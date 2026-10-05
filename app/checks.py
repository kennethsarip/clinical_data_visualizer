"""Every deterministic spec check (CLAUDE.md §7.6).

Each check reads only the assembled response, the aggregator's declared row shape and the raw
cached records, never LLM output, so a check cannot be talked out of a failure. A failure
triggers one repair from the same rows, then `degraded` (§7.7); each message names what broke so
`meta.errors` is actionable.

The §7.6 WARN items (capped sample, counting-rule exclusions, network pruning) keep the response
`ok` because `meta` discloses them. The `disclosures` check makes sure it does, consistently.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.aggregators.common import (
    F_ENROLLMENT,
    F_ENROLLMENT_TYPE,
    F_INTERVENTION_TYPE,
    F_PHASES,
    F_SPONSOR_CLASS,
    F_START_DATE,
    F_STATUS,
)
from app.aggregators.registry import RowShape
from app.ctgov import build_params
from app.schemas import (
    RESPONSE_ADAPTER,
    ChartVisualization,
    CheckError,
    Citation,
    NetworkVisualization,
    OkResponse,
    Provenance,
    RetrievalFilters,
)
from app.viz import VIZ_TYPE, stray_numbers

# Dimensions where every trial lands in exactly one row, so rows must sum to the trials charted
# (§8.5). Multi-valued ones (country, drug, ...) may sum higher, and top-N drops categories.
SINGLE_VALUED = frozenset({"phase", "overall_status", "sponsor_class", "start_year"})

# Messages kept per check; a broken aggregator would otherwise repeat one message per row.
MAX_MESSAGES = 5


# Fields holding codes, numbers or dates: a substring would let "PHASE1" cite "EARLY_PHASE1" or
# "120" cite 1200, so their excerpts must equal a value. Free-text fields keep substring matching.
EXACT_FIELDS = frozenset(
    {
        F_PHASES,
        F_STATUS,
        F_START_DATE,
        F_INTERVENTION_TYPE,
        F_SPONSOR_CLASS,
        F_ENROLLMENT,
        F_ENROLLMENT_TYPE,
    }
)


@dataclass(frozen=True)
class CheckContext:
    shape: RowShape  # declared by the aggregator that produced the rows
    records: Mapping[str, dict[str, Any]]  # nct_id -> raw cached record, the retrieved set
    # The API params each cohort was fetched with. The pipeline always passes them; None (unit
    # tests of other checks) skips only the "filters equal the params sent" half of conformance.
    sent: Sequence[Mapping[str, str]] | None = None


Check = Callable[[OkResponse, CheckContext], list[str]]


def run_checks(response: OkResponse, context: CheckContext) -> list[CheckError]:
    """Every BLOCK check; an empty list means the response may be returned as `ok`."""
    errors: list[CheckError] = []
    for name, check in CHECKS:
        messages = check(response, context)
        errors += [CheckError(check=name, message=m) for m in messages[:MAX_MESSAGES]]
        if len(messages) > MAX_MESSAGES:
            more = len(messages) - MAX_MESSAGES
            errors.append(CheckError(check=name, message=f"... and {more} more"))
    return errors


# --- helpers ---


def _tables(response: OkResponse) -> list[tuple[str, dict[str, Any], list[dict[str, Any]]]]:
    """(name, encoding channels, rows as dicts) for each row table in the spec."""
    spec = response.visualization
    if isinstance(spec, NetworkVisualization):
        return [
            ("nodes", _channels(spec.encoding.nodes), [n.model_dump() for n in spec.data.nodes]),
            ("edges", _channels(spec.encoding.edges), [e.model_dump() for e in spec.data.edges]),
        ]
    return [("rows", _channels(spec.encoding), [r.model_dump() for r in spec.data])]


def _channels(encoding: Mapping[str, Any]) -> dict[str, str]:
    return {channel: c.field for channel, c in encoding.items()}


def _provenance(response: OkResponse) -> list[Provenance]:
    spec = response.visualization
    if isinstance(spec, NetworkVisualization):
        return [*spec.data.nodes, *spec.data.edges]
    return list(spec.data)


def excerpt_matches(record: Mapping[str, Any], citation: Citation) -> bool:
    """A citation holds against its raw record: a non-null excerpt is a verbatim substring of a
    value at its `field` (equal to it, for code, number and date fields); a null excerpt means
    that field has no value."""
    values = _values_at(record.get("protocolSection", {}), citation.field.split("."))
    if citation.excerpt is None:
        return not values
    if citation.field in EXACT_FIELDS:
        return citation.excerpt in values
    return any(citation.excerpt in value for value in values)


def _values_at(node: Any, path: list[str]) -> list[str]:
    """Every scalar at `path`, descending through lists (e.g. locations[].country)."""
    if isinstance(node, list):
        return [value for item in node for value in _values_at(item, path)]
    if not path:
        if isinstance(node, str | int) and not isinstance(node, bool):
            return [str(node)]
        return []
    if isinstance(node, dict) and path[0] in node:
        return _values_at(node[path[0]], path[1:])
    return []


# --- the checks ---


def _schema(response: OkResponse, context: CheckContext) -> list[str]:
    try:
        dumped = RESPONSE_ADAPTER.dump_python(response, mode="json", warnings=False)
        again = RESPONSE_ADAPTER.validate_python(dumped)
    except ValidationError as exc:
        first = exc.errors()[0]
        return [f"response does not validate at {first['loc']}: {first['msg']}"]
    return [] if again == response else ["response changes when round-tripped"]


def _encoding(response: OkResponse, context: CheckContext) -> list[str]:
    messages = []
    for table, channels, rows in _tables(response):
        for channel, field in channels.items():
            missing = sum(field not in row for row in rows)
            if missing:
                messages.append(
                    f"field '{field}' (channel {channel}) is missing from {missing} of "
                    f"{len(rows)} {table}"
                )
    return messages


def _shape(response: OkResponse, context: CheckContext) -> list[str]:
    spec = response.visualization
    expected = VIZ_TYPE[context.shape]
    if spec.type != expected:
        return [f"type {spec.type} does not fit row shape {context.shape} (expected {expected})"]
    if isinstance(spec, NetworkVisualization):
        if not spec.data.nodes or not spec.data.edges:
            return ["a network needs at least one node and one edge"]
        return []
    if not any(row.trial_count for row in spec.data):
        # §7.6: never return an empty chart; zero-filled rows alone are still empty.
        return ["the chart has no trials in any row"]
    return _chart_shape(spec)


def _chart_shape(spec: ChartVisualization) -> list[str]:
    if spec.type == "grouped_bar_chart" and not {"x", "series"} <= spec.encoding.keys():
        return ["a grouped bar chart needs x and series channels"]
    if spec.type == "time_series" and "x" in spec.encoding:
        field = spec.encoding["x"].field
        xs: list[Any] = [row.model_dump().get(field) for row in spec.data]
        if any(not (a < b) for a, b in zip(xs, xs[1:], strict=False)):
            return [f"time series x ({field}) is not strictly ascending"]
    return []


def _citation_ids(response: OkResponse, context: CheckContext) -> list[str]:
    messages = []
    row_ids: set[str] = set()
    for item in _provenance(response):
        row_ids.update(item.nct_ids)
        stray = sorted({c.nct_id for c in item.citations} - set(item.nct_ids))
        if stray:
            messages.append(f"citations {stray} are not among their row's nct_ids")
    unretrieved = sorted(row_ids - context.records.keys())
    if unretrieved:
        messages.append(f"{unretrieved} are not in the retrieved records")
    lookup = set(response.trials)
    if lookup != row_ids:
        missing, extra = sorted(row_ids - lookup), sorted(lookup - row_ids)
        messages.append(f"trials lookup is missing {missing} and has extra {extra}")
    return messages


def _excerpts(response: OkResponse, context: CheckContext) -> list[str]:
    messages = []
    for item in _provenance(response):
        for c in item.citations:
            record = context.records.get(c.nct_id)
            if record is None:
                continue  # reported by the citation ids check
            if excerpt_matches(record, c):
                continue
            if c.excerpt is None:
                messages.append(f"{c.nct_id}: {c.field} is present, but cited as absent")
            else:
                messages.append(f"{c.nct_id}: {c.excerpt!r} is not in {c.field}")
    return messages


def _reconciliation(response: OkResponse, context: CheckContext) -> list[str]:
    messages = []
    for item in _provenance(response):
        if item.trial_count != len(item.nct_ids):
            messages.append(f"trial_count {item.trial_count} != {len(item.nct_ids)} nct_ids")
        if len(set(item.nct_ids)) != len(item.nct_ids):
            messages.append(f"duplicate nct_ids in a row: {item.nct_ids}")
    meta = response.meta
    spec = response.visualization
    if meta.grouping.dimension in SINGLE_VALUED and isinstance(spec, ChartVisualization):
        messages += _single_valued_sums(response, spec)
    return messages


def _single_valued_sums(response: OkResponse, spec: ChartVisualization) -> list[str]:
    """§8.5: per cohort, rows sum to the trials fetched minus every disclosed exclusion."""
    meta = response.meta
    series = meta.grouping.series
    messages = []
    for sample in meta.sample:
        rows: Iterable[Any] = spec.data
        excluded = meta.excluded
        if series is not None and sample.cohort is not None:
            rows = [r for r in spec.data if r.model_dump().get(series) == sample.cohort]
            # In a comparison each exclusion names its cohort: "<rule> (<cohort>)".
            excluded = [e for e in meta.excluded if e.rule.endswith(f" ({sample.cohort})")]
        charted = sum(r.trial_count for r in rows)
        expected = sample.fetched - sum(e.count for e in excluded)
        if charted != expected:
            name = f" for {sample.cohort}" if sample.cohort else ""
            messages.append(
                f"rows sum to {charted}{name}, but {sample.fetched} fetched minus "
                f"{sample.fetched - expected} excluded is {expected}"
            )
    return messages


def _assumptions(response: OkResponse, context: CheckContext) -> list[str]:
    meta = response.meta
    if meta.filters.inferred and not meta.assumptions:
        return [f"inferred filters {sorted(meta.filters.inferred)} have no stated assumption"]
    return []


def _title(response: OkResponse, context: CheckContext) -> list[str]:
    """The LLM writes the title; any number in it must come from the filters (§7.2)."""
    meta = response.meta
    sources: list[object] = [*meta.filters.stated.values(), *meta.filters.inferred.values()]
    for cohort in meta.interpretation.cohorts or ():
        sources += [cohort.label, *cohort.filters.values()]
    stray = stray_numbers(response.visualization.title, sources)
    if stray:
        return [f"title contains numbers not in the filters: {stray}"]
    return []


def _disclosures(response: OkResponse, context: CheckContext) -> list[str]:
    meta = response.meta
    messages = []
    for s in meta.sample:
        if s.fetched > s.total or s.capped != (s.fetched < s.total):
            messages.append(
                f"sample {s.cohort}: capped={s.capped} but fetched {s.fetched} of {s.total}"
            )
    is_network = isinstance(response.visualization, NetworkVisualization)
    if is_network != (meta.pruning is not None):
        messages.append("pruning must be disclosed for a network and only for a network")
    spec = response.visualization
    if meta.top_n is not None and isinstance(spec, ChartVisualization) and "x" in spec.encoding:
        field = spec.encoding["x"].field
        shown = len({r.model_dump().get(field) for r in spec.data})
        if shown > meta.top_n.limit or shown > meta.top_n.categories_total:
            messages.append(f"top_n {meta.top_n} does not bound the {shown} categories shown")
    return messages


# Record paths of the exact filters, read raw so a normalize bug cannot hide an off-filter trial.
F_COUNTRY = "contactsLocationsModule.locations.country"
# Params every search sends whatever its filters; they say nothing about what was filtered.
HOUSEKEEPING_PARAMS = frozenset({"fields", "pageSize", "countTotal", "pageToken"})


def _conformance(response: OkResponse, context: CheckContext) -> list[str]:
    """Phase 6 step 4: every charted trial meets each exact filter in `meta` (its raw record, with
    the API's meaning, §8.4), and the filters `meta` shows are exactly the params that were sent."""
    filters = response.meta.filters
    shared = {**filters.stated, **filters.inferred}
    messages = []
    charted = sorted({n for item in _provenance(response) for n in item.nct_ids}, reverse=True)
    for nct_id in charted:
        record = context.records.get(nct_id)
        if record is None:
            continue  # the citation ids check reports a trial that was never retrieved
        section = record.get("protocolSection", {})
        for key, value in shared.items():
            if not _meets_raw(section, key, value):
                messages.append(f"{nct_id} is outside the {key} filter ({value})")
    if context.sent is not None:
        messages += _sent_mismatches(response, context.sent)
    return messages


def _meets_raw(section: Mapping[str, Any], key: str, value: str | int) -> bool:
    if key == "trial_phase":
        return str(value) in _values_at(section, F_PHASES.split("."))
    if key == "overall_status":
        return str(value) in _values_at(section, F_STATUS.split("."))
    if key == "country":
        return str(value) in _values_at(section, F_COUNTRY.split("."))
    if key in ("start_year", "end_year"):
        dates = _values_at(section, F_START_DATE.split("."))
        if not dates:
            return False
        year = int(dates[0][:4])
        return year >= int(value) if key == "start_year" else year <= int(value)
    return True  # entity filters are searches (§7.3), not exact


def _sent_mismatches(response: OkResponse, sent: Sequence[Mapping[str, str]]) -> list[str]:
    filters = response.meta.filters
    cohorts = response.meta.interpretation.cohorts
    shown = [c.filters for c in cohorts] if cohorts else [{**filters.stated, **filters.inferred}]
    if len(shown) != len(sent):
        return [f"meta describes {len(shown)} searches but {len(sent)} were sent"]
    messages = []
    for values, params in zip(shown, sent, strict=True):
        expected = _param_terms(build_params(RetrievalFilters.model_validate(values), 1))
        actual = _param_terms(params)
        messages += [
            f"meta shows {k}={v!r}, which was not sent" for k, v in sorted(expected - actual)
        ]
        messages += [
            f"sent {k}={v!r}, which meta does not show" for k, v in sorted(actual - expected)
        ]
    return messages


def _param_terms(params: Mapping[str, str]) -> set[tuple[str, str]]:
    """Params as comparable terms: `filter.advanced` is split into its AND-ed terms."""
    terms = set()
    for key, value in params.items():
        if key in HOUSEKEEPING_PARAMS:
            continue
        if key == "filter.advanced":
            terms |= {(key, term) for term in value.split(" AND ")}
        else:
            terms.add((key, value))
    return terms


CHECKS: tuple[tuple[str, Check], ...] = (
    ("schema", _schema),
    ("encoding", _encoding),
    ("shape", _shape),
    ("citation ids", _citation_ids),
    ("excerpts", _excerpts),
    ("reconciliation", _reconciliation),
    ("assumptions", _assumptions),
    ("title", _title),
    ("disclosures", _disclosures),
    ("conformance", _conformance),
)


# What each check guarantees, in plain language, for the frontend's "Checks passed" list (published
# in the OpenAPI schema as `x-checks`). Wording follows CLAUDE.md §7.6; keys match CHECKS.
CHECK_RULES: Mapping[str, str] = {
    "schema": "The response matches the documented schema.",
    "encoding": "Every field the chart encodes exists in every row.",
    "shape": "The chart type fits the shape of the data.",
    "citation ids": "Every cited trial is in its datum and in the retrieved records.",
    "excerpts": "Every excerpt is the exact text at its field in the trial's record.",
    "reconciliation": "Each count equals its distinct trials; totals reconcile with the records.",
    "assumptions": "Every inferred filter is disclosed as an assumption.",
    "title": "The title contains no number that is not in the filters.",
    "disclosures": "Sample caps, pruning and top-N limits are disclosed consistently.",
    "conformance": "Every charted trial meets each exact filter; the filters shown are those sent.",
}
