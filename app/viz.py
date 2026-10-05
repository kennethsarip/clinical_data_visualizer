"""Row shape -> viz type; spec + meta assembly; LLM title + notes (CLAUDE.md §7.2, §7.4).

Everything here is deterministic except the title and notes, which the caller passes in (Phase 3:
the LLM; until then, `default_title`). The viz type, encoding, sort and every `meta` disclosure
follow from the aggregator's declaration and result, so the same rows always produce the same
spec, and a repair (§7.7) can rebuild it without re-querying anything.
"""

from collections.abc import Mapping, Sequence

from app.aggregators.registry import (
    Aggregation,
    Aggregator,
    AggRow,
    CohortTrials,
    Dimension,
    GraphAggregation,
    Intent,
    RowShape,
)
from app.citations import CITATION_CAP, provenance, trial_summaries
from app.normalize import UNREADABLE_RULE
from app.schemas import (
    Channel,
    ChartVisualization,
    Cohort,
    Edge,
    Exclusion,
    Filters,
    Grouping,
    Interpretation,
    NetworkData,
    NetworkEncoding,
    NetworkVisualization,
    Node,
    OkMeta,
    OkResponse,
    RetrievalFilters,
    Row,
    SampleEntry,
    Sort,
)
from app.vocab import PHASE_NOT_SPECIFIED

# Python picks the viz type from the aggregator's declared row shape (decided 2026-10-04): each
# shape has exactly one fitting type, so an LLM choice would add a failure mode and no choice.
VIZ_TYPE: Mapping[RowShape, str] = {
    RowShape.CATEGORICAL: "bar_chart",
    RowShape.TWO_CATEGORICAL: "grouped_bar_chart",
    RowShape.TEMPORAL: "time_series",
    RowShape.PER_TRIAL_NUMERIC: "scatter_plot",
    RowShape.BINNED_NUMERIC: "histogram",
    RowShape.GRAPH: "network_graph",
}

SOURCE = "clinicaltrials.gov"
UNITS = {"trial_count": "trials"}
ENROLLMENT_UNITS = UNITS | {"enrollment": "participants"}

# Plain-language names for titles; never numbers (the title check allows only filter numbers).
DIMENSION_NAMES: Mapping[Dimension, str] = {
    Dimension.PHASE: "Phase",
    Dimension.OVERALL_STATUS: "Status",
    Dimension.INTERVENTION_TYPE: "Intervention Type",
    Dimension.SPONSOR_CLASS: "Sponsor Class",
    Dimension.DRUG: "Drug",
    Dimension.SPONSOR: "Sponsor",
    Dimension.CONDITION: "Condition",
    Dimension.COUNTRY: "Country",
    Dimension.START_YEAR: "Year",
    Dimension.ENROLLMENT_BY_START_DATE: "Enrollment by Start Date",
    Dimension.ENROLLMENT: "Enrollment",
    Dimension.SPONSOR_DRUG: "Sponsor-Drug Network",
    Dimension.DRUG_DRUG: "Drug Co-occurrence Network",
    Dimension.CONDITION_DRUG: "Condition-Drug Network",
}

# Counting rules disclosed with every chart on that dimension (CLAUDE.md §6).
DRUG_RULE = (
    "Drugs are interventions registered as Drug, Biological or Combination Product; placebo, "
    "sham, vehicle and saline are left out. Names are matched ignoring case, doses, bracketed "
    "aliases and salt forms; brand and generic names are not merged."
)
DIMENSION_ASSUMPTIONS: Mapping[Dimension, tuple[str, ...]] = {
    Dimension.PHASE: (
        "A trial registered under two phases is its own category (e.g. Phase 1/Phase 2), so "
        "every trial is counted once.",
    ),
    Dimension.INTERVENTION_TYPE: ("A trial counts once for each intervention type it uses.",),
    Dimension.COUNTRY: ("A trial with sites in several countries counts once in each country.",),
    Dimension.DRUG: (DRUG_RULE,),
    Dimension.SPONSOR: ("Sponsors are the lead sponsor; names are matched ignoring case.",),
    Dimension.CONDITION: (
        "Conditions are matched ignoring case; a trial counts once per condition.",
    ),
    Dimension.START_YEAR: (
        "Trials are counted by start date (statusModule.startDateStruct.date); years with no "
        "trials are shown as zero.",
    ),
    Dimension.ENROLLMENT_BY_START_DATE: (
        "Enrollment is split by type: Actual counts are final, Estimated counts are targets.",
        "Enrollment of 0 (e.g. a withdrawn trial) cannot sit on a log axis and is drawn at the "
        "axis floor.",
    ),
    Dimension.ENROLLMENT: (
        "Enrollment is split by type: Actual counts are final, Estimated counts are targets.",
    ),
    Dimension.SPONSOR_DRUG: (DRUG_RULE,),
    Dimension.DRUG_DRUG: (DRUG_RULE,),
    Dimension.CONDITION_DRUG: (DRUG_RULE,),
}
NOT_SPECIFIED_ASSUMPTION = (
    '"Not specified" means the record lists no phase; these are mostly observational studies.'
)
NETWORK_ASSUMPTION = "An edge's weight is the number of trials that name both of its ends."
COMPARISON_ASSUMPTION = (
    "Each cohort is a separate search; a trial matching both cohorts counts in both."
)


class AssemblyError(ValueError):
    """The caller's inputs contradict each other: a pipeline bug, never user input."""


def assemble(
    aggregator: Aggregator,
    result: Aggregation | GraphAggregation,
    cohorts: Sequence[CohortTrials],
    *,
    filters: Filters,
    title: str,
    assumptions: Sequence[str] = (),
    notes: Sequence[str] = (),
) -> OkResponse:
    """The full `ok` response for one aggregator's result (SCHEMAS.md §2-§4)."""
    _check_filters(cohorts, filters)
    if isinstance(result, GraphAggregation):
        spec: ChartVisualization | NetworkVisualization = _network_spec(result, title)
        rows: Sequence[AggRow] = (*result.nodes, *result.edges)
    else:
        spec = _chart_spec(aggregator, result, title)
        rows = result.rows
    nct_ids = {n for row in rows for n in row.nct_ids}
    trials = [t for c in cohorts for t in c.batch.trials]
    meta = OkMeta(
        source=SOURCE,
        interpretation=_interpretation(aggregator, cohorts),
        filters=filters,
        assumptions=[*_assumptions(aggregator, result, cohorts), *assumptions],
        units=ENROLLMENT_UNITS if aggregator.intent is Intent.NUMERIC else UNITS,
        sort=_sort(aggregator),
        time_granularity="year" if aggregator.shape is RowShape.TEMPORAL else None,
        grouping=Grouping(dimension=str(aggregator.dimension), series=_series(aggregator)),
        sample=[_sample(c) for c in cohorts],
        citation_cap=CITATION_CAP,
        excluded=_excluded(result, cohorts),
        top_n=None if isinstance(result, GraphAggregation) else result.top_n,
        pruning=result.pruning if isinstance(result, GraphAggregation) else None,
        notes=list(notes),
    )
    return OkResponse(
        status="ok",
        visualization=spec,
        trials=trial_summaries(trials, nct_ids),
        meta=meta,
    )


def _check_filters(cohorts: Sequence[CohortTrials], filters: Filters) -> None:
    """`meta.filters` must disclose exactly the search that ran. A comparison's per-cohort
    filters are disclosed in `meta.interpretation.cohorts` instead."""
    if len(cohorts) != 1:
        return
    applied = _filter_values(cohorts[0].filters)
    disclosed = {**filters.stated, **filters.inferred}
    if applied != disclosed:
        raise AssemblyError(f"filters applied {applied} but disclosed {disclosed}")


def default_title(aggregator: Aggregator, cohorts: Sequence[CohortTrials]) -> str:
    """A plain, number-free title from the plan, used until the LLM writes titles (Phase 3)."""
    name = DIMENSION_NAMES[aggregator.dimension]
    subjects = [_subject(c) for c in cohorts]
    if aggregator.intent is Intent.COMPARISON:
        return f"{name}: {' vs '.join(s for s in subjects if s)}"
    subject = subjects[0] if subjects else None
    if aggregator.intent is Intent.NETWORK:
        return f"{name}: {subject}" if subject else name
    noun = "Trials by" if aggregator.shape is not RowShape.TEMPORAL else "Trials Started per"
    return f"{noun} {name}" + (f": {subject}" if subject else "")


# --- spec ---


def _chart_spec(aggregator: Aggregator, result: Aggregation, title: str) -> ChartVisualization:
    data = [Row(**row.values, **provenance(row).model_dump()) for row in result.rows]
    return ChartVisualization.model_validate(
        {
            "type": VIZ_TYPE[aggregator.shape],
            "title": title,
            "encoding": _chart_encoding(aggregator),
            "data": data,
        }
    )


def _chart_encoding(aggregator: Aggregator) -> dict[str, Channel]:
    column = aggregator.columns[0]
    count = Channel(field="trial_count", type="quantitative")
    match aggregator.shape:
        case RowShape.CATEGORICAL:
            return {"x": Channel(field=column, type="nominal"), "y": count}
        case RowShape.TWO_CATEGORICAL:
            series = aggregator.columns[1]
            return {
                "x": Channel(field=column, type="nominal"),
                "y": count,
                "series": Channel(field=series, type="nominal"),
            }
        case RowShape.TEMPORAL:
            return {"x": Channel(field=column, type="temporal"), "y": count}
        case RowShape.PER_TRIAL_NUMERIC:
            return {
                "x": Channel(field="start_date", type="temporal"),
                "y": Channel(field="enrollment", type="quantitative", scale="log"),
                "series": Channel(field="enrollment_type", type="nominal"),
            }
        case RowShape.BINNED_NUMERIC:
            return {
                "x": Channel(field="bin_label", type="ordinal"),
                "y": count,
                "series": Channel(field="enrollment_type", type="nominal"),
            }
    raise ValueError(f"no chart encoding for shape {aggregator.shape}")


def _network_spec(result: GraphAggregation, title: str) -> NetworkVisualization:
    nominal = {"type": "nominal"}
    encoding = NetworkEncoding.model_validate(
        {
            "nodes": {
                "id": {"field": "id", **nominal},
                "label": {"field": "label", **nominal},
                "group": {"field": "entity_type", **nominal},
                "size": {"field": "trial_count", "type": "quantitative"},
            },
            "edges": {
                "source": {"field": "source", **nominal},
                "target": {"field": "target", **nominal},
                "weight": {"field": "trial_count", "type": "quantitative"},
            },
        }
    )
    nodes = [Node.model_validate({**n.values, **provenance(n).model_dump()}) for n in result.nodes]
    edges = [Edge.model_validate({**e.values, **provenance(e).model_dump()}) for e in result.edges]
    return NetworkVisualization(
        type="network_graph",
        title=title,
        encoding=encoding,
        data=NetworkData(nodes=nodes, edges=edges),
    )


# --- meta ---


def _interpretation(aggregator: Aggregator, cohorts: Sequence[CohortTrials]) -> Interpretation:
    listed = None
    if aggregator.intent is Intent.COMPARISON:
        listed = [
            Cohort.model_validate({"label": c.label or "", "filters": _filter_values(c.filters)})
            for c in cohorts
        ]
    return Interpretation(
        intent=str(aggregator.intent), dimension=str(aggregator.dimension), cohorts=listed
    )


def _filter_values(filters: RetrievalFilters) -> dict[str, object]:
    return {k: v for k, v in filters.model_dump(mode="json").items() if v is not None}


def _sort(aggregator: Aggregator) -> Sort:
    match aggregator.shape:
        case RowShape.CATEGORICAL | RowShape.TWO_CATEGORICAL if (
            aggregator.dimension is Dimension.PHASE
        ):
            return Sort(field="phase", order="canonical")
        case RowShape.CATEGORICAL | RowShape.TWO_CATEGORICAL | RowShape.GRAPH:
            return Sort(field="trial_count", order="desc")
        case RowShape.TEMPORAL:
            return Sort(field=aggregator.columns[0], order="asc")
        case RowShape.PER_TRIAL_NUMERIC:
            return Sort(field="start_date", order="asc")
        case RowShape.BINNED_NUMERIC:
            return Sort(field="bin_start", order="asc")
    raise ValueError(f"no sort for shape {aggregator.shape}")


def _series(aggregator: Aggregator) -> str | None:
    if aggregator.shape is RowShape.TWO_CATEGORICAL:
        return aggregator.columns[1]
    if aggregator.intent is Intent.NUMERIC:
        return "enrollment_type"
    return None


def _sample(cohort: CohortTrials) -> SampleEntry:
    fetched = len(cohort.batch.trials) + len(cohort.batch.unreadable)
    # totalCount is read from the first page; trials registered while later pages are fetched
    # can push `fetched` past it, and a total below what was fetched is never true.
    total = max(cohort.total, fetched)
    return SampleEntry(cohort=cohort.label, fetched=fetched, total=total, capped=fetched < total)


def _excluded(
    result: Aggregation | GraphAggregation, cohorts: Sequence[CohortTrials]
) -> list[Exclusion]:
    counts = dict(result.excluded)
    for c in cohorts:
        if c.batch.unreadable:
            # A comparison names the cohort, as the aggregator does for its own rules.
            rule = UNREADABLE_RULE if len(cohorts) == 1 else f"{UNREADABLE_RULE} ({c.label})"
            counts[rule] = counts.get(rule, 0) + len(c.batch.unreadable)
    return [Exclusion(rule=rule, count=n) for rule, n in counts.items() if n]


def _assumptions(
    aggregator: Aggregator, result: Aggregation | GraphAggregation, cohorts: Sequence[CohortTrials]
) -> list[str]:
    found = list(DIMENSION_ASSUMPTIONS.get(aggregator.dimension, ()))
    if aggregator.intent is Intent.COMPARISON:
        found.append(COMPARISON_ASSUMPTION)
    if isinstance(result, GraphAggregation):
        found.append(NETWORK_ASSUMPTION)
        anchors = [str(n.values["label"]) for n in result.nodes if n.values["is_anchor"]]
        if anchors:
            found.append(
                f"{', '.join(anchors)} appears in every trial because the search was for it, "
                "so it is drawn de-emphasized."
            )
    elif any(r.values.get(aggregator.columns[0]) == PHASE_NOT_SPECIFIED for r in result.rows):
        found.append(NOT_SPECIFIED_ASSUMPTION)
    return found


def _subject(cohort: CohortTrials) -> str | None:
    """What the cohort's search named, for titles: the label, or the named entities."""
    if cohort.label:
        return cohort.label
    f = cohort.filters
    named = [x for x in (f.drug_name, f.condition, f.sponsor) if x]
    return ", ".join(named) or None
