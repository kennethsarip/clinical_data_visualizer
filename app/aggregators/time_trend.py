"""Trials started per year, zero-filled (§1, §7.4).

A year with no trials is information, so gap years get a zero row. The range spans the stated
years and every trial's year, so a stated range widens the zero-fill but never drops a trial.
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
        stated = cohort.filters
        years = [key for key in buckets if isinstance(key, int)]
        bounds = [*years, *(y for y in (stated.start_year, stated.end_year) if y is not None)]
        if not years:
            return Aggregation((), dict(categorized.excluded))
        first, last = min(bounds), max(bounds)
        column = START_YEAR.column
        rows = tuple(
            buckets[year].row({column: year}) if year in buckets else empty_row({column: year})
            for year in range(first, last + 1)
        )
        return Aggregation(rows, dict(categorized.excluded))


REGISTRY.register(TimeTrendAggregator())
