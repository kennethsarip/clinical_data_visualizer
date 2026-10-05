"""Spec and meta assembly (CLAUDE.md §7.4, §14 Phase 2 step 7; SCHEMAS.md §2-§4).

The Phase 2 "Done when": every registered aggregator assembles a response that passes every
check. Expected encodings, sorts and meta values come from SCHEMAS.md, not from output.
"""

from typing import Any

import pytest

from app.aggregators.registry import REGISTRY, Dimension, Intent
from app.checks import CheckContext, run_checks
from app.normalize import normalize_record
from app.schemas import Filters, OkResponse
from app.viz import assemble, default_title
from tests.factories import FIXTURE, T1, T2, T4, cohort, make_trial, raw_record

RECORDS = {t.nct_id: raw_record(t) for t in FIXTURE}
NO_FILTERS = Filters(stated={}, inferred={})


def _cohorts(intent: Intent, **kwargs: Any) -> list[Any]:
    if intent is Intent.COMPARISON:
        return [cohort(FIXTURE[:3], label="A", **kwargs), cohort(FIXTURE[3:], label="B", **kwargs)]
    return [cohort(FIXTURE, **kwargs)]


def _stated(cohorts: list[Any]) -> Filters:
    """Disclose a single cohort's filters as stated; a comparison shares none."""
    if len(cohorts) != 1:
        return NO_FILTERS
    applied = cohorts[0].filters.model_dump(mode="json", exclude_none=True)
    return Filters.model_validate({"stated": applied, "inferred": {}})


def _assemble(intent: Intent, dimension: Dimension, cohorts: list[Any] | None = None) -> OkResponse:
    aggregator = REGISTRY.get(intent, dimension)
    cohorts = cohorts or _cohorts(intent)
    result = aggregator.aggregate(cohorts)
    return assemble(
        aggregator,
        result,
        cohorts,
        filters=_stated(cohorts),
        title=default_title(aggregator, cohorts),
    )


def test_raw_record_factory_round_trips_through_normalize() -> None:
    # The excerpt check below is only meaningful if these records are faithful.
    for trial in FIXTURE:
        assert normalize_record(raw_record(trial)) == trial


# --- the Phase 2 "Done when" ---


@pytest.mark.parametrize(
    ("intent", "dimension"),
    [pytest.param(i, d, id=f"{i}-{d}") for i, d in REGISTRY.registered()],
)
def test_every_aggregator_assembles_a_response_that_passes_every_check(
    intent: Intent, dimension: Dimension
) -> None:
    aggregator = REGISTRY.get(intent, dimension)
    response = _assemble(intent, dimension)
    errors = run_checks(response, CheckContext(shape=aggregator.shape, records=RECORDS))
    assert errors == []


# --- encodings per shape (SCHEMAS.md §3) ---


def _channels(response: OkResponse) -> dict[str, tuple[str, str, str]]:
    encoding = response.visualization.encoding
    assert isinstance(encoding, dict)
    return {k: (c.field, c.type, c.scale) for k, c in encoding.items()}


def test_bar_chart_spec_and_meta() -> None:
    response = _assemble(Intent.DISTRIBUTION, Dimension.PHASE)
    spec = response.visualization
    assert spec.type == "bar_chart"
    assert _channels(response) == {
        "x": ("phase", "nominal", "linear"),
        "y": ("trial_count", "quantitative", "linear"),
    }
    rows = [r.model_dump() for r in spec.data]
    assert [(r["phase"], r["trial_count"]) for r in rows] == [
        ("Phase 1/Phase 2", 1),
        ("Phase 3", 2),
        ("Not Applicable", 1),
        ("Not specified", 1),
    ]
    meta = response.meta
    assert meta.sort.model_dump() == {"field": "phase", "order": "canonical"}
    assert meta.grouping.model_dump() == {"dimension": "phase", "series": None}
    assert meta.time_granularity is None
    assert meta.units == {"trial_count": "trials"}
    assert [s.model_dump() for s in meta.sample] == [
        {"cohort": None, "fetched": 5, "total": 5, "capped": False}
    ]
    assert meta.citation_cap == 25
    assert meta.interpretation.model_dump() == {
        "intent": "distribution",
        "dimension": "phase",
        "cohorts": None,
    }
    assert set(response.trials) == {t.nct_id for t in FIXTURE}
    assert any("Phase 1/Phase 2" in a for a in meta.assumptions)
    assert any("Not specified" in a for a in meta.assumptions)


def test_count_sorted_bar_declares_descending_count() -> None:
    meta = _assemble(Intent.DISTRIBUTION, Dimension.OVERALL_STATUS).meta
    assert meta.sort.model_dump() == {"field": "trial_count", "order": "desc"}


def test_grouped_bar_spec_names_its_cohorts() -> None:
    response = _assemble(Intent.COMPARISON, Dimension.PHASE)
    assert response.visualization.type == "grouped_bar_chart"
    assert _channels(response)["series"] == ("cohort", "nominal", "linear")
    cohorts = response.meta.interpretation.cohorts
    assert cohorts is not None and [c.label for c in cohorts] == ["A", "B"]
    assert response.meta.grouping.model_dump() == {"dimension": "phase", "series": "cohort"}
    assert [s.cohort for s in response.meta.sample] == ["A", "B"]


def test_time_series_spec() -> None:
    response = _assemble(Intent.TIME_TREND, Dimension.START_YEAR)
    assert response.visualization.type == "time_series"
    assert _channels(response)["x"] == ("start_year", "temporal", "linear")
    meta = response.meta
    assert meta.time_granularity == "year"
    assert meta.sort.model_dump() == {"field": "start_year", "order": "asc"}
    assert [e.model_dump() for e in meta.excluded] == [
        {"rule": "missing start date", "count": 1, "nct_ids": ["NCT00000003"]}
    ]


def test_scatter_spec_uses_a_log_enrollment_axis() -> None:
    response = _assemble(Intent.NUMERIC, Dimension.ENROLLMENT_BY_START_DATE)
    assert response.visualization.type == "scatter_plot"
    assert _channels(response) == {
        "x": ("start_date", "temporal", "linear"),
        "y": ("enrollment", "quantitative", "log"),
        "series": ("enrollment_type", "nominal", "linear"),
    }
    assert response.meta.units == {"trial_count": "trials", "enrollment": "participants"}
    # T4 has enrollment 0, which a log axis cannot show (CLAUDE.md §6).
    assert any("log" in a for a in response.meta.assumptions)


def test_histogram_spec_uses_ordinal_bins() -> None:
    response = _assemble(Intent.NUMERIC, Dimension.ENROLLMENT)
    assert response.visualization.type == "histogram"
    assert _channels(response)["x"] == ("bin_label", "ordinal", "linear")
    assert response.meta.sort.model_dump() == {"field": "bin_start", "order": "asc"}


def test_network_spec() -> None:
    from app.schemas import RetrievalFilters

    cohorts = [cohort(FIXTURE, filters=RetrievalFilters(drug_name="Pembrolizumab"))]
    response = _assemble(Intent.NETWORK, Dimension.DRUG_DRUG, cohorts)
    spec = response.visualization
    assert spec.type == "network_graph"
    encoding = spec.encoding.model_dump()
    assert {k: v["field"] for k, v in encoding["nodes"].items()} == {
        "id": "id",
        "label": "label",
        "group": "entity_type",
        "size": "trial_count",
    }
    assert {k: v["field"] for k, v in encoding["edges"].items()} == {
        "source": "source",
        "target": "target",
        "weight": "trial_count",
    }
    assert response.meta.pruning is not None and response.meta.pruning.fallback_used
    assert response.meta.sort.model_dump() == {"field": "trial_count", "order": "desc"}
    # The anchor is named in an assumption, so the de-emphasized hub is explained.
    assert any("Pembrolizumab" in a for a in response.meta.assumptions)


# --- meta disclosures ---


def test_unreadable_records_are_disclosed_and_reconcile() -> None:
    cohorts = [cohort(FIXTURE, unreadable=1)]
    response = _assemble(Intent.DISTRIBUTION, Dimension.PHASE, cohorts)
    assert response.meta.sample[0].fetched == 6
    # The synthetic unreadable record has no usable NCT ID: counted, but no ID to list.
    assert {"rule": "unreadable record", "count": 1, "nct_ids": []} in [
        e.model_dump() for e in response.meta.excluded
    ]
    shape = REGISTRY.get(Intent.DISTRIBUTION, Dimension.PHASE).shape
    assert run_checks(response, CheckContext(shape=shape, records=RECORDS)) == []


def test_comparison_unreadable_exclusion_names_its_cohort() -> None:
    cohorts = [cohort([T1, T2], label="A", unreadable=1), cohort([T4], label="B")]
    response = _assemble(Intent.COMPARISON, Dimension.PHASE, cohorts)
    assert {"rule": "unreadable record (A)", "count": 1, "nct_ids": []} in [
        e.model_dump() for e in response.meta.excluded
    ]
    shape = REGISTRY.get(Intent.COMPARISON, Dimension.PHASE).shape
    retrieved = {t.nct_id: RECORDS[t.nct_id] for t in (T1, T2, T4)}  # what the cohorts fetched
    assert run_checks(response, CheckContext(shape=shape, records=retrieved)) == []


def test_capped_sample_is_disclosed() -> None:
    response = _assemble(Intent.DISTRIBUTION, Dimension.PHASE, [cohort(FIXTURE, total=3769)])
    assert response.meta.sample[0].model_dump() == {
        "cohort": None,
        "fetched": 5,
        "total": 3769,
        "capped": True,
    }


def test_filters_and_notes_pass_through() -> None:
    from app.schemas import RetrievalFilters

    aggregator = REGISTRY.get(Intent.DISTRIBUTION, Dimension.PHASE)
    applied = RetrievalFilters(drug_name="Pembrolizumab", overall_status="RECRUITING")
    cohorts = [cohort(FIXTURE, filters=applied)]
    filters = Filters(
        stated={"drug_name": "Pembrolizumab"}, inferred={"overall_status": "RECRUITING"}
    )
    response = assemble(
        aggregator,
        aggregator.aggregate(cohorts),
        cohorts,
        filters=filters,
        title="t",
        assumptions=["Read 'active' as recruiting."],
        notes=["n"],
    )
    assert response.meta.filters == filters
    assert response.meta.notes == ["n"]
    assert "Read 'active' as recruiting." in response.meta.assumptions


@pytest.mark.parametrize(
    ("intent", "dimension"),
    [pytest.param(i, d, id=f"{i}-{d}") for i, d in REGISTRY.registered()],
)
def test_default_title_has_no_numbers(intent: Intent, dimension: Dimension) -> None:
    aggregator = REGISTRY.get(intent, dimension)
    title = default_title(aggregator, _cohorts(intent))
    assert title and not any(ch.isdigit() for ch in title)


# --- regressions found in the Phase 2 bug review ---


def test_time_trend_range_covers_data_outside_the_stated_years() -> None:
    from app.schemas import RetrievalFilters

    # A stated 2016-2017 range must not drop T1 (2015) or T5 (2018) from the chart.
    cohorts = [cohort(FIXTURE, filters=RetrievalFilters(start_year=2016, end_year=2017))]
    response = _assemble(Intent.TIME_TREND, Dimension.START_YEAR, cohorts)
    years = [r.model_dump()["start_year"] for r in response.visualization.data]  # type: ignore[union-attr]
    assert years == [2015, 2016, 2017, 2018]
    shape = REGISTRY.get(Intent.TIME_TREND, Dimension.START_YEAR).shape
    # The pipeline drops such off-filter trials before aggregating (Phase 6 step 4); charted
    # anyway, they fail only the conformance check.
    errors = run_checks(response, CheckContext(shape=shape, records=RECORDS))
    assert {e.check for e in errors} == {"conformance"}


def test_total_below_fetched_is_raised_to_fetched() -> None:
    # totalCount comes from the first page; trials added between pages can push fetched past it.
    response = _assemble(Intent.DISTRIBUTION, Dimension.PHASE, [cohort(FIXTURE, total=4)])
    assert response.meta.sample[0].model_dump() == {
        "cohort": None,
        "fetched": 5,
        "total": 5,
        "capped": False,
    }


def test_time_trend_title_reads_naturally() -> None:
    from app.schemas import RetrievalFilters

    aggregator = REGISTRY.get(Intent.TIME_TREND, Dimension.START_YEAR)
    cohorts = [cohort(FIXTURE, filters=RetrievalFilters(condition="Melanoma"))]
    assert default_title(aggregator, cohorts) == "Trials Started per Year: Melanoma"


def test_disclosed_filters_must_match_the_applied_filters() -> None:
    # meta.filters must describe the search that ran; a mismatch is a pipeline bug.
    from app.schemas import RetrievalFilters
    from app.viz import AssemblyError

    aggregator = REGISTRY.get(Intent.DISTRIBUTION, Dimension.PHASE)
    cohorts = [cohort(FIXTURE, filters=RetrievalFilters(condition="COVID-19"))]
    with pytest.raises(AssemblyError, match="COVID-19"):
        assemble(aggregator, aggregator.aggregate(cohorts), cohorts, filters=NO_FILTERS, title="t")


BARE = [make_trial(f"NCT0000010{i}") for i in range(3)]  # no phase, date, sites, drugs, enrollment


@pytest.mark.parametrize("trials", [[], BARE], ids=["no-trials", "no-optional-fields"])
@pytest.mark.parametrize(
    ("intent", "dimension"),
    [pytest.param(i, d, id=f"{i}-{d}") for i, d in REGISTRY.registered()],
)
def test_aggregators_survive_empty_input_and_checks_block_an_empty_chart(
    trials: list[Any], intent: Intent, dimension: Dimension
) -> None:
    # Phase 3 turns these into no_results; they must not crash first, and if one slipped through
    # to the checks, an empty chart must be blocked rather than returned as ok (§7.6).
    aggregator = REGISTRY.get(intent, dimension)
    cohorts = (
        [cohort(trials, label="A"), cohort(trials, label="B")]
        if intent is Intent.COMPARISON
        else [cohort(trials)]
    )
    response = assemble(
        aggregator,
        aggregator.aggregate(cohorts),
        cohorts,
        filters=_stated(cohorts),
        title=default_title(aggregator, cohorts),
    )
    records = {t.nct_id: raw_record(t) for t in trials}
    errors = run_checks(response, CheckContext(shape=aggregator.shape, records=records))
    if response.trials:
        assert errors == [], [(e.check, e.message) for e in errors]
    else:
        assert "shape" in {e.check for e in errors}
