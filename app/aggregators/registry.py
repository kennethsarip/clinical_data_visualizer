"""Single source of (intent, dimension) -> aggregator dispatch (CLAUDE.md §7.4).

A new question class is a new registered aggregator, never a new code path: the pipeline looks up
the plan's (intent, dimension) here, and the planner's choices are generated from `registered()`,
so it can only pick what exists. Each aggregator declares its row shape, which fixes the viz type
(`viz.py`), and the record fields its excerpts quote, which the checks read.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.normalize import NormalizedBatch
from app.schemas import Provenance, Pruning, RetrievalFilters, TopN


class Intent(StrEnum):
    """The question classes of the CLAUDE.md §1 coverage matrix."""

    TIME_TREND = "time_trend"
    DISTRIBUTION = "distribution"
    COMPARISON = "comparison"
    GEOGRAPHIC = "geographic"
    NUMERIC = "numeric"
    NETWORK = "network"


class Dimension(StrEnum):
    """What rows are grouped on. Categorical values double as the row's column name."""

    PHASE = "phase"
    OVERALL_STATUS = "overall_status"
    INTERVENTION_TYPE = "intervention_type"
    SPONSOR_CLASS = "sponsor_class"
    DRUG = "drug"
    SPONSOR = "sponsor"
    CONDITION = "condition"
    COUNTRY = "country"
    START_YEAR = "start_year"
    ENROLLMENT_BY_START_DATE = "enrollment_by_start_date"
    ENROLLMENT = "enrollment"
    SPONSOR_DRUG = "sponsor_drug"
    DRUG_DRUG = "drug_drug"
    CONDITION_DRUG = "condition_drug"


class RowShape(StrEnum):
    CATEGORICAL = "categorical"
    TWO_CATEGORICAL = "two_categorical"
    TEMPORAL = "temporal"
    PER_TRIAL_NUMERIC = "per_trial_numeric"
    BINNED_NUMERIC = "binned_numeric"
    GRAPH = "graph"


# The §1 coverage matrix: the shapes each question class may produce. A mismatch is a
# declaration bug, caught at registration rather than as a wrong chart.
INTENT_SHAPES: Mapping[Intent, frozenset[RowShape]] = {
    Intent.TIME_TREND: frozenset({RowShape.TEMPORAL}),
    Intent.DISTRIBUTION: frozenset({RowShape.CATEGORICAL}),
    Intent.GEOGRAPHIC: frozenset({RowShape.CATEGORICAL}),
    Intent.COMPARISON: frozenset({RowShape.TWO_CATEGORICAL}),
    Intent.NUMERIC: frozenset({RowShape.PER_TRIAL_NUMERIC, RowShape.BINNED_NUMERIC}),
    Intent.NETWORK: frozenset({RowShape.GRAPH}),
}

# Counting-rule name -> the NCT IDs it acted on (Phase 7 step 3: accounting by ID). A count in
# `meta.excluded` is the size of its set, so the two cannot disagree.
Excluded = Mapping[str, frozenset[str]]

# Fields every row, node and edge already carries (SCHEMAS.md §2).
PROVENANCE_FIELDS = frozenset(Provenance.model_fields)


@dataclass(frozen=True)
class CohortTrials:
    """One cohort's trials and the filters that fetched them.

    `label` is None unless the request compares cohorts. Aggregators read `filters` only for
    stated bounds and anchors (the zero-fill year range, the network's anchor node).
    """

    label: str | None
    batch: NormalizedBatch
    filters: RetrievalFilters
    total: int  # trials matching `filters` per the API's totalCount; more than fetched if capped
    # Fetched trials dropped for failing an exact filter (app/conformance.py): rule -> NCT IDs.
    # Not in `batch`, but fetched, so `meta.sample` and `meta.excluded` count them.
    off_filter: Excluded = field(default_factory=dict)


@dataclass(frozen=True)
class Evidence:
    """The record value that placed a trial in a row; `excerpt` None means the field is absent."""

    field: str
    excerpt: str | None


@dataclass(frozen=True)
class AggRow:
    """A row, node or edge before citations: its column values and its provenance."""

    values: Mapping[str, str | int | bool | None]
    nct_ids: frozenset[str]
    evidence: Mapping[str, tuple[Evidence, ...]]  # nct_id -> evidence; keys equal nct_ids


@dataclass(frozen=True)
class Aggregation:
    rows: tuple[AggRow, ...]  # in render order (SCHEMAS.md §4 `sort`)
    excluded: Excluded  # counting-rule name -> the trials it acted on (`meta.excluded`)
    top_n: TopN | None = None


@dataclass(frozen=True)
class GraphAggregation:
    nodes: tuple[AggRow, ...]
    edges: tuple[AggRow, ...]
    excluded: Excluded
    pruning: Pruning


class Aggregator(Protocol):
    @property
    def intent(self) -> Intent: ...
    @property
    def dimension(self) -> Dimension: ...
    @property
    def shape(self) -> RowShape: ...
    @property
    def columns(self) -> tuple[str, ...]: ...  # row fields besides provenance
    @property
    def excerpt_fields(self) -> tuple[str, ...]: ...  # record paths its evidence quotes

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> Aggregation | GraphAggregation: ...


class UnknownAggregatorError(LookupError):
    """No aggregator is registered for the plan's (intent, dimension)."""


class DuplicateAggregatorError(ValueError):
    """Two aggregators claim the same (intent, dimension)."""


class AggregatorDeclarationError(ValueError):
    """An aggregator's declaration contradicts the coverage matrix or the row contract."""


class AggregationInputError(ValueError):
    """An aggregator got cohorts it cannot use (e.g. two cohorts for a single-cohort chart)."""


class Registry:
    def __init__(self) -> None:
        self._by_key: dict[tuple[Intent, Dimension], Aggregator] = {}

    def register(self, aggregator: Aggregator) -> None:
        _check_declaration(aggregator)
        key = (aggregator.intent, aggregator.dimension)
        if key in self._by_key:
            raise DuplicateAggregatorError(f"an aggregator is already registered for {_name(key)}")
        self._by_key[key] = aggregator

    def get(self, intent: Intent, dimension: Dimension) -> Aggregator:
        try:
            return self._by_key[(intent, dimension)]
        except KeyError:
            raise UnknownAggregatorError(
                f"no aggregator registered for {_name((intent, dimension))}"
            ) from None

    def registered(self) -> list[tuple[Intent, Dimension]]:
        """Every registered pair, sorted, so the planner's generated schema is stable."""
        return sorted(self._by_key)


def _check_declaration(aggregator: Aggregator) -> None:
    key = _name((aggregator.intent, aggregator.dimension))
    allowed = INTENT_SHAPES[aggregator.intent]
    if aggregator.shape not in allowed:
        raise AggregatorDeclarationError(
            f"{key}: shape {aggregator.shape} does not fit intent {aggregator.intent} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )
    if not aggregator.columns:
        raise AggregatorDeclarationError(f"{key}: declares no columns")
    if not aggregator.excerpt_fields:
        raise AggregatorDeclarationError(f"{key}: declares no excerpt fields")
    shadowed = PROVENANCE_FIELDS.intersection(aggregator.columns)
    if shadowed:
        raise AggregatorDeclarationError(
            f"{key}: columns {sorted(shadowed)} shadow provenance fields"
        )


def _name(key: tuple[Intent, Dimension]) -> str:
    return f"({key[0]}, {key[1]})"


# The registry the pipeline dispatches through; aggregator modules register into it.
REGISTRY = Registry()
