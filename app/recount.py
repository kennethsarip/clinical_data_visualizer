"""An independent re-derivation of a network from its trials (CLAUDE.md §7.4), for the checks.

The `network` check compares a response's graph with this one, so a counting or pruning bug in
`aggregators/network.py` shows up as a mismatch instead of being reproduced. Only the §6 entity
rules (`app.entities`) and the §7.4 policy values are shared, because they define what a node is;
the co-occurrence counting and the pruning are written again here from the §7.4 text. Phase 7.2
extends this recount to every row shape.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations, product

from app.aggregators.network import MIN_EDGE_WEIGHT, TOP_N_NODES
from app.aggregators.registry import Dimension
from app.entities import EntityType, condition_mentions, select_drugs, sponsor_mention
from app.normalize import NormalizedTrial
from app.schemas import Pruning

Pair = tuple[str, str]

# Entity types per network, first-named first; a two-type edge runs from the first (SCHEMAS.md §3).
NETWORK_ENDS: Mapping[Dimension, tuple[EntityType, EntityType]] = {
    Dimension.SPONSOR_DRUG: (EntityType.SPONSOR, EntityType.DRUG),
    Dimension.DRUG_DRUG: (EntityType.DRUG, EntityType.DRUG),
    Dimension.CONDITION_DRUG: (EntityType.CONDITION, EntityType.DRUG),
}


@dataclass(frozen=True)
class RecountedGraph:
    nodes: dict[str, frozenset[str]]  # node id -> nct_ids, kept nodes only
    edges: dict[Pair, frozenset[str]]  # (source, target) -> nct_ids, kept edges only
    pruning: Pruning


def recount_network(
    dimension: Dimension,
    trials: Sequence[NormalizedTrial],
    min_edge_weight: int = MIN_EDGE_WEIGHT,
    top_n: int = TOP_N_NODES,
) -> RecountedGraph:
    """The pruned graph §7.4 prescribes for `trials`. Raises KeyError for a non-network."""
    first, second = NETWORK_ENDS[dimension]
    nodes, edges = _cooccurrence(trials, first, second)
    weights = {pair: len(ids) for pair, ids in edges.items()}
    weight, fallback = min_edge_weight, False
    kept = _kept_edges(weights, weight, top_n)
    if not kept and weight > 1:
        weight, fallback = 1, True
        kept = _kept_edges(weights, weight, top_n)
    kept_nodes = {node for pair in kept for node in pair}
    pruning = Pruning(
        min_edge_weight=weight,
        top_n_nodes=top_n,
        fallback_used=fallback,
        nodes_removed=len(nodes) - len(kept_nodes),
        edges_removed=len(edges) - len(kept),
    )
    return RecountedGraph(
        {node: frozenset(nodes[node]) for node in kept_nodes},
        {pair: frozenset(edges[pair]) for pair in kept},
        pruning,
    )


def _cooccurrence(
    trials: Sequence[NormalizedTrial], first: EntityType, second: EntityType
) -> tuple[dict[str, set[str]], dict[Pair, set[str]]]:
    """Every node and edge before pruning, each with the trials it appears in."""
    ids = {kind: _entity_ids(kind, trials) for kind in (first, second)}
    nodes: dict[str, set[str]] = {}
    edges: dict[Pair, set[str]] = {}
    for trial in trials:
        ends_a, ends_b = ids[first][trial.nct_id], ids[second][trial.nct_id]
        for node in {*ends_a, *ends_b}:
            nodes.setdefault(node, set()).add(trial.nct_id)
        pairs = combinations(sorted(ends_a), 2) if first == second else product(ends_a, ends_b)
        for pair in pairs:
            edges.setdefault(pair, set()).add(trial.nct_id)
    return nodes, edges


def _entity_ids(kind: EntityType, trials: Sequence[NormalizedTrial]) -> dict[str, set[str]]:
    """nct_id -> the node ids of that trial's entities of one type (§6 rules)."""
    if kind is EntityType.DRUG:
        mentions = select_drugs(trials).mentions
    elif kind is EntityType.SPONSOR:
        mentions = {t.nct_id: (sponsor_mention(t),) for t in trials}
    else:
        mentions = {t.nct_id: condition_mentions(t) for t in trials}
    return {nct_id: {f"{kind}:{m.key}" for m in found} for nct_id, found in mentions.items()}


def _kept_edges(weights: Mapping[Pair, int], min_weight: int, top_n: int) -> set[Pair]:
    """Edges at or above `min_weight` whose ends are both among the `top_n` nodes by weighted
    degree (ties alphabetical). Orphans fall out because nodes are read off the kept edges."""
    heavy = {pair: w for pair, w in weights.items() if w >= min_weight}
    degree: dict[str, int] = {}
    for pair, w in heavy.items():
        for node in pair:
            degree[node] = degree.get(node, 0) + w
    top = set(sorted(degree, key=lambda node: (-degree[node], node))[:top_n])
    return {pair for pair in heavy if pair[0] in top and pair[1] in top}
