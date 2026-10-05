"""Distribution and geographic bar charts: one categorical dimension, one cohort (§1, §7.4)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.aggregators.common import (
    CATEGORICAL,
    COUNTRY,
    Categorizer,
    count_by,
    ordered,
    single_cohort,
)
from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    CohortTrials,
    Dimension,
    Intent,
    RowShape,
)
from app.schemas import TopN


@dataclass(frozen=True)
class CategoricalAggregator:
    intent: Intent
    categorizer: Categorizer

    @property
    def dimension(self) -> Dimension:
        return self.categorizer.dimension

    @property
    def shape(self) -> RowShape:
        return RowShape.CATEGORICAL

    @property
    def columns(self) -> tuple[str, ...]:
        return (self.categorizer.column,)

    @property
    def excerpt_fields(self) -> tuple[str, ...]:
        return self.categorizer.excerpt_fields

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> Aggregation:
        categorized = self.categorizer.categorize(single_cohort(cohorts).batch.trials)
        buckets = ordered(count_by(categorized).values())
        top_n = None
        if self.categorizer.top_n is not None:
            top_n = TopN(limit=self.categorizer.top_n, categories_total=len(buckets))
            buckets = buckets[: self.categorizer.top_n]
        column = self.categorizer.column
        rows = tuple(b.row({column: b.label}) for b in buckets)
        return Aggregation(rows, dict(categorized.excluded), top_n, categorized.merges)


for _categorizer in CATEGORICAL:
    REGISTRY.register(CategoricalAggregator(Intent.DISTRIBUTION, _categorizer))
REGISTRY.register(CategoricalAggregator(Intent.GEOGRAPHIC, COUNTRY))
