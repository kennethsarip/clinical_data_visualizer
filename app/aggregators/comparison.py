"""Grouped bar charts: one categorical dimension across two or more cohorts (§1, §7.4).

Each cohort is its own API query (e.g. drug A, drug B). Every category appears for every cohort,
zero-filled, so bars align; categories are ordered as for one cohort, over the cohorts combined.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.aggregators.common import (
    CATEGORICAL,
    COUNTRY,
    Categorized,
    Categorizer,
    count_by,
    cut_by_top_n,
    empty_row,
    nonempty,
    ordered,
    top_n_rule,
)
from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    AggregationInputError,
    AggRow,
    CohortTrials,
    Dimension,
    Intent,
    RowShape,
)
from app.schemas import TopN

COHORT_COLUMN = "cohort"


@dataclass(frozen=True)
class ComparisonAggregator:
    categorizer: Categorizer

    @property
    def intent(self) -> Intent:
        return Intent.COMPARISON

    @property
    def dimension(self) -> Dimension:
        return self.categorizer.dimension

    @property
    def shape(self) -> RowShape:
        return RowShape.TWO_CATEGORICAL

    @property
    def columns(self) -> tuple[str, ...]:
        return (self.categorizer.column, COHORT_COLUMN)

    @property
    def excerpt_fields(self) -> tuple[str, ...]:
        return self.categorizer.excerpt_fields

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> Aggregation:
        labels = _cohort_labels(cohorts)
        per_cohort = [self.categorizer.assign(c.batch.trials) for c in cohorts]
        # A trial in two cohorts gets the same categories in both, so a merged view is consistent.
        combined = Categorized(
            {nct: a for cat in per_cohort for nct, a in cat.by_trial.items()}, {}
        )
        categories = ordered(count_by(combined).values())
        top_n = None
        if self.categorizer.top_n is not None:
            top_n = TopN(limit=self.categorizer.top_n, categories_total=len(categories))
            categories = categories[: self.categorizer.top_n]
        buckets = [count_by(cat) for cat in per_cohort]
        column = self.categorizer.column
        rows: list[AggRow] = []
        for category in categories:
            for label, cohort_buckets in zip(labels, buckets, strict=True):
                values = {column: category.label, COHORT_COLUMN: label}
                bucket = cohort_buckets.get(category.key)
                rows.append(bucket.row(values) if bucket else empty_row(values))
        excluded: dict[str, frozenset[str]] = {}
        for label, cat in zip(labels, per_cohort, strict=True):
            rules = dict(cat.excluded)
            if top_n is not None:
                rules[top_n_rule(top_n.limit)] = cut_by_top_n(cat, (c.key for c in categories))
            excluded |= {f"{rule} ({label})": ids for rule, ids in nonempty(rules).items()}
        return Aggregation(tuple(rows), excluded, top_n)


def _cohort_labels(cohorts: Sequence[CohortTrials]) -> list[str]:
    labels = [c.label for c in cohorts]
    if len(labels) < 2:
        raise AggregationInputError(f"a comparison needs at least two cohorts, got {len(labels)}")
    named = [label for label in labels if label is not None]
    if len(named) != len(labels) or len(set(named)) != len(named):
        raise AggregationInputError(f"comparison cohorts need distinct labels, got {labels}")
    return named


for _categorizer in (*CATEGORICAL, COUNTRY):
    REGISTRY.register(ComparisonAggregator(_categorizer))
