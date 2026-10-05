"""Co-occurrence networks: sponsor-drug, drug-drug and condition-drug (§1, §7.4).

A network here is an aggregation over records, not graph retrieval: a node is one entity (after
the §6 drug rule and name rules), and an edge's weight is the number of trials naming both ends.
One aggregator, configured with two entity "sides", covers every pair, so a new network is a new
registration rather than new code.

Pruning (decided 2026-10-04): drop edges below `min_edge_weight`, keep the `top_n_nodes` nodes by
weighted degree, then drop edges to removed nodes and nodes left without edges. If that empties
the graph, rerun at weight 1, because an empty picture is useless to the user. `Pruning` records
what was done.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations, product

from app.aggregators.common import (
    F_CONDITION,
    F_INTERVENTION_NAME,
    F_SPONSOR,
    NO_CONDITIONS_RULE,
    Value,
    gap_counts,
    nonzero,
    single_cohort,
)
from app.aggregators.registry import (
    REGISTRY,
    AggRow,
    CohortTrials,
    Dimension,
    Evidence,
    GraphAggregation,
    Intent,
    RowShape,
)
from app.entities import (
    DrugMerge,
    EntityType,
    Mention,
    combine_merges,
    condition_mentions,
    drug_aliases,
    entity_key,
    most_common_spelling,
    select_drugs,
    sponsor_mention,
)
from app.normalize import Gap, NormalizedTrial
from app.schemas import Pruning, RetrievalFilters

MIN_EDGE_WEIGHT = 2
TOP_N_NODES = 50

Mentions = dict[str, tuple[Mention, ...]]  # nct_id -> entities in that trial
End = tuple["Side", Mention]
# trials -> (entities per trial, counting-rule exclusions, synonym merges applied)
Extract = Callable[
    [Sequence[NormalizedTrial]], tuple[Mentions, dict[str, int], tuple[DrugMerge, ...]]
]


@dataclass(frozen=True)
class Side:
    """One end of an edge: an entity type, the record field its excerpts quote, its extractor."""

    entity_type: EntityType
    field: str
    extract: Extract


def _drugs(
    trials: Sequence[NormalizedTrial],
) -> tuple[Mentions, dict[str, int], tuple[DrugMerge, ...]]:
    selection = select_drugs(trials)
    excluded = nonzero(selection.excluded) | gap_counts(
        trials, Gap.NO_INTERVENTIONS, Gap.UNNAMED_INTERVENTION
    )
    return selection.mentions, excluded, selection.merges


def _sponsors(
    trials: Sequence[NormalizedTrial],
) -> tuple[Mentions, dict[str, int], tuple[DrugMerge, ...]]:
    return {t.nct_id: (sponsor_mention(t),) for t in trials}, {}, ()


def _conditions(
    trials: Sequence[NormalizedTrial],
) -> tuple[Mentions, dict[str, int], tuple[DrugMerge, ...]]:
    excluded = nonzero({NO_CONDITIONS_RULE: sum(not t.conditions for t in trials)})
    return {t.nct_id: condition_mentions(t) for t in trials}, excluded, ()


DRUG_SIDE = Side(EntityType.DRUG, F_INTERVENTION_NAME, _drugs)
SPONSOR_SIDE = Side(EntityType.SPONSOR, F_SPONSOR, _sponsors)
CONDITION_SIDE = Side(EntityType.CONDITION, F_CONDITION, _conditions)


@dataclass
class _Accumulator:
    """One node's or edge's trials and evidence, plus label votes for nodes."""

    nct_ids: set[str] = field(default_factory=set)
    evidence: dict[str, tuple[Evidence, ...]] = field(default_factory=dict)
    votes: list[str] = field(default_factory=list)

    def add(self, nct_id: str, evidence: tuple[Evidence, ...], vote: str | None = None) -> None:
        if nct_id in self.nct_ids:
            return
        self.nct_ids.add(nct_id)
        self.evidence[nct_id] = evidence
        if vote is not None:
            self.votes.append(vote)


@dataclass(frozen=True)
class CooccurrenceAggregator:
    dimension: Dimension
    first: Side
    second: Side
    min_edge_weight: int = MIN_EDGE_WEIGHT
    top_n_nodes: int = TOP_N_NODES

    @property
    def intent(self) -> Intent:
        return Intent.NETWORK

    @property
    def shape(self) -> RowShape:
        return RowShape.GRAPH

    @property
    def columns(self) -> tuple[str, ...]:
        return ("id", "label", "entity_type", "is_anchor")

    @property
    def excerpt_fields(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.first.field, self.second.field)))

    @property
    def _one_type(self) -> bool:
        return self.first == self.second

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> GraphAggregation:
        cohort = single_cohort(cohorts)
        trials = cohort.batch.trials
        first, excluded, merges = self.first.extract(trials)
        second, second_excluded, second_merges = (
            (first, {}, ()) if self._one_type else self.second.extract(trials)
        )
        nodes, edges = self._accumulate(trials, first, second)
        kept_nodes, kept_edges, pruning = self._prune(nodes, edges)
        anchors = _anchor_ids(cohort.filters, drug_aliases(trials))
        node_rows = sorted(
            (_node_row(node_id, nodes[node_id], node_id in anchors) for node_id in kept_nodes),
            key=lambda row: (-len(row.nct_ids), row.values["id"]),
        )
        edge_rows = sorted(
            (_edge_row(pair, edges[pair]) for pair in kept_edges),
            key=lambda row: (-len(row.nct_ids), row.values["source"], row.values["target"]),
        )
        return GraphAggregation(
            tuple(node_rows),
            tuple(edge_rows),
            excluded | second_excluded,
            pruning,
            combine_merges(merges, second_merges),
        )

    def _accumulate(
        self, trials: Sequence[NormalizedTrial], first: Mentions, second: Mentions
    ) -> tuple[dict[str, _Accumulator], dict[tuple[str, str], _Accumulator]]:
        nodes: dict[str, _Accumulator] = {}
        edges: dict[tuple[str, str], _Accumulator] = {}
        for trial in trials:
            nct = trial.nct_id
            ends_a = [(self.first, m) for m in first.get(nct, ())]
            ends_b = [(self.second, m) for m in second.get(nct, ())]
            for side, m in ends_a + ([] if self._one_type else ends_b):
                node = nodes.setdefault(_node_id(side, m), _Accumulator())
                node.add(nct, (Evidence(side.field, m.raw),), m.label)
            # One type: source < target by id, so an undirected pair has one key.
            pairs: Iterable[tuple[End, End]] = (
                combinations(sorted(ends_a, key=lambda e: _node_id(*e)), 2)
                if self._one_type
                else product(ends_a, ends_b)
            )
            for (side_x, x), (side_y, y) in pairs:
                edge = edges.setdefault((_node_id(side_x, x), _node_id(side_y, y)), _Accumulator())
                edge.add(nct, (Evidence(side_x.field, x.raw), Evidence(side_y.field, y.raw)))
        return nodes, edges

    def _prune(
        self, nodes: Mapping[str, _Accumulator], edges: Mapping[tuple[str, str], _Accumulator]
    ) -> tuple[set[str], set[tuple[str, str]], Pruning]:
        weights = {pair: len(acc.nct_ids) for pair, acc in edges.items()}
        min_weight, fallback = self.min_edge_weight, False
        kept_nodes, kept_edges = _prune(weights, min_weight, self.top_n_nodes)
        if not kept_edges and min_weight > 1:
            min_weight, fallback = 1, True
            kept_nodes, kept_edges = _prune(weights, min_weight, self.top_n_nodes)
        pruning = Pruning(
            min_edge_weight=min_weight,
            top_n_nodes=self.top_n_nodes,
            fallback_used=fallback,
            nodes_removed=len(nodes) - len(kept_nodes),
            edges_removed=len(edges) - len(kept_edges),
        )
        return kept_nodes, kept_edges, pruning


def _prune(
    weights: Mapping[tuple[str, str], int], min_weight: int, top_n: int
) -> tuple[set[str], set[tuple[str, str]]]:
    heavy = {pair: w for pair, w in weights.items() if w >= min_weight}
    degree: dict[str, int] = {}
    for (source, target), weight in heavy.items():
        degree[source] = degree.get(source, 0) + weight
        degree[target] = degree.get(target, 0) + weight
    top = set(sorted(degree, key=lambda node: (-degree[node], node))[:top_n])
    kept_edges = {pair for pair in heavy if pair[0] in top and pair[1] in top}
    kept_nodes = {node for pair in kept_edges for node in pair}  # drops orphans
    return kept_nodes, kept_edges


def _node_id(side: Side, mention: Mention) -> str:
    return f"{side.entity_type}:{mention.key}"


def _node_row(node_id: str, acc: _Accumulator, is_anchor: bool) -> AggRow:
    entity_type = node_id.split(":", 1)[0]
    values: dict[str, Value] = {
        "id": node_id,
        "label": most_common_spelling(acc.votes),
        "entity_type": entity_type,
        "is_anchor": is_anchor,
    }
    return AggRow(values, frozenset(acc.nct_ids), acc.evidence)


def _edge_row(pair: tuple[str, str], acc: _Accumulator) -> AggRow:
    return AggRow({"source": pair[0], "target": pair[1]}, frozenset(acc.nct_ids), acc.evidence)


def _anchor_ids(filters: RetrievalFilters, aliases: Mapping[str, str]) -> set[str]:
    """Nodes for the entities the request named: they sit in every trial, so they are hubs. A
    named drug that is a merged synonym ("Keytruda") anchors the drug it merged into."""
    named = [
        (EntityType.DRUG, filters.drug_name),
        (EntityType.SPONSOR, filters.sponsor),
        (EntityType.CONDITION, filters.condition),
    ]
    ids = set()
    for kind, name in named:
        if name is not None:
            key = entity_key(kind, name)
            ids.add(f"{kind}:{aliases.get(key, key) if kind is EntityType.DRUG else key}")
    return ids


REGISTRY.register(CooccurrenceAggregator(Dimension.SPONSOR_DRUG, SPONSOR_SIDE, DRUG_SIDE))
REGISTRY.register(CooccurrenceAggregator(Dimension.DRUG_DRUG, DRUG_SIDE, DRUG_SIDE))
REGISTRY.register(CooccurrenceAggregator(Dimension.CONDITION_DRUG, CONDITION_SIDE, DRUG_SIDE))
