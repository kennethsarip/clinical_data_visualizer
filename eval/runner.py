"""Phase 5 eval runner (CLAUDE.md §9, §14 Phase 5): every eval question through the pipeline,
scored against the expectations written before the code, with citation and network metrics."""

import logging
import re
import statistics
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.checks import CheckContext, excerpt_matches, run_checks
from app.pipeline import Checker, DependencyError, Pipeline
from app.schemas import (
    AnyResponse,
    CheckError,
    ClarificationResponse,
    DegradedResponse,
    FilterKey,
    NetworkVisualization,
    NoResultsResponse,
    OkResponse,
    Provenance,
    VisualizeRequest,
)
from app.viz import PROSE_FALLBACK_NOTE
from eval.questions import EvalQuestion, Expected

__all__ = ["Checker"]

logger = logging.getLogger(__name__)

# planner._apply_fields writes "The <key> field (<value>) overrides <value> from the question."
OVERRIDE_NOTE = re.compile(r"^The \w+ field \(.+\) overrides .+ from the question\.$")


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CitationMetrics(_Result):
    items: int  # rows, nodes and edges holding at least one trial
    fully_cited: int  # items citing min(trial_count, citation_cap) distinct trials
    citations: int
    excerpts_passed: int  # citations whose excerpt holds against the fetched record


class NetworkMetrics(_Result):
    nodes: int
    edges: int
    fallback_used: bool
    nodes_removed: int
    edges_removed: int
    placebo_excluded: int
    non_drug_excluded: int
    no_drug_excluded: int


class OffFilterMetrics(_Result):
    trials_checked: int  # distinct charted trials
    off_filter: int  # charted trials failing at least one applied filter
    by_filter: dict[str, int]  # filter key -> charted trials failing it


class QuestionResult(_Result):
    id: str
    question_class: str
    passed: bool
    failures: list[str]
    http: int
    status: str | None
    analysis: str | None
    viz_type: str | None
    records_fetched: int | None
    records_total: int | None
    capped: bool | None
    latency_s: float
    check_attempts: int
    repaired: bool
    failed_checks: list[str]
    prose_fallback: bool
    citations: CitationMetrics | None
    network: NetworkMetrics | None
    off_filter: OffFilterMetrics | None = None
    error: str | None


class Summary(_Result):
    questions: int
    passed: int
    by_class: dict[str, list[int]]  # class -> [passed, total]
    failure_modes: dict[str, int]
    repaired: int
    prose_fallbacks: int
    latency_p50_s: float
    latency_max_s: float
    items: int
    items_fully_cited: int
    citations: int
    excerpts_passed: int
    off_filter_trials_checked: int
    off_filter_trials: int  # Phase 6 done when: 0 across the eval set


class RecordingChecker:
    """Wraps the pipeline's checker to see every attempt: a second attempt is the repair (§7.7),
    and the last context holds the records the excerpts are checked against."""

    def __init__(self, inner: Checker) -> None:
        self.inner = inner
        self.attempts: list[list[CheckError]] = []
        self.last: tuple[OkResponse, CheckContext] | None = None

    def __call__(self, response: OkResponse, context: CheckContext) -> list[CheckError]:
        errors = self.inner(response, context)
        self.attempts.append(errors)
        self.last = (response, context)
        return errors


def run_question(
    question: EvalQuestion,
    make_pipeline: Callable[[Checker], Pipeline],
    clock: Callable[[], float] = time.perf_counter,
    inner: Checker = run_checks,
) -> QuestionResult:
    """One question end to end. Never raises: every outcome, including a crash, is a result."""
    checker = RecordingChecker(inner)
    response: AnyResponse | None = None
    http, error = 200, None
    start = clock()
    try:
        request = VisualizeRequest.model_validate(question.request)
    except ValidationError as exc:
        http, error = 422, str(exc)
    else:
        try:
            response = make_pipeline(checker).run(request)
        except DependencyError as exc:
            http, error = 502, str(exc)
        except Exception as exc:  # a crash is a finding, so the run goes on
            logger.exception("question %s crashed", question.id)
            http, error = 500, repr(exc)
    latency = round(clock() - start, 3)
    return _result(question, response, http, error, latency, checker)


def _result(
    question: EvalQuestion,
    response: AnyResponse | None,
    http: int,
    error: str | None,
    latency: float,
    checker: RecordingChecker,
) -> QuestionResult:
    ok = response if isinstance(response, OkResponse) else None
    first = checker.attempts[0] if checker.attempts else []
    records = checker.last[1].records if ok and checker.last else None
    off_filter = off_filter_metrics(ok, records) if ok and records is not None else None
    failures = _failures(question.expected, response, http)
    if off_filter and off_filter.off_filter:
        failures.append("off_filter")
    interpretation = ok.meta.interpretation if ok else None
    return QuestionResult(
        id=question.id,
        question_class=question.question_class,
        passed=not failures,
        failures=failures,
        http=http,
        status=response.status if response else None,
        analysis=f"{interpretation.intent}.{interpretation.dimension}" if interpretation else None,
        viz_type=ok.visualization.type if ok else None,
        records_fetched=sum(s.fetched for s in ok.meta.sample) if ok else None,
        records_total=sum(s.total for s in ok.meta.sample) if ok else None,
        capped=any(s.capped for s in ok.meta.sample) if ok else None,
        latency_s=latency,
        check_attempts=len(checker.attempts),
        repaired=ok is not None and len(checker.attempts) > 1,
        failed_checks=sorted({e.check for e in first}),
        prose_fallback=ok is not None and PROSE_FALLBACK_NOTE in ok.meta.notes,
        citations=citation_metrics(ok, records) if ok and records is not None else None,
        network=network_metrics(ok) if ok else None,
        off_filter=off_filter,
        error=error,
    )


def _failures(e: Expected, response: AnyResponse | None, http: int) -> list[str]:
    """The ways a response misses its expectation, named so a run can count them by kind."""
    if http != e.http:
        return ["dependency_error" if http == 502 else "crash" if http == 500 else "wrong_http"]
    if response is None:
        return []
    if response.status != e.status:
        return ["wrong_status"]
    if isinstance(response, ClarificationResponse):
        return [] if response.meta.missing == e.missing else ["wrong_missing"]
    if isinstance(response, DegradedResponse):
        return []
    failures = _filter_failures(e, response)
    if isinstance(response, NoResultsResponse):
        if _fold_list(response.meta.not_found) != _fold_list(e.not_found):
            failures.append("wrong_not_found")
        return failures
    return _ok_failures(e, response) + failures


def _ok_failures(e: Expected, response: OkResponse) -> list[str]:
    failures = []
    interpretation = response.meta.interpretation
    if f"{interpretation.intent}.{interpretation.dimension}" != e.analysis:
        failures.append("wrong_analysis")
    if response.visualization.type != e.viz_type:
        failures.append("wrong_viz_type")
    if e.cohorts is not None:
        cohorts = interpretation.cohorts or []
        # Compared pairwise only once the counts agree: zip would hide an extra cohort.
        if len(cohorts) != len(e.cohorts) or any(
            c.label.casefold() != x.label.casefold()
            or str(c.filters.get(x.entity, "")).casefold() != x.value.casefold()
            for c, x in zip(cohorts, e.cohorts, strict=True)
        ):
            failures.append("wrong_cohorts")
    return failures


def _filter_failures(e: Expected, response: OkResponse | NoResultsResponse) -> list[str]:
    failures = []
    filters = response.meta.filters
    if _fold(filters.stated) != _fold(e.stated):
        failures.append("wrong_stated")
    # Inferred values fold like stated ones: an enum may come back as RECRUITING or recruiting.
    inferred = _fold(filters.inferred)
    accepted: dict[str, set[str]] = {
        k: {str(v).casefold() for v in values} for k, values in e.inferred.items()
    }
    if inferred.keys() != accepted.keys() or any(v not in accepted[k] for k, v in inferred.items()):
        failures.append("wrong_inferred")
    if e.status == "no_results":
        return failures  # overrides are asserted on charted answers only
    capped = isinstance(response, OkResponse) and any(s.capped for s in response.meta.sample)
    if e.capped is not None and capped != e.capped:
        failures.append("cap_mismatch")
    overridden = any(OVERRIDE_NOTE.match(n) for n in response.meta.notes)
    if overridden != e.field_override:
        failures.append("missing_override_note" if e.field_override else "unexpected_override_note")
    return failures


def _fold(values: Mapping[FilterKey, str | int]) -> dict[str, str]:
    return {k: str(v).casefold() for k, v in values.items()}


def _fold_list(values: list[str]) -> list[str]:
    return [v.casefold() for v in values]


def citation_metrics(
    response: OkResponse, records: Mapping[str, dict[str, Any]]
) -> CitationMetrics:
    """Share of items fully cited (up to the citation cap, §7.5) and of excerpts that hold
    against the records this answer was built from (§7.6), recomputed outside the pipeline."""
    cap = response.meta.citation_cap
    items = [item for item in _provenance(response) if item.trial_count > 0]
    fully = sum(len({c.nct_id for c in i.citations}) >= min(i.trial_count, cap) for i in items)
    citations = [c for item in items for c in item.citations]
    passed = sum(c.nct_id in records and excerpt_matches(records[c.nct_id], c) for c in citations)
    return CitationMetrics(
        items=len(items), fully_cited=fully, citations=len(citations), excerpts_passed=passed
    )


def off_filter_metrics(
    response: OkResponse, records: Mapping[str, dict[str, Any]]
) -> OffFilterMetrics:
    """Charted trials that fail an applied filter, read straight from the raw records rather than
    through `normalize` or `checks.py`, so a bug there cannot hide one (Phase 6 step 0).

    Entity filters are searches by design (§7.3), so only the exact filters are tested, each with
    the API's meaning (§8.4): a phase in the record's list, the status, a start year in range, and
    a site whose country equals the filter (records use the registry's country names).
    """
    filters = {**response.meta.filters.stated, **response.meta.filters.inferred}
    charted = {n for item in _provenance(response) for n in item.nct_ids}
    failing: Counter[str] = Counter()
    off = 0
    for nct_id in charted:
        record = records.get(nct_id)
        failed = ["no_record"] if record is None else _failed_filters(record, filters)
        failing.update(failed)
        off += bool(failed)
    return OffFilterMetrics(trials_checked=len(charted), off_filter=off, by_filter=dict(failing))


def _failed_filters(record: dict[str, Any], filters: Mapping[FilterKey, str | int]) -> list[str]:
    section = record.get("protocolSection", {})
    status = section.get("statusModule", {})
    start = status.get("startDateStruct", {}).get("date")
    year = int(start[:4]) if start else None
    locations = section.get("contactsLocationsModule", {}).get("locations", [])
    observed: dict[str, Any] = {
        "trial_phase": section.get("designModule", {}).get("phases", []),
        "overall_status": status.get("overallStatus"),
        "start_year": year,
        "end_year": year,
        "country": {str(loc.get("country", "")).casefold() for loc in locations},
    }
    return [k for k, v in filters.items() if k in observed and not _meets(k, v, observed[k])]


def _meets(key: str, value: str | int, observed: Any) -> bool:
    if key in ("trial_phase", "country"):  # one of the record's values
        return str(value).casefold() in {str(o).casefold() for o in observed}
    if key == "overall_status":
        return bool(observed == value)
    if observed is None:  # no start date cannot meet a year bound
        return False
    return bool(observed >= int(value) if key == "start_year" else observed <= int(value))


def _provenance(response: OkResponse) -> list[Provenance]:
    spec = response.visualization
    if isinstance(spec, NetworkVisualization):
        return [*spec.data.nodes, *spec.data.edges]
    return list(spec.data)


# The §6 drug-rule exclusions, as `meta.excluded` names them.
DRUG_RULES = {
    "placebo": "placebo",
    "non_drug": "non-drug intervention",
    "no_drug": "no drug intervention",
}


def network_metrics(response: OkResponse) -> NetworkMetrics | None:
    spec, pruning = response.visualization, response.meta.pruning
    if not isinstance(spec, NetworkVisualization) or pruning is None:
        return None
    excluded = {e.rule: e.count for e in response.meta.excluded}
    return NetworkMetrics(
        nodes=len(spec.data.nodes),
        edges=len(spec.data.edges),
        fallback_used=pruning.fallback_used,
        nodes_removed=pruning.nodes_removed,
        edges_removed=pruning.edges_removed,
        placebo_excluded=excluded.get(DRUG_RULES["placebo"], 0),
        non_drug_excluded=excluded.get(DRUG_RULES["non_drug"], 0),
        no_drug_excluded=excluded.get(DRUG_RULES["no_drug"], 0),
    )


def summarize(results: list[QuestionResult]) -> Summary:
    by_class: dict[str, list[int]] = {}
    for r in results:
        tally = by_class.setdefault(r.question_class, [0, 0])
        tally[0] += r.passed
        tally[1] += 1
    cited = [r.citations for r in results if r.citations]
    filtered = [r.off_filter for r in results if r.off_filter]
    # A request rejected at validation (422) does no work; its ~0 s would drag the median down.
    latencies = [r.latency_s for r in results if r.http != 422]
    return Summary(
        questions=len(results),
        passed=sum(r.passed for r in results),
        by_class=by_class,
        failure_modes=dict(Counter(f for r in results for f in r.failures)),
        repaired=sum(r.repaired for r in results),
        prose_fallbacks=sum(r.prose_fallback for r in results),
        latency_p50_s=statistics.median(latencies) if latencies else 0.0,
        latency_max_s=max(latencies, default=0.0),
        items=sum(c.items for c in cited),
        items_fully_cited=sum(c.fully_cited for c in cited),
        citations=sum(c.citations for c in cited),
        excerpts_passed=sum(c.excerpts_passed for c in cited),
        off_filter_trials_checked=sum(f.trials_checked for f in filtered),
        off_filter_trials=sum(f.off_filter for f in filtered),
    )


class RunMeta(_Result):
    """What a run depends on besides the code, so two runs can be compared fairly."""

    started_at: str
    git_commit: str
    model: str
    reasoning_effort: str
    fetch_cap: int
    today: date  # the pipeline's "today", pinned to when the expectations were written
    questions_written: str


class RunResult(_Result):
    meta: RunMeta
    summary: Summary
    results: list[QuestionResult]


def run_all(
    questions: list[EvalQuestion], make_pipeline: Callable[[Checker], Pipeline], meta: RunMeta
) -> RunResult:
    results = []
    for n, question in enumerate(questions, 1):
        result = run_question(question, make_pipeline)
        verdict = "pass" if result.passed else f"FAIL {', '.join(result.failures)}"
        logger.info(
            "[%d/%d] %s: %s (%.1f s)", n, len(questions), question.id, verdict, result.latency_s
        )
        results.append(result)
    return RunResult(meta=meta, summary=summarize(results), results=results)
