"""Trials started per year, zero-filled (§1, §7.4).

A year with no trials is information, so gap years get a zero row. The range runs from the stated
start year (or the earliest trial) to the stated end year (or the latest trial).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.aggregators.common import START_YEAR, count_by, empty_row, single_cohort
from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    CohortTrials,
    Dimension,
    Intent,
    RowShape,
)


@dataclass(frozen=True)
class TimeTrendAggregator:
    @property
    def intent(self) -> Intent:
        return Intent.TIME_TREND

    @property
    def dimension(self) -> Dimension:
        return Dimension.START_YEAR

    @property
    def shape(self) -> RowShape:
        return RowShape.TEMPORAL

    @property
    def columns(self) -> tuple[str, ...]:
        return (START_YEAR.column,)

    @property
    def excerpt_fields(self) -> tuple[str, ...]:
        return START_YEAR.excerpt_fields

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> Aggregation:
        cohort = single_cohort(cohorts)
        categorized = START_YEAR.assign(cohort.batch.trials)
        buckets = count_by(categorized)
        years = [key for key in buckets if isinstance(key, int)]
        stated = cohort.filters
        first = stated.start_year if stated.start_year is not None else min(years, default=None)
        last = stated.end_year if stated.end_year is not None else max(years, default=None)
        if first is None or last is None:
            return Aggregation((), dict(categorized.excluded))
        column = START_YEAR.column
        rows = tuple(
            buckets[year].row({column: year}) if year in buckets else empty_row({column: year})
            for year in range(first, last + 1)
        )
        return Aggregation(rows, dict(categorized.excluded))


REGISTRY.register(TimeTrendAggregator())
