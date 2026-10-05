"""Distribution, geographic, top-N, time trend and comparison aggregators (CLAUDE.md §7.4).

Expected rows are derived by hand from `tests/factories.py` FIXTURE and the §6 counting rules.
"""

from typing import Any

import pytest

from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    AggregationInputError,
    Dimension,
    Evidence,
    GraphAggregation,
    Intent,
)
from app.schemas import RetrievalFilters, TopN
from tests.factories import FIXTURE, T1, T2, T4, cohort, make_trial

Summary = list[tuple[Any, ...]]


def _run(intent: Intent, dimension: Dimension, *cohorts: Any) -> Aggregation:
    result = REGISTRY.get(intent, dimension).aggregate(list(cohorts))
    assert isinstance(result, Aggregation)
    return result


def _rows(result: Aggregation, *columns: str) -> Summary:
    """(column values..., trial_count, sorted nct_ids) per row, in row order."""
    return [
        (*(row.values[c] for c in columns), len(row.nct_ids), sorted(row.nct_ids))
        for row in result.rows
    ]


def _check_provenance(result: Aggregation) -> None:
    # Every row's evidence covers exactly its trials (registry.AggRow contract).
    for row in result.rows:
        assert set(row.evidence) == row.nct_ids


# --- distribution ---


def test_phase_rows_in_canonical_order() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.PHASE, cohort(FIXTURE))
    assert _rows(result, "phase") == [
        ("Phase 1/Phase 2", 1, ["NCT00000002"]),
        ("Phase 3", 2, ["NCT00000001", "NCT00000004"]),
        ("Not Applicable", 1, ["NCT00000005"]),
        ("Not specified", 1, ["NCT00000003"]),
    ]
    assert result.excluded == {}
    assert result.top_n is None
    _check_provenance(result)


def test_phase_evidence_cites_each_phase_and_absence() -> None:
    rows = {
        r.values["phase"]: r
        for r in _run(Intent.DISTRIBUTION, Dimension.PHASE, cohort(FIXTURE)).rows
    }
    assert rows["Phase 1/Phase 2"].evidence["NCT00000002"] == (
        Evidence("designModule.phases", "PHASE1"),
        Evidence("designModule.phases", "PHASE2"),
    )
    assert rows["Not Applicable"].evidence["NCT00000005"] == (
        Evidence("designModule.phases", "NA"),
    )
    assert rows["Not specified"].evidence["NCT00000003"] == (Evidence("designModule.phases", None),)


def test_status_rows_by_count_then_label() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.OVERALL_STATUS, cohort(FIXTURE))
    assert _rows(result, "overall_status") == [
        ("Completed", 2, ["NCT00000002", "NCT00000003"]),
        ("Recruiting", 2, ["NCT00000001", "NCT00000004"]),
        ("Withdrawn", 1, ["NCT00000005"]),
    ]
    assert result.rows[0].evidence["NCT00000003"] == (
        Evidence("statusModule.overallStatus", "COMPLETED"),
    )


def test_intervention_types_count_each_trial_once_per_type() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.INTERVENTION_TYPE, cohort(FIXTURE))
    # T1 has two DRUG items (one a placebo): one Drug membership. T5 has none: excluded.
    assert _rows(result, "intervention_type") == [
        ("Drug", 3, ["NCT00000001", "NCT00000002", "NCT00000004"]),
        ("Biological", 1, ["NCT00000002"]),
        ("Other", 1, ["NCT00000003"]),
    ]
    assert result.excluded == {"no interventions": 1}
    _check_provenance(result)


def test_unnamed_intervention_is_left_out_and_counted() -> None:
    trial = T1.model_copy(update={"nct_id": "NCT00000009"})
    unnamed = trial.model_copy(
        update={"interventions": (trial.interventions[0].model_copy(update={"name": None}),)}
    )
    result = _run(Intent.DISTRIBUTION, Dimension.INTERVENTION_TYPE, cohort([unnamed]))
    assert result.rows == ()
    assert result.excluded == {"unnamed intervention": 1}


def test_sponsor_class_rows() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.SPONSOR_CLASS, cohort(FIXTURE))
    assert _rows(result, "sponsor_class") == [
        ("Industry", 4, ["NCT00000001", "NCT00000002", "NCT00000004", "NCT00000005"]),
        ("NIH", 1, ["NCT00000003"]),
    ]


def test_top_drugs_apply_the_drug_rule_and_merge_registrations() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.DRUG, cohort(FIXTURE))
    assert _rows(result, "drug") == [
        ("Ipilimumab", 2, ["NCT00000002", "NCT00000004"]),
        ("Pembrolizumab", 2, ["NCT00000001", "NCT00000002"]),
        ("Nivolumab", 1, ["NCT00000004"]),
    ]
    assert result.excluded == {
        "placebo": 1,
        "non-drug intervention": 1,
        "no drug intervention": 1,
        "no interventions": 1,
    }
    assert result.top_n == TopN(limit=20, categories_total=3)
    pembro = result.rows[1]
    assert pembro.evidence["NCT00000002"] == (
        Evidence("armsInterventionsModule.interventions.name", "Pembrolizumab (MK-3475)"),
    )


def test_top_sponsors_merge_case_variants() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.SPONSOR, cohort(FIXTURE))
    assert _rows(result, "sponsor") == [
        ("Bristol-Myers Squibb", 2, ["NCT00000004", "NCT00000005"]),
        ("Merck Sharp & Dohme LLC", 2, ["NCT00000001", "NCT00000002"]),
        ("National Cancer Institute (NCI)", 1, ["NCT00000003"]),
    ]


def test_top_conditions() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.CONDITION, cohort(FIXTURE))
    assert _rows(result, "condition") == [
        ("Melanoma", 4, ["NCT00000001", "NCT00000002", "NCT00000004", "NCT00000005"]),
        ("Lung Cancer", 2, ["NCT00000002", "NCT00000003"]),
    ]
    melanoma = result.rows[0]
    assert melanoma.evidence["NCT00000002"] == (
        Evidence("conditionsModule.conditions", "melanoma"),
    )


def test_top_n_keeps_the_largest_categories_and_discloses_the_total() -> None:
    from tests.factories import make_trial

    trials = [make_trial(f"NCT{i:08d}", sponsor_name=f"Sponsor {i:02d}") for i in range(1, 26)]
    result = _run(Intent.DISTRIBUTION, Dimension.SPONSOR, cohort(trials))
    assert result.top_n == TopN(limit=20, categories_total=25)
    assert [r.values["sponsor"] for r in result.rows] == [f"Sponsor {i:02d}" for i in range(1, 21)]


# --- geographic ---


def test_countries_dedupe_per_trial_and_exclude_trials_without_sites() -> None:
    result = _run(Intent.GEOGRAPHIC, Dimension.COUNTRY, cohort(FIXTURE))
    assert _rows(result, "country") == [
        ("France", 2, ["NCT00000004", "NCT00000005"]),
        ("Germany", 2, ["NCT00000001", "NCT00000005"]),
        ("United States", 2, ["NCT00000001", "NCT00000002"]),
    ]
    assert result.excluded == {"no locations": 1}
    assert result.top_n == TopN(limit=20, categories_total=3)


# --- time trend ---


def test_start_years_are_zero_filled_and_missing_dates_counted() -> None:
    result = _run(Intent.TIME_TREND, Dimension.START_YEAR, cohort(FIXTURE))
    assert _rows(result, "start_year") == [
        (2015, 1, ["NCT00000001"]),
        (2016, 0, []),
        (2017, 2, ["NCT00000002", "NCT00000004"]),
        (2018, 1, ["NCT00000005"]),
    ]
    assert result.excluded == {"missing start date": 1}
    assert result.rows[2].evidence["NCT00000002"] == (
        Evidence("statusModule.startDateStruct.date", "2017-06-01"),
    )


def test_stated_year_range_widens_the_zero_fill() -> None:
    filters = RetrievalFilters(start_year=2014, end_year=2019)
    result = _run(Intent.TIME_TREND, Dimension.START_YEAR, cohort(FIXTURE, filters=filters))
    assert [r.values["start_year"] for r in result.rows] == list(range(2014, 2020))
    assert result.rows[0].nct_ids == frozenset()


# --- comparison ---


def test_comparison_zero_fills_every_category_for_every_cohort() -> None:
    result = _run(
        Intent.COMPARISON,
        Dimension.PHASE,
        cohort([T1, T2], label="Pembrolizumab"),
        cohort([T4], label="Nivolumab"),
    )
    assert _rows(result, "phase", "cohort") == [
        ("Phase 1/Phase 2", "Pembrolizumab", 1, ["NCT00000002"]),
        ("Phase 1/Phase 2", "Nivolumab", 0, []),
        ("Phase 3", "Pembrolizumab", 1, ["NCT00000001"]),
        ("Phase 3", "Nivolumab", 1, ["NCT00000004"]),
    ]


def test_comparison_orders_unranked_categories_by_combined_count() -> None:
    result = _run(
        Intent.COMPARISON,
        Dimension.OVERALL_STATUS,
        cohort([T1, T2], label="A"),
        cohort([T4, FIXTURE[4]], label="B"),
    )
    # Combined: Recruiting {T1, T4} = 2, Completed {T2} = 1, Withdrawn {T5} = 1.
    assert [r.values["overall_status"] for r in result.rows[::2]] == [
        "Recruiting",
        "Completed",
        "Withdrawn",
    ]


def test_comparison_exclusions_name_their_cohort() -> None:
    result = _run(
        Intent.COMPARISON,
        Dimension.DRUG,
        cohort([T1], label="Pembrolizumab"),
        cohort([T4], label="Nivolumab"),
    )
    assert result.excluded == {"placebo (Pembrolizumab)": 1}


# --- input guards ---


def test_single_cohort_aggregators_reject_a_comparison() -> None:
    with pytest.raises(AggregationInputError, match="one cohort"):
        REGISTRY.get(Intent.DISTRIBUTION, Dimension.PHASE).aggregate(
            [cohort([T1], label="A"), cohort([T2], label="B")]
        )


@pytest.mark.parametrize("labels", [["A"], ["A", None], ["A", "A"]])
def test_comparison_needs_two_distinct_labelled_cohorts(labels: list[str | None]) -> None:
    cohorts = [cohort([T1], label=label) for label in labels]
    with pytest.raises(AggregationInputError):
        REGISTRY.get(Intent.COMPARISON, Dimension.PHASE).aggregate(cohorts)


def test_result_types_match_the_declared_shape() -> None:
    for intent, dimension in REGISTRY.registered():
        aggregator = REGISTRY.get(intent, dimension)
        cohorts = (
            [cohort(FIXTURE[:3], label="A"), cohort(FIXTURE[3:], label="B")]
            if intent is Intent.COMPARISON
            else [cohort(FIXTURE)]
        )
        result = aggregator.aggregate(cohorts)
        expected = GraphAggregation if intent is Intent.NETWORK else Aggregation
        assert isinstance(result, expected), (intent, dimension)


# --- synonym merges (Phase 8 step 5) ---

# Two trials register RAD001 as an other name of everolimus; a third names RAD001 itself.
_EVEROLIMUS = [
    make_trial("NCT00000011", [("DRUG", "Everolimus", ["RAD001"])]),
    make_trial("NCT00000012", [("DRUG", "Everolimus", ["RAD001"])]),
]
_RAD001 = make_trial("NCT00000013", [("DRUG", "RAD001")])


def test_top_drugs_merge_a_synonym_and_report_it() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.DRUG, cohort([*_EVEROLIMUS, _RAD001]))
    assert _rows(result, "drug") == [
        ("Everolimus", 3, ["NCT00000011", "NCT00000012", "NCT00000013"]),
    ]
    assert [(m.key, m.merged_names) for m in result.name_merges] == [("everolimus", ("RAD001",))]


def test_comparison_merges_with_evidence_from_every_cohort() -> None:
    # The RAD001 cohort holds no listing itself; the other cohort's trials supply the evidence,
    # so both cohorts chart one Everolimus category.
    result = _run(
        Intent.COMPARISON,
        Dimension.DRUG,
        cohort(_EVEROLIMUS, label="A"),
        cohort([_RAD001], label="B"),
    )
    assert _rows(result, "drug", "cohort") == [
        ("Everolimus", "A", 2, ["NCT00000011", "NCT00000012"]),
        ("Everolimus", "B", 1, ["NCT00000013"]),
    ]
    assert [m.key for m in result.name_merges] == ["everolimus"]


def test_charts_without_drugs_report_no_merges() -> None:
    result = _run(Intent.DISTRIBUTION, Dimension.PHASE, cohort([*_EVEROLIMUS, _RAD001]))
    assert result.name_merges == ()


def test_a_trial_in_two_cohorts_counts_once_as_synonym_evidence() -> None:
    # Live (comparison-drug): a trial matching both cohorts was counted twice, which changed the
    # merged drug's label. Own spellings once each: "Everolimus" 1, "everolimus" 2.
    shared = make_trial("NCT00000011", [("DRUG", "Everolimus", ["RAD001"])])
    result = _run(
        Intent.COMPARISON,
        Dimension.DRUG,
        cohort(
            [shared, make_trial("NCT00000012", [("DRUG", "everolimus", ["RAD001"])])], label="A"
        ),
        cohort(
            [shared, make_trial("NCT00000014", [("DRUG", "everolimus")]), _RAD001],
            label="B",
        ),
    )
    assert [(m.label, m.merged_names) for m in result.name_merges] == [("everolimus", ("RAD001",))]
