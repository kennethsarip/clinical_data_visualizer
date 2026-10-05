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
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from urllib.parse import parse_qsl

from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    Aggregator,
    CohortTrials,
    GraphAggregation,
    Registry,
)
from app.checks import CheckContext, run_checks
from app.conformance import OffFilterBatchError, conform
from app.ctgov import FetchResult, UpstreamError
from app.llm import LLMClient, LLMUpstreamError
from app.normalize import RecordShapeError, batch_of, normalize_records
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
from app.viz import SOURCE, Prose, assemble, default_title, write_prose

logger = logging.getLogger(__name__)

NOT_WIDENED_NOTE = "No trials match all applied filters. The search was not widened."

Checker = Callable[[OkResponse, CheckContext], list[CheckError]]


class Fetcher(Protocol):
    """The record source: `TrialCache` in the app, a fake in tests."""

    def fetch_many(self, filters: Sequence[RetrievalFilters]) -> list[FetchResult]: ...
    def count(self, filters: RetrievalFilters) -> int: ...


class DependencyError(RuntimeError):
    """A dependency failed (ClinicalTrials.gov, the LLM, or the API's record format): HTTP 502."""


@dataclass(frozen=True)
class _Target:
    """One search: a cohort's label (None without cohorts) and its filters."""

    label: str | None
    filters: RetrievalFilters


@dataclass(frozen=True)
class _Fetched:
    cohorts: list[CohortTrials]
    records: dict[str, dict[str, Any]]  # nct_id -> raw record, the retrieved set the checks use
    sent: list[dict[str, str]]  # the API params each cohort was fetched with


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
        aggregator = self.registry.get(planned.intent, planned.dimension)
        targets = [_Target(c.label, c.filters) for c in planned.cohorts] or [
            _Target(None, planned.filters)
        ]
        # The title is written from the plan alone (§7.2), so it runs while the trials are
        # fetched. Only an `ok` answer waits for it; any other outcome returns at once and the
        # call finishes unread in the background.
        pool = ThreadPoolExecutor(1, thread_name_prefix="title")
        try:
            prose = pool.submit(
                write_prose,
                self.llm,
                query=request.query,
                aggregator=aggregator,
                cohorts=targets,
                filters=_filters(planned),
            )
            prose.add_done_callback(_log_title_failure)
            return self._answer(planned, aggregator, targets, prose)
        finally:
            pool.shutdown(wait=False)

    def _answer(
        self,
        plan: QueryPlan,
        aggregator: Aggregator,
        targets: list["_Target"],
        prose: "Future[Prose]",
    ) -> AnyResponse:
        try:
            fetched = self._fetch(targets)
        except OffFilterBatchError as exc:
            return _degraded(
                _filters(plan), plan.assumptions, [CheckError(check="retrieval", message=str(exc))]
            )
        if not fetched.records:
            return self._zero_results(plan)
        result = aggregator.aggregate(fetched.cohorts)
        if _charts_nothing(result):
            return _nothing_charted(plan, result, len(fetched.records))
        return self._checked(plan, aggregator, result, fetched, prose.result())

    def _fetch(self, targets: list["_Target"]) -> _Fetched:
        """One fetch per cohort (§7.2), downloaded together; a plan without cohorts is one
        unlabeled cohort."""
        results = self.fetcher.fetch_many([t.filters for t in targets])
        cohorts: list[CohortTrials] = []
        records: dict[str, dict[str, Any]] = {}
        for target, result in zip(targets, results, strict=True):
            # Normalize first: a record without an nctId is unreadable and set aside (counted
            # in meta), so it must not abort the request while building the lookup.
            batch = normalize_records(result.records)
            readable = {t.nct_id for t in batch.trials}
            records |= {nct_id: r for r in result.records if (nct_id := _nct_id(r)) in readable}
            kept, off_filter = conform(batch.trials, target.filters)
            batch = batch_of(kept, batch.unreadable)
            cohorts.append(
                CohortTrials(target.label, batch, target.filters, result.total, off_filter)
            )
        sent = [dict(parse_qsl(result.params_key)) for result in results]
        return _Fetched(cohorts, records, sent)

    def _checked(
        self,
        plan: QueryPlan,
        aggregator: Aggregator,
        result: Aggregation | GraphAggregation,
        fetched: _Fetched,
        prose: Prose,
    ) -> AnyResponse:
        """§1 steps 7-9: prose, assembly, checks, one repair without the prose, else degraded."""
        filters = _filters(plan)
        context = CheckContext(aggregator.shape, fetched.records, fetched.sent)

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


def _log_title_failure(future: "Future[Prose]") -> None:
    """A bug in the title thread: an `ok` answer re-raises it from `result()`, but an answer that
    abandoned the call would otherwise lose it."""
    if not future.cancelled() and (error := future.exception()) is not None:
        logger.error("title call failed: %r", error, exc_info=error)


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
