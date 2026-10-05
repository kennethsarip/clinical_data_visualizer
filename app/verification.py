"""The verification ledger (CLAUDE.md §14 Phase 7 step 5): `meta.verification` on every status.

One entry per pipeline step, in order, with the checks it ran, the items they verified and a
one-line result. Everything here is Python, written from counts already in the response or the
plan, so the ledger cannot claim a verification that did not run: a step's status follows the
check outcomes the pipeline passes in, and an answer that stopped early marks the rest
`not_reached`. Each spec check belongs to exactly one step (CHECK_STEP).
"""

from collections.abc import Mapping, Sequence

from app.normalize import UNREADABLE_RULE
from app.planner import Clarification, QueryPlan
from app.schemas import (
    CheckError,
    LedgerStep,
    NetworkVisualization,
    OkResponse,
    Provenance,
    VerificationStep,
)

STEPS: tuple[LedgerStep, ...] = (
    "request",
    "plan",
    "retrieval",
    "records",
    "aggregation",
    "citations",
    "prose",
    "response",
)
REQUEST_CHECKS = ["request schema", "year range"]
PLAN_CHECKS = ["plan schema", "registered analysis", "constraint quotes", "name coverage", "anchor"]
STEP_CHECKS: Mapping[LedgerStep, list[str]] = {
    "retrieval": ["conformance"],
    "records": ["normalize"],
    "aggregation": ["membership", "recount", "reconciliation", "accounting"],
    "citations": ["citation ids", "excerpts", "coverage", "summaries"],
    "prose": ["title"],
    "response": ["schema", "encoding", "shape", "assumptions", "disclosures"],
}
CHECK_STEP: Mapping[str, LedgerStep] = {
    check: step for step, checks in STEP_CHECKS.items() for check in checks
}
OFF_FILTER_PREFIX = "outside the "


def _entry(
    step: LedgerStep, status: str, checks: list[str], verified: int, total: int, result: str
) -> VerificationStep:
    return VerificationStep.model_validate(
        {
            "step": step,
            "status": status,
            "checks": checks,
            "verified": verified,
            "total": total,
            "result": result,
        }
    )


def _request() -> VerificationStep:
    return _entry("request", "passed", REQUEST_CHECKS, 1, 1, "The request fields are valid.")


def _not_reached(after: LedgerStep) -> list[VerificationStep]:
    rest = STEPS[STEPS.index(after) + 1 :]
    return [_entry(s, "not_reached", STEP_CHECKS.get(s, []), 0, 0, "Not reached.") for s in rest]


def _plan_passed(plan: QueryPlan) -> VerificationStep:
    applied = len(plan.stated) + len(plan.inferred) + len(plan.cohorts)
    applied_text = _plural(applied, "filter or cohort", "filters or cohorts")
    result = f"Read as {plan.analysis}; {applied_text} applied"
    result += f", {len(plan.inferred)} inferred and disclosed." if plan.inferred else "."
    return _entry("plan", "passed", PLAN_CHECKS, applied, applied, result)


def for_clarification(clarification: Clarification) -> list[VerificationStep]:
    asked = len(clarification.missing) + len(clarification.unapplied) + len(clarification.conflicts)
    result = " ".join(clarification.notes[:2]) or "The question needs more detail to chart."
    plan = _entry("plan", "stopped", PLAN_CHECKS, 0, max(asked, 1), f"Stopped: {result}")
    return [_request(), plan, *_not_reached("plan")]


def for_plan_error(message: str) -> list[VerificationStep]:
    plan = _entry(
        "plan", "failed", PLAN_CHECKS, 0, 1, f"The plan failed validation twice: {message}"
    )
    return [_request(), plan, *_not_reached("plan")]


def for_no_results(plan: QueryPlan, notes: Sequence[str]) -> list[VerificationStep]:
    result = f"Stopped: {notes[0]}" if notes else "Stopped: no trial matches."
    retrieval = _entry("retrieval", "stopped", STEP_CHECKS["retrieval"], 0, 0, result)
    return [_request(), _plan_passed(plan), retrieval, *_not_reached("retrieval")]


def for_nothing_charted(plan: QueryPlan, fetched: int, note: str) -> list[VerificationStep]:
    retrieval = _entry(
        "retrieval", "passed", STEP_CHECKS["retrieval"], fetched, fetched, f"Fetched {fetched}."
    )
    records = _entry("records", "passed", STEP_CHECKS["records"], fetched, fetched, "Read.")
    aggregation = _entry(
        "aggregation", "stopped", STEP_CHECKS["aggregation"], 0, fetched, f"Stopped: {note}"
    )
    return [
        _request(),
        _plan_passed(plan),
        retrieval,
        records,
        aggregation,
        *_not_reached("aggregation"),
    ]


def for_retrieval_error(plan: QueryPlan, message: str) -> list[VerificationStep]:
    retrieval = _entry("retrieval", "failed", STEP_CHECKS["retrieval"], 0, 1, message)
    return [_request(), _plan_passed(plan), retrieval, *_not_reached("retrieval")]


def for_answer(
    response: OkResponse, plan: QueryPlan, prose_fallback: bool, errors: Sequence[CheckError] = ()
) -> list[VerificationStep]:
    """The ledger of an answer that reached the checks: `ok`, or `degraded` with `errors`."""
    failing: dict[LedgerStep, list[CheckError]] = {}
    for e in errors:
        failing.setdefault(CHECK_STEP.get(e.check, "response"), []).append(e)
    counts = _counts(response)
    entries = [_request(), _plan_passed(plan)]
    for step in STEPS[2:]:
        verified, total, result = counts[step]
        if step == "prose" and prose_fallback:
            result = "Plain title used: the LLM title was unavailable or failed its check."
        if step in failing:
            names = sorted({e.check for e in failing[step]})
            first = failing[step][0].message
            checks = STEP_CHECKS[step]
            held = len([c for c in checks if c not in names])
            entries.append(
                _entry(step, "failed", checks, held, len(checks), f"{', '.join(names)}: {first}")
            )
        else:
            entries.append(_entry(step, "passed", STEP_CHECKS[step], verified, total, result))
    return entries


def _counts(response: OkResponse) -> dict[LedgerStep, tuple[int, int, str]]:
    meta = response.meta
    fetched = sum(s.fetched for s in meta.sample)
    total = sum(s.total for s in meta.sample)
    off = sum(e.count for e in meta.excluded if e.rule.startswith(OFF_FILTER_PREFIX))
    unreadable = sum(e.count for e in meta.excluded if e.rule.startswith(UNREADABLE_RULE))
    items = _items(response)
    charted = len({n for nct_ids, _ in items for n in nct_ids})
    citations = sum(cited for _, cited in items)
    reasons = len(meta.excluded)
    retrieved = fetched - unreadable
    fetch_line = f"Fetched {fetched} of {total} matching trials"
    fetch_line += " (the fetch cap)." if fetched < total else "."
    if off:
        fetch_line += f" {off} outside an exact filter dropped and listed."
    return {
        "retrieval": (fetched - off, fetched, fetch_line),
        "records": (retrieved, fetched, f"{retrieved} of {fetched} records readable."),
        "aggregation": (
            retrieved,
            retrieved,
            f"All {_plural(retrieved, 'trial', 'trials')} accounted for: {charted} charted in "
            f"{_plural(len(items), 'datum', 'data')}"
            + (
                f", the rest listed under {_plural(reasons, 'reason', 'reasons')}"
                if reasons
                else ""
            )
            + "; each datum recounted from its records.",
        ),
        "citations": (
            citations,
            citations,
            f"{citations} citations verified: each excerpt is its record's value at its field.",
        ),
        "prose": (1, 1, "Title written by the LLM; it holds no number outside the filters."),
        "response": (5, 5, "The response matches the documented schema and its disclosures."),
    }


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _items(response: OkResponse) -> list[tuple[list[str], int]]:
    spec = response.visualization
    rows: list[Provenance] = (
        [*spec.data.nodes, *spec.data.edges]
        if isinstance(spec, NetworkVisualization)
        else list(spec.data)
    )
    return [(list(r.nct_ids), len(r.citations)) for r in rows if r.trial_count]
