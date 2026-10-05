"""Enrollment scatter and histogram, and co-occurrence networks (CLAUDE.md §6, §7.4).

Expected rows are derived by hand from `tests/factories.py` FIXTURE and the §6/§7.4 rules.
"""

from typing import Any

from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    Dimension,
    Evidence,
    GraphAggregation,
    Intent,
)
from app.schemas import Pruning, RetrievalFilters
from tests.factories import FIXTURE, cohort, make_trial

NAME = "armsInterventionsModule.interventions.name"
SPONSOR = "sponsorCollaboratorsModule.leadSponsor.name"


def _aggregate(intent: Intent, dimension: Dimension, *cohorts: Any) -> Aggregation:
    result = REGISTRY.get(intent, dimension).aggregate(list(cohorts))
    assert isinstance(result, Aggregation)
    return result


def _graph(dimension: Dimension, *cohorts: Any) -> GraphAggregation:
    result = REGISTRY.get(Intent.NETWORK, dimension).aggregate(list(cohorts))
    assert isinstance(result, GraphAggregation)
    return result


# --- enrollment scatter ---


def test_scatter_has_one_point_per_trial_sorted_by_start_date() -> None:
    result = _aggregate(Intent.NUMERIC, Dimension.ENROLLMENT_BY_START_DATE, cohort(FIXTURE))
    assert [dict(r.values) for r in result.rows] == [
        {
            "nct_id": "NCT00000001",
            "start_date": "2015-03",
            "enrollment": 120,
            "enrollment_type": "Actual",
        },
        {
            "nct_id": "NCT00000004",
            "start_date": "2017-01",
            "enrollment": 0,
            "enrollment_type": "Actual",
        },
        {
            "nct_id": "NCT00000002",
            "start_date": "2017-06-01",
            "enrollment": 48,
            "enrollment_type": "Estimated",
        },
        {
            "nct_id": "NCT00000005",
            "start_date": "2018-02",
            "enrollment": 5000,
            "enrollment_type": "Type not reported",
        },
    ]
    assert all(r.nct_ids == {r.values["nct_id"]} for r in result.rows)
    # T3 lacks both values; it is counted under each rule.
    assert result.excluded == {"missing enrollment": 1, "missing start date": 1}
    assert result.rows[0].evidence["NCT00000001"] == (
        Evidence("designModule.enrollmentInfo.count", "120"),
        Evidence("statusModule.startDateStruct.date", "2015-03"),
    )


# --- enrollment histogram ---

BIN_LABELS = ["0", "1-9", "10-49", "50-99", "100-249", "250-499", "500-999", "1000-4999", "5000+"]


def test_histogram_bins_are_fixed_half_open_and_split_by_enrollment_type() -> None:
    result = _aggregate(Intent.NUMERIC, Dimension.ENROLLMENT, cohort(FIXTURE))
    series = ["Actual", "Estimated", "Type not reported"]
    # Every bin for every enrollment type present, bin-major.
    assert [(r.values["bin_label"], r.values["enrollment_type"]) for r in result.rows] == [
        (b, s) for b in BIN_LABELS for s in series
    ]
    nonzero = {
        (r.values["bin_label"], r.values["enrollment_type"]): sorted(r.nct_ids)
        for r in result.rows
        if r.nct_ids
    }
    assert nonzero == {
        ("0", "Actual"): ["NCT00000004"],
        ("10-49", "Estimated"): ["NCT00000002"],
        ("100-249", "Actual"): ["NCT00000001"],
        ("5000+", "Type not reported"): ["NCT00000005"],
    }
    assert result.excluded == {"missing enrollment": 1}


def test_histogram_bin_edges() -> None:
    result = _aggregate(Intent.NUMERIC, Dimension.ENROLLMENT, cohort(FIXTURE))
    edges = [(r.values["bin_start"], r.values["bin_end"]) for r in result.rows[::3]]
    assert edges == [
        (0, 1),
        (1, 10),
        (10, 50),
        (50, 100),
        (100, 250),
        (250, 500),
        (500, 1000),
        (1000, 5000),
        (5000, None),
    ]


def test_histogram_boundaries_fall_in_the_upper_bin() -> None:
    trials = [
        make_trial(f"NCT0000001{i}", enrollment=n, enrollment_type="ACTUAL")
        for i, n in enumerate([1, 9, 10, 4999, 5000])
    ]
    result = _aggregate(Intent.NUMERIC, Dimension.ENROLLMENT, cohort(trials))
    counts = {r.values["bin_label"]: len(r.nct_ids) for r in result.rows}
    assert counts == {
        "0": 0,
        "1-9": 2,
        "10-49": 1,
        "50-99": 0,
        "100-249": 0,
        "250-499": 0,
        "500-999": 0,
        "1000-4999": 1,
        "5000+": 1,
    }


# --- networks ---


def _edges(graph: GraphAggregation) -> list[tuple[Any, Any, list[str]]]:
    return [(e.values["source"], e.values["target"], sorted(e.nct_ids)) for e in graph.edges]


def _nodes(graph: GraphAggregation) -> list[tuple[Any, Any, int, Any]]:
    return [
        (n.values["id"], n.values["label"], len(n.nct_ids), n.values["is_anchor"])
        for n in graph.nodes
    ]


def test_drug_drug_falls_back_to_weight_one_when_weight_two_empties_the_graph() -> None:
    # Pairs: ipilimumab-pembrolizumab {T2}, ipilimumab-nivolumab {T4}; both weight 1.
    filters = RetrievalFilters(drug_name="Pembrolizumab")
    graph = _graph(Dimension.DRUG_DRUG, cohort(FIXTURE, filters=filters))
    assert _edges(graph) == [
        ("drug:ipilimumab", "drug:nivolumab", ["NCT00000004"]),
        ("drug:ipilimumab", "drug:pembrolizumab", ["NCT00000002"]),
    ]
    # Node size counts every trial naming the drug, including T1 where pembrolizumab is alone.
    assert _nodes(graph) == [
        ("drug:ipilimumab", "Ipilimumab", 2, False),
        ("drug:pembrolizumab", "Pembrolizumab", 2, True),
        ("drug:nivolumab", "Nivolumab", 1, False),
    ]
    assert graph.pruning == Pruning(
        min_edge_weight=1, top_n_nodes=50, fallback_used=True, nodes_removed=0, edges_removed=0
    )
    assert graph.excluded == {
        "placebo": 1,
        "non-drug intervention": 1,
        "no drug intervention": 1,
        "no interventions": 1,
    }


def test_edge_evidence_cites_both_ends_verbatim() -> None:
    graph = _graph(Dimension.DRUG_DRUG, cohort(FIXTURE))
    edge = graph.edges[1]
    assert edge.evidence["NCT00000002"] == (
        Evidence(NAME, "Ipilimumab"),
        Evidence(NAME, "Pembrolizumab (MK-3475)"),
    )


def test_sponsor_drug_prunes_weight_one_edges_and_orphan_nodes() -> None:
    graph = _graph(Dimension.SPONSOR_DRUG, cohort(FIXTURE))
    # Edges: merck-pembrolizumab {T1, T2}; merck-ipilimumab {T2}; bms-nivolumab {T4};
    # bms-ipilimumab {T4}. Only the first reaches weight 2.
    assert _edges(graph) == [
        ("sponsor:merck sharp dohme", "drug:pembrolizumab", ["NCT00000001", "NCT00000002"]),
    ]
    assert _nodes(graph) == [
        ("drug:pembrolizumab", "Pembrolizumab", 2, False),
        ("sponsor:merck sharp dohme", "Merck Sharp & Dohme LLC", 2, False),
    ]
    # Nodes: merck, bms, nci, pembrolizumab, ipilimumab, nivolumab = 6; 2 kept.
    assert graph.pruning == Pruning(
        min_edge_weight=2, top_n_nodes=50, fallback_used=False, nodes_removed=4, edges_removed=3
    )
    assert graph.edges[0].evidence["NCT00000002"] == (
        Evidence(SPONSOR, "merck sharp & dohme llc"),
        Evidence(NAME, "Pembrolizumab (MK-3475)"),
    )


def test_condition_drug_network_and_condition_anchor() -> None:
    filters = RetrievalFilters(condition="melanoma")
    graph = _graph(Dimension.CONDITION_DRUG, cohort(FIXTURE, filters=filters))
    # melanoma-pembrolizumab {T1, T2}, melanoma-ipilimumab {T2, T4}; the rest weight 1.
    assert _edges(graph) == [
        ("condition:melanoma", "drug:ipilimumab", ["NCT00000002", "NCT00000004"]),
        ("condition:melanoma", "drug:pembrolizumab", ["NCT00000001", "NCT00000002"]),
    ]
    anchors = [n.values["id"] for n in graph.nodes if n.values["is_anchor"]]
    assert anchors == ["condition:melanoma"]


def test_top_n_nodes_keeps_the_highest_weighted_degree() -> None:
    from app.aggregators.network import CooccurrenceAggregator

    pairs = [("A", "B")] * 2 + [("A", "C")] * 2 + [("B", "C")] * 2 + [("A", "D")] * 3
    trials = [
        make_trial(f"NCT{i:08d}", [("DRUG", x), ("DRUG", y)]) for i, (x, y) in enumerate(pairs, 1)
    ]
    aggregator = REGISTRY.get(Intent.NETWORK, Dimension.DRUG_DRUG)
    assert isinstance(aggregator, CooccurrenceAggregator)
    small = CooccurrenceAggregator(
        aggregator.dimension, aggregator.first, aggregator.second, top_n_nodes=2
    )
    graph = small.aggregate([cohort(trials)])
    assert isinstance(graph, GraphAggregation)
    # Weighted degree: A = 2+2+3 = 7, B = 4, C = 4, D = 3. Top 2: A, then B (tie with C by id).
    assert [n.values["id"] for n in graph.nodes] == ["drug:a", "drug:b"]
    assert _edges(graph) == [("drug:a", "drug:b", ["NCT00000001", "NCT00000002"])]
    assert graph.pruning.nodes_removed == 2
    assert graph.pruning.edges_removed == 3


def test_graph_with_no_cooccurrence_is_empty_not_an_error() -> None:
    trials = [make_trial("NCT00000001", [("DRUG", "Aspirin")])]
    graph = _graph(Dimension.DRUG_DRUG, cohort(trials))
    assert graph.nodes == () and graph.edges == ()
    assert graph.pruning.fallback_used is True


# --- coverage ---


def test_every_coverage_matrix_class_is_registered() -> None:
    # CLAUDE.md §1 coverage matrix and §14 Phase 2 step 4.
    categorical = [
        Dimension.PHASE,
        Dimension.OVERALL_STATUS,
        Dimension.INTERVENTION_TYPE,
        Dimension.SPONSOR_CLASS,
        Dimension.DRUG,
        Dimension.SPONSOR,
        Dimension.CONDITION,
    ]
    expected = (
        {(Intent.DISTRIBUTION, d) for d in categorical}
        | {(Intent.GEOGRAPHIC, Dimension.COUNTRY), (Intent.TIME_TREND, Dimension.START_YEAR)}
        | {(Intent.COMPARISON, d) for d in [*categorical, Dimension.COUNTRY]}
        | {
            (Intent.NUMERIC, Dimension.ENROLLMENT_BY_START_DATE),
            (Intent.NUMERIC, Dimension.ENROLLMENT),
        }
        | {
            (Intent.NETWORK, d)
            for d in [Dimension.SPONSOR_DRUG, Dimension.DRUG_DRUG, Dimension.CONDITION_DRUG]
        }
    )
    assert set(REGISTRY.registered()) == expected
