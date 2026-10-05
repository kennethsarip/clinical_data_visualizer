"""The independent network recount behind the `network` check (CLAUDE.md §7.4 pruning).

Expected graphs are derived by hand from the §7.4 rules, not from the aggregator's output.
"""

from app.aggregators.registry import Dimension
from app.normalize import NormalizedTrial
from app.recount import recount_network
from app.schemas import Pruning
from tests.factories import make_trial


def _trial(nct_id: str, *drugs: str, sponsor: str = "Merck Sharp & Dohme LLC") -> NormalizedTrial:
    return make_trial(nct_id, [("DRUG", d) for d in drugs], sponsor_name=sponsor)


def test_edges_below_the_weight_threshold_are_pruned() -> None:
    trials = [_trial("NCT00000001", "A", "B"), _trial("NCT00000002", "A", "B", "C")]
    graph = recount_network(Dimension.DRUG_DRUG, trials)
    assert graph.edges == {("drug:a", "drug:b"): frozenset({"NCT00000001", "NCT00000002"})}
    assert graph.nodes == {
        "drug:a": frozenset({"NCT00000001", "NCT00000002"}),
        "drug:b": frozenset({"NCT00000001", "NCT00000002"}),
    }
    assert graph.pruning == Pruning(
        min_edge_weight=2, top_n_nodes=50, fallback_used=False, nodes_removed=1, edges_removed=2
    )


def test_an_empty_graph_falls_back_to_weight_one() -> None:
    graph = recount_network(Dimension.DRUG_DRUG, [_trial("NCT00000001", "A", "B")])
    assert set(graph.edges) == {("drug:a", "drug:b")}
    assert graph.pruning.fallback_used and graph.pruning.min_edge_weight == 1


def test_top_n_keeps_the_heaviest_nodes_with_an_alphabetical_tie_break() -> None:
    # One trial with three drugs: every node has weighted degree 2, so "a" and "b" win the tie.
    graph = recount_network(Dimension.DRUG_DRUG, [_trial("NCT00000001", "C", "B", "A")], top_n=2)
    assert set(graph.nodes) == {"drug:a", "drug:b"}
    assert set(graph.edges) == {("drug:a", "drug:b")}
    assert (graph.pruning.nodes_removed, graph.pruning.edges_removed) == (1, 2)


def test_two_type_edges_run_from_the_first_named_type() -> None:
    trials = [_trial("NCT00000001", "Zeta"), _trial("NCT00000002", "Zeta")]
    graph = recount_network(Dimension.SPONSOR_DRUG, trials)
    assert set(graph.edges) == {("sponsor:merck sharp dohme", "drug:zeta")}
