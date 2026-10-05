"""Aggregator registry: dispatch by (intent, dimension) and declaration guards (CLAUDE.md §7.4)."""

from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from app.aggregators.registry import (
    Aggregation,
    AggregatorDeclarationError,
    CohortTrials,
    Dimension,
    DuplicateAggregatorError,
    GraphAggregation,
    Intent,
    Registry,
    RowShape,
    UnknownAggregatorError,
)


@dataclass(frozen=True)
class FakeAggregator:
    intent: Intent = Intent.DISTRIBUTION
    dimension: Dimension = Dimension.PHASE
    shape: RowShape = RowShape.CATEGORICAL
    columns: tuple[str, ...] = ("phase",)
    excerpt_fields: tuple[str, ...] = ("designModule.phases",)

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> Aggregation | GraphAggregation:
        return Aggregation(rows=(), excluded={})


def test_lookup_returns_the_registered_aggregator() -> None:
    registry = Registry()
    aggregator = FakeAggregator()
    registry.register(aggregator)
    assert registry.get(Intent.DISTRIBUTION, Dimension.PHASE) is aggregator


def test_unknown_pair_raises_a_typed_error_naming_it() -> None:
    registry = Registry()
    registry.register(FakeAggregator())
    with pytest.raises(UnknownAggregatorError, match="time_trend.*country"):
        registry.get(Intent.TIME_TREND, Dimension.COUNTRY)


def test_registering_the_same_pair_twice_is_rejected() -> None:
    registry = Registry()
    registry.register(FakeAggregator())
    with pytest.raises(DuplicateAggregatorError, match="distribution.*phase"):
        registry.register(FakeAggregator(columns=("phase", "other")))


def test_registered_lists_every_registered_pair_in_a_stable_order() -> None:
    registry = Registry()
    registry.register(FakeAggregator(dimension=Dimension.PHASE))
    registry.register(
        FakeAggregator(
            intent=Intent.TIME_TREND,
            dimension=Dimension.START_YEAR,
            shape=RowShape.TEMPORAL,
            columns=("start_year",),
        )
    )
    registry.register(FakeAggregator(dimension=Dimension.COUNTRY, columns=("country",)))
    assert registry.registered() == [
        (Intent.DISTRIBUTION, Dimension.COUNTRY),
        (Intent.DISTRIBUTION, Dimension.PHASE),
        (Intent.TIME_TREND, Dimension.START_YEAR),
    ]


# The §1 coverage matrix fixes which row shapes each question class produces.
@pytest.mark.parametrize(
    ("intent", "shape"),
    [
        (Intent.TIME_TREND, RowShape.CATEGORICAL),
        (Intent.DISTRIBUTION, RowShape.TEMPORAL),
        (Intent.GEOGRAPHIC, RowShape.GRAPH),
        (Intent.COMPARISON, RowShape.CATEGORICAL),
        (Intent.NUMERIC, RowShape.CATEGORICAL),
        (Intent.NETWORK, RowShape.TWO_CATEGORICAL),
    ],
)
def test_shape_that_contradicts_the_intent_is_rejected(intent: Intent, shape: RowShape) -> None:
    with pytest.raises(AggregatorDeclarationError, match="shape"):
        Registry().register(FakeAggregator(intent=intent, shape=shape))


@pytest.mark.parametrize(
    ("intent", "shape"),
    [
        (Intent.TIME_TREND, RowShape.TEMPORAL),
        (Intent.DISTRIBUTION, RowShape.CATEGORICAL),
        (Intent.GEOGRAPHIC, RowShape.CATEGORICAL),
        (Intent.COMPARISON, RowShape.TWO_CATEGORICAL),
        (Intent.NUMERIC, RowShape.PER_TRIAL_NUMERIC),
        (Intent.NUMERIC, RowShape.BINNED_NUMERIC),
        (Intent.NETWORK, RowShape.GRAPH),
    ],
)
def test_shape_that_fits_the_intent_is_accepted(intent: Intent, shape: RowShape) -> None:
    Registry().register(FakeAggregator(intent=intent, shape=shape))


@pytest.mark.parametrize("column", ["trial_count", "nct_ids", "citations"])
def test_columns_may_not_shadow_provenance_fields(column: str) -> None:
    # Every row already carries these (SCHEMAS.md §2); a dimension column with the same name
    # would overwrite them.
    with pytest.raises(AggregatorDeclarationError, match=column):
        Registry().register(FakeAggregator(columns=("phase", column)))


def test_an_aggregator_must_declare_columns_and_excerpt_fields() -> None:
    with pytest.raises(AggregatorDeclarationError, match="columns"):
        Registry().register(FakeAggregator(columns=()))
    with pytest.raises(AggregatorDeclarationError, match="excerpt"):
        Registry().register(FakeAggregator(excerpt_fields=()))
