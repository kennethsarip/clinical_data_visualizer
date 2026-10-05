"""Request -> plan: one LLM call for interpretation, then deterministic rules (CLAUDE.md §7.2).

The LLM picks one registered analysis key and copies filter values and cohorts from the query
text. Everything that decides what is fetched or disclosed is Python, so it is testable without
the LLM:
- request fields override the query, with a note (§7.3);
- a filter is stated iff it came from a field or appears verbatim in the query, else inferred and
  disclosed as an assumption (§7.3);
- comparisons take 2-4 cohorts of one entity kind (§7.2);
- the anchor rule: a drug, condition or sponsor must be named (§7.8).

An answer that breaks a rule only the LLM can fix raises `LLMOutputError` and is retried once
with the error; a second failure raises `PlanError` (`degraded`, §7.7). A request the user must
fix returns a `Clarification`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, get_args

from pydantic import ValidationError

from app.aggregators.registry import REGISTRY, Dimension, Intent, Registry
from app.llm import LLMClient, LLMOutputError, strict_json_schema
from app.schemas import FilterKey, LLMCohort, LLMPlan, RetrievalFilters, VisualizeRequest
from app.vocab import Phase, Status, label

PLAN_SCHEMA_NAME = "query_plan"
ANCHORS: tuple[FilterKey, ...] = ("drug_name", "condition", "sponsor")
MIN_COHORTS, MAX_COHORTS = 2, 4
ANCHOR_NOTE = "Name a drug, condition or sponsor to chart."

FilterValues = dict[FilterKey, str | int]
FILTER_KEYS: tuple[FilterKey, ...] = get_args(FilterKey)

# One line per intent and dimension, joined into the prompt's key list. A newly registered
# aggregator fails `test_prompt_describes_every_registered_key...` until it is described here.
INTENT_GUIDE: Mapping[Intent, str] = {
    Intent.TIME_TREND: "how many trials started per year",
    Intent.DISTRIBUTION: "how one cohort's trial counts split into categories (never enrollment)",
    Intent.COMPARISON: "the same categories side by side for 2-4 named cohorts (needs cohorts)",
    Intent.GEOGRAPHIC: "which countries host the trials",
    Intent.NUMERIC: "enrollment (participants, sample size) per trial",
    Intent.NETWORK: "which entities appear together in the same trials",
}
DIMENSION_GUIDE: Mapping[Dimension, str] = {
    Dimension.PHASE: "by trial phase",
    Dimension.OVERALL_STATUS: "by recruitment status (recruiting, completed, ...)",
    Dimension.INTERVENTION_TYPE: "by intervention type (drug, device, behavioral, ...)",
    Dimension.SPONSOR_CLASS: "by sponsor category (industry, NIH, academic/other, ...)",
    Dimension.DRUG: "by drug (top drugs)",
    Dimension.SPONSOR: "by lead sponsor name (top sponsors)",
    Dimension.CONDITION: "by condition (top conditions)",
    Dimension.COUNTRY: "by country",
    Dimension.START_YEAR: "by start year",
    Dimension.ENROLLMENT_BY_START_DATE: "each trial's enrollment by start date (over time)",
    Dimension.ENROLLMENT: "distribution of enrollment sizes (histogram)",
    Dimension.SPONSOR_DRUG: "sponsors linked to the drugs they test",
    Dimension.DRUG_DRUG: "drugs tested together in combination",
    Dimension.CONDITION_DRUG: "conditions linked to the drugs tested for them",
}
FILTER_NAMES: Mapping[str, str] = {
    "drug_name": "drug",
    "condition": "condition",
    "sponsor": "sponsor",
    "country": "country",
    "trial_phase": "phase",
    "overall_status": "status",
    "start_year": "start year from",
    "end_year": "start year until",
}
_ENUM_FILTERS: Mapping[str, type[Phase] | type[Status]] = {
    "trial_phase": Phase,
    "overall_status": Status,
}


class PlanError(RuntimeError):
    """The LLM's plan was still invalid after one retry with the error."""


@dataclass(frozen=True)
class Cohort:
    label: str
    filters: RetrievalFilters  # the shared filters with this cohort's entity set


@dataclass(frozen=True)
class QueryPlan:
    intent: Intent
    dimension: Dimension
    filters: RetrievalFilters  # shared by every cohort; the whole search when there are none
    cohorts: tuple[Cohort, ...]  # empty unless the intent is a comparison
    stated: FilterValues
    inferred: FilterValues
    assumptions: tuple[str, ...]  # Python-written: inferred filters, reinterpreted cohorts
    notes: tuple[str, ...]  # Python-written: field-over-query overrides

    @property
    def analysis(self) -> str:
        return analysis_key(self.intent, self.dimension)


@dataclass(frozen=True)
class Clarification:
    missing: tuple[FilterKey, ...]  # absent anchors; empty when the problem is something else
    stated: FilterValues
    notes: tuple[str, ...]


def analysis_key(intent: Intent, dimension: Dimension) -> str:
    return f"{intent}.{dimension}"


def plan_schema(registry: Registry = REGISTRY) -> dict[str, Any]:
    """The strict schema for `LLMPlan`, with `analysis` narrowed to the registered keys, so the
    LLM cannot choose an analysis that does not exist."""
    schema = strict_json_schema(LLMPlan)
    schema["properties"]["analysis"] = {
        "type": "string",
        "enum": [analysis_key(i, d) for i, d in registry.registered()],
    }
    return schema


def instructions(today: date, registry: Registry = REGISTRY) -> str:
    keys = "\n".join(
        f"- {analysis_key(i, d)}: {INTENT_GUIDE[i]}, {DIMENSION_GUIDE[d]}"
        for i, d in registry.registered()
    )
    return _INSTRUCTIONS.format(today=today.isoformat(), keys=keys)


_INSTRUCTIONS = """\
You plan charts of ClinicalTrials.gov data. Read the user's question and answer with JSON only.
You never produce data, counts or trial IDs: Python fetches and counts them.
You only choose what to chart.

Choose exactly one `analysis` key:
{keys}

`filters`: copy values only from the question text, spelled as the user wrote them. Never correct,
expand or translate a name, and never add a value the question does not imply. Leave a filter null
when the question does not mention it. Always copy values written in the question, even when a
structured field listed with it sets the same filter (Python resolves conflicts); never copy a value
that appears only in the structured fields.
- drug_name, condition, sponsor, country: the names as written.
- trial_phase: one phase when the question names exactly one (Phase 3 -> PHASE3).
- overall_status: one status when the question names exactly one (recruiting -> RECRUITING).
- start_year, end_year: trial start years. "Since 2015" or "the last five years" sets only
  start_year (resolve relative periods against today's date, {today}). Set end_year only when the
  question names an upper bound ("until 2020", "before 2020", "between 2015 and 2020").

`cohorts`: only for a comparison.* key, else null. One cohort per compared drug, condition or
sponsor, all of the same kind: `label` is the name as written, `entity` its kind, `value` the
name to search. List every compared item, even if there are more than 4. Do not also put the
compared entity in `filters`.

`unsupported_reason`: null unless no key fits the question (e.g. it asks about investigators or
outcomes); then one sentence saying what cannot be charted.

Any question about enrollment, participants or sample size uses a numeric.* key, even when it says
"distribution": enrollment sizes -> numeric.enrollment; enrollment over time ->
numeric.enrollment_by_start_date. "How many trials per year" is time_trend.start_year.
"""


def user_message(request: VisualizeRequest) -> str:
    fields = request.model_dump(mode="json", exclude={"query"}, exclude_none=True)
    supplied = ", ".join(f"{k}={v!r}" for k, v in fields.items()) or "none"
    return f"Question: {request.query}\nStructured fields (already applied): {supplied}"


def plan_request(
    request: VisualizeRequest,
    llm: LLMClient,
    today: date | None = None,
    registry: Registry = REGISTRY,
) -> QueryPlan | Clarification:
    """Plan a request: the LLM call plus the rules, retried once with the error (§7.2).
    `LLMUpstreamError` propagates untouched: an unreachable LLM is a 502, not a bad plan."""
    system = instructions(today or date.today(), registry)
    message = user_message(request)
    try:
        return _attempt(request, llm, system, message, registry)
    except LLMOutputError as first:
        retry = f"{message}\n\nYour previous answer was rejected: {first}\nAnswer again."
        try:
            return _attempt(request, llm, system, retry, registry)
        except LLMOutputError as second:
            raise PlanError(f"plan invalid after one retry: {second}") from second


def _attempt(
    request: VisualizeRequest, llm: LLMClient, system: str, message: str, registry: Registry
) -> QueryPlan | Clarification:
    llm_plan = llm.complete(
        instructions=system,
        user_input=message,
        name=PLAN_SCHEMA_NAME,
        output_type=LLMPlan,
        schema=plan_schema(registry),
    )
    return build_plan(request, llm_plan, registry)


def build_plan(
    request: VisualizeRequest, llm_plan: LLMPlan, registry: Registry = REGISTRY
) -> QueryPlan | Clarification:
    """The deterministic half of planning: no LLM, so every rule is unit-tested."""
    intent, dimension = _parse_analysis(llm_plan.analysis, registry)
    filters, notes = _merge(request, llm_plan.filters)
    stated, inferred = _classify(request, filters)
    cohorts, cohort_problem = _cohorts(intent, llm_plan.cohorts, filters)
    # Named cohorts are anchors even when there are too many to compare: the user named entities,
    # so the clarification is about the count, not a missing anchor.
    has_anchor = bool(llm_plan.cohorts) or any(getattr(filters, key) for key in ANCHORS)
    missing = () if has_anchor else ANCHORS
    problems = [p for p in (llm_plan.unsupported_reason, cohort_problem) if p]
    if missing or problems:
        anchor_note = () if has_anchor else (ANCHOR_NOTE,)
        return Clarification(missing, {**stated, **inferred}, (*anchor_note, *problems, *notes))
    assumptions = (*_inferred_assumptions(inferred), *_cohort_assumptions(llm_plan.cohorts or []))
    return QueryPlan(intent, dimension, filters, cohorts, stated, inferred, assumptions, notes)


def _parse_analysis(key: str, registry: Registry) -> tuple[Intent, Dimension]:
    intent, _, dimension = key.partition(".")
    try:
        pair = (Intent(intent), Dimension(dimension))
    except ValueError:
        pair = None
    if pair is None or pair not in registry.registered():
        raise LLMOutputError(f"analysis: {key!r} is not one of the listed analysis keys")
    return pair


def _merge(
    request: VisualizeRequest, llm_filters: RetrievalFilters
) -> tuple[RetrievalFilters, tuple[str, ...]]:
    """Request fields win over the query's values (§7.3); each override gets a note."""
    merged = llm_filters.model_dump(exclude_none=True)
    notes: list[str] = []
    for key, field_value in request.model_dump(exclude={"query"}, exclude_none=True).items():
        query_value = merged.get(key)
        if query_value is not None and str(query_value).casefold() != str(field_value).casefold():
            notes.append(
                f"The {key} field ({field_value}) overrides {query_value} from the question."
            )
        merged[key] = field_value
    try:
        return RetrievalFilters.model_validate(merged), tuple(notes)
    except ValidationError as exc:
        raise LLMOutputError(f"filters: {exc.errors()[0]['msg']} ({merged})") from exc


def is_stated(request: VisualizeRequest, key: str, value: str | int) -> bool:
    """§7.3: a value is stated iff a request field supplies it or it appears verbatim in the
    query (case-insensitive); an enum value also counts when its display label appears."""
    if getattr(request, key, None) == value:
        return True
    spellings = {str(value)}
    if key in _ENUM_FILTERS:
        spellings.add(label(_ENUM_FILTERS[key](str(value))))
    query = request.query.casefold()
    return any(spelling.casefold() in query for spelling in spellings)


def _classify(
    request: VisualizeRequest, filters: RetrievalFilters
) -> tuple[FilterValues, FilterValues]:
    stated: FilterValues = {}
    inferred: FilterValues = {}
    for key in FILTER_KEYS:
        value = getattr(filters, key)
        if value is not None:
            (stated if is_stated(request, key, value) else inferred)[key] = value
    return stated, inferred


def _cohorts(
    intent: Intent, raw: list[LLMCohort] | None, shared: RetrievalFilters
) -> tuple[tuple[Cohort, ...], str | None]:
    """2-4 cohorts of one entity kind for a comparison, none otherwise (§7.2). A problem the
    user must fix comes back as text; an LLM inconsistency raises for the retry."""
    if intent is not Intent.COMPARISON:
        if raw:
            raise LLMOutputError("cohorts: only a comparison.* analysis has cohorts; use null")
        return (), None
    raw = raw or []
    if not MIN_COHORTS <= len(raw) <= MAX_COHORTS:
        return (), (
            f"A comparison needs 2 to 4 drugs, conditions or sponsors; the question names "
            f"{len(raw)}. Name 2 to 4 to compare."
        )
    entities = {c.entity for c in raw}
    if len(entities) > 1:
        return (), "Compare items of one kind: all drugs, all conditions or all sponsors."
    entity = entities.pop()
    if getattr(shared, entity) is not None:
        return (), (
            f"The request sets {entity} ({getattr(shared, entity)}) and also compares "
            f"{entity} values; remove one of them."
        )
    return tuple(Cohort(c.label, shared.model_copy(update={entity: c.value})) for c in raw), None


def _inferred_assumptions(inferred: FilterValues) -> list[str]:
    return [
        f"Filtered on {FILTER_NAMES[key]} {_display(key, value)}, inferred from the question's "
        "wording rather than stated in it."
        for key, value in inferred.items()
    ]


def _cohort_assumptions(cohorts: list[LLMCohort]) -> list[str]:
    return [
        f'Read "{c.label}" as {FILTER_NAMES[c.entity]} "{c.value}".'
        for c in cohorts
        if c.label.casefold() != c.value.casefold()
    ]


def _display(key: str, value: str | int) -> str:
    return label(_ENUM_FILTERS[key](str(value))) if key in _ENUM_FILTERS else str(value)
