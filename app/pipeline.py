"""The CLAUDE.md §1 steps, repair-once, status selection and error -> status mapping.

This is the one place errors become outcomes (§7.7, §10):
- the plan still invalid after one retry -> `degraded` (check "plan");
- a check still failing after one repair -> `degraded` with the check errors;
- ClinicalTrials.gov or the LLM unreachable, or a batch of mostly unreadable records (the API
  format has probably changed) -> `DependencyError`, which the route returns as 502;
- anything else (an assembly or citation bug) propagates: it is a defect, not an outcome.

The repair rebuilds the spec from the same rows with the LLM prose removed (the plain title and
no LLM notes): everything else in the spec is deterministic, so the prose is the only part a
rebuild can change. The API is never re-queried (§7.7).
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    Aggregator,
    CohortTrials,
    GraphAggregation,
    Registry,
)
from app.checks import CheckContext, run_checks
from app.ctgov import FetchResult, UpstreamError
from app.llm import LLMClient, LLMUpstreamError
from app.normalize import RecordShapeError, normalize_records
from app.planner import ANCHORS, Clarification, PlanError, QueryPlan, plan_request
from app.schemas import (
    AnyResponse,
    CheckError,
    ClarificationMeta,
    ClarificationResponse,
    DegradedMeta,
    DegradedResponse,
    Filters,
    NoResultsMeta,
    NoResultsResponse,
    OkResponse,
    RetrievalFilters,
    VisualizeRequest,
)
from app.viz import SOURCE, assemble, default_title, write_prose

logger = logging.getLogger(__name__)

NOT_WIDENED_NOTE = "No trials match all applied filters. The search was not widened."

Checker = Callable[[OkResponse, CheckContext], list[CheckError]]


class Fetcher(Protocol):
    """The record source: `TrialCache` in the app, a fake in tests."""

    def fetch(self, filters: RetrievalFilters) -> FetchResult: ...
    def count(self, filters: RetrievalFilters) -> int: ...


class DependencyError(RuntimeError):
    """A dependency failed (ClinicalTrials.gov, the LLM, or the API's record format): HTTP 502."""


@dataclass(frozen=True)
class _Fetched:
    cohorts: list[CohortTrials]
    records: dict[str, dict[str, Any]]  # nct_id -> raw record, the retrieved set the checks use


@dataclass(frozen=True)
class Pipeline:
    llm: LLMClient
    fetcher: Fetcher
    registry: Registry = REGISTRY
    checker: Checker = run_checks
    today: Callable[[], date] = date.today

    def run(self, request: VisualizeRequest) -> AnyResponse:
        try:
            return self._run(request)
        except (UpstreamError, RecordShapeError) as exc:
            raise DependencyError(f"ClinicalTrials.gov: {exc}") from exc
        except LLMUpstreamError as exc:
            raise DependencyError(f"LLM: {exc}") from exc

    def _run(self, request: VisualizeRequest) -> AnyResponse:
        try:
            planned = plan_request(request, self.llm, self.today(), self.registry)
        except PlanError as exc:
            stated = request.model_dump(mode="json", exclude={"query"}, exclude_none=True)
            return _degraded(Filters(stated=stated, inferred={}), (), [_plan_error(exc)])
        if isinstance(planned, Clarification):
            return _clarification(planned)
        fetched = self._fetch(planned)
        if not fetched.records:
            return self._zero_results(planned)
        aggregator = self.registry.get(planned.intent, planned.dimension)
        result = aggregator.aggregate(fetched.cohorts)
        if _charts_nothing(result):
            return _nothing_charted(planned, result, len(fetched.records))
        return self._checked(request, planned, aggregator, result, fetched)

    def _fetch(self, plan: QueryPlan) -> _Fetched:
        """One fetch per cohort (§7.2); a plan without cohorts is one unlabeled cohort."""
        targets: list[tuple[str | None, RetrievalFilters]] = [
            (c.label, c.filters) for c in plan.cohorts
        ] or [(None, plan.filters)]
        cohorts: list[CohortTrials] = []
        records: dict[str, dict[str, Any]] = {}
        for label, filters in targets:
            result = self.fetcher.fetch(filters)
            # Normalize first: a record without an nctId is unreadable and set aside (counted
            # in meta), so it must not abort the request while building the lookup.
            batch = normalize_records(result.records)
            readable = {t.nct_id for t in batch.trials}
            records |= {nct_id: r for r in result.records if (nct_id := _nct_id(r)) in readable}
            cohorts.append(CohortTrials(label, batch, filters, result.total))
        return _Fetched(cohorts, records)

    def _checked(
        self,
        request: VisualizeRequest,
        plan: QueryPlan,
        aggregator: Aggregator,
        result: Aggregation | GraphAggregation,
        fetched: _Fetched,
    ) -> AnyResponse:
        """§1 steps 7-9: prose, assembly, checks, one repair without the prose, else degraded."""
        filters = _filters(plan)
        prose = write_prose(
            self.llm,
            query=request.query,
            aggregator=aggregator,
            cohorts=fetched.cohorts,
            filters=filters,
        )
        context = CheckContext(aggregator.shape, fetched.records)

        def build(title: str, notes: Sequence[str]) -> OkResponse:
            return assemble(
                aggregator,
                result,
                fetched.cohorts,
                filters=filters,
                title=title,
                assumptions=plan.assumptions,
                notes=(*plan.notes, *notes),
            )

        response = build(prose.title, prose.notes)
        errors = self.checker(response, context)
        if not errors:
            return response
        logger.warning("checks failed, repairing once without LLM prose: %s", errors)
        repaired = build(default_title(aggregator, fetched.cohorts), ())
        errors = self.checker(repaired, context)
        if not errors:
            return repaired
        logger.error("checks still failing after the repair: %s", errors)
        return _degraded(filters, plan.assumptions, errors)

    def _zero_results(self, plan: QueryPlan) -> NoResultsResponse:
        """§7.8: tell "not found" from "over-filtered" by probing each entity alone. A search on
        the entity alone already ran when it was the only filter, so that probe is skipped."""
        not_found: list[str] = []
        for filters in [c.filters for c in plan.cohorts] or [plan.filters]:
            entities = {k: v for k in ANCHORS if (v := getattr(filters, k)) is not None}
            alone_ran = len(filters.model_dump(exclude_none=True)) == 1
            for key, value in entities.items():
                if alone_ran or self.fetcher.count(RetrievalFilters(**{key: value})) == 0:
                    not_found.append(value)
        notes = [
            f"No trial on ClinicalTrials.gov lists {name}. No similar name was substituted."
            for name in not_found
        ] or [NOT_WIDENED_NOTE]
        return _no_results(plan, not_found, notes)


def _nct_id(record: dict[str, Any]) -> str | None:
    value = record.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
    return value if isinstance(value, str) else None


def _filters(plan: QueryPlan) -> Filters:
    return Filters.model_validate({"stated": plan.stated, "inferred": plan.inferred})


def _plan_error(exc: PlanError) -> CheckError:
    return CheckError(check="plan", message=str(exc))


def _charts_nothing(result: Aggregation | GraphAggregation) -> bool:
    """No trial in any row, or a network with no edge: §7.6 `shape` would block it as an empty
    chart, but the honest answer is `no_results` naming why (§14 Phase 3 step 4)."""
    if isinstance(result, GraphAggregation):
        return not result.edges
    return not any(row.nct_ids for row in result.rows)


def _nothing_charted(
    plan: QueryPlan, result: Aggregation | GraphAggregation, retrieved: int
) -> NoResultsResponse:
    reasons = ", ".join(f"{count} {rule}" for rule, count in result.excluded.items() if count)
    note = f"{retrieved} trials matched, but none could be charted"
    note += f" ({reasons})." if reasons else "."
    return _no_results(plan, [], [note])


def _no_results(plan: QueryPlan, not_found: list[str], notes: list[str]) -> NoResultsResponse:
    meta = NoResultsMeta(
        source=SOURCE,
        filters=_filters(plan),
        assumptions=list(plan.assumptions),
        notes=[*plan.notes, *notes],
        not_found=not_found,
    )
    return NoResultsResponse(status="no_results", visualization=None, trials={}, meta=meta)


def _clarification(clarification: Clarification) -> ClarificationResponse:
    meta = ClarificationMeta(
        source=SOURCE,
        filters=Filters.model_validate({"stated": clarification.stated, "inferred": {}}),
        assumptions=[],
        notes=list(clarification.notes),
        missing=list(clarification.missing),
    )
    return ClarificationResponse(
        status="clarification_needed", visualization=None, trials={}, meta=meta
    )


def _degraded(
    filters: Filters, assumptions: Sequence[str], errors: list[CheckError]
) -> DegradedResponse:
    meta = DegradedMeta(
        source=SOURCE, filters=filters, assumptions=list(assumptions), notes=[], errors=errors
    )
    return DegradedResponse(status="degraded", visualization=None, trials={}, meta=meta)
