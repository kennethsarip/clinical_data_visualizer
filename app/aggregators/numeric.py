"""Enrollment charts: a per-trial scatter and a fixed-bin histogram (§1, §6, §7.4).

Enrollment is the only numeric field (§6). Both charts split it by enrollment type, because an
estimated count (an ongoing trial's target) and an actual count must not be mixed unseen.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.aggregators.common import (
    F_ENROLLMENT,
    F_START_DATE,
    Assignment,
    Categorized,
    Value,
    count_by,
    empty_row,
    gap_counts,
    single_cohort,
)
from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    AggRow,
    CohortTrials,
    Dimension,
    Evidence,
    Intent,
    RowShape,
)
from app.normalize import Gap, NormalizedTrial
from app.vocab import ENROLLMENT_TYPE_NOT_REPORTED, EnrollmentType, label

# Half-open [start, end) bins; enrollment is heavily skewed, so equal-width bins would put almost
# every trial in the first one (decided 2026-10-04).
BINS: tuple[tuple[int, int | None, str], ...] = (
    (0, 1, "0"),
    (1, 10, "1-9"),
    (10, 50, "10-49"),
    (50, 100, "50-99"),
    (100, 250, "100-249"),
    (250, 500, "250-499"),
    (500, 1000, "500-999"),
    (1000, 5000, "1000-4999"),
    (5000, None, "5000+"),
)

# Series order: Actual, Estimated, then records that omit the type.
SERIES = (*(label(t) for t in EnrollmentType), ENROLLMENT_TYPE_NOT_REPORTED)


def _series(trial: NormalizedTrial) -> str:
    kind = trial.enrollment_type
    return label(kind) if kind is not None else ENROLLMENT_TYPE_NOT_REPORTED


def _bin_index(enrollment: int) -> int:
    return next(
        i
        for i, (lo, hi, _) in enumerate(BINS)
        if enrollment >= lo and (hi is None or enrollment < hi)
    )


@dataclass(frozen=True)
class EnrollmentScatterAggregator:
    @property
    def intent(self) -> Intent:
        return Intent.NUMERIC

    @property
    def dimension(self) -> Dimension:
        return Dimension.ENROLLMENT_BY_START_DATE

    @property
    def shape(self) -> RowShape:
        return RowShape.PER_TRIAL_NUMERIC

    @property
    def columns(self) -> tuple[str, ...]:
        return ("nct_id", "start_date", "enrollment", "enrollment_type")

    @property
    def excerpt_fields(self) -> tuple[str, ...]:
        return (F_ENROLLMENT, F_START_DATE)

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> Aggregation:
        trials = single_cohort(cohorts).batch.trials
        plotted = sorted(
            (t for t in trials if t.enrollment is not None and t.start_date is not None),
            key=lambda t: (t.start_date or "", t.nct_id),
        )
        rows = tuple(_point(t) for t in plotted)
        excluded = gap_counts(trials, Gap.MISSING_ENROLLMENT, Gap.MISSING_START_DATE)
        return Aggregation(rows, excluded)


def _point(trial: NormalizedTrial) -> AggRow:
    values = {
        "nct_id": trial.nct_id,
        "start_date": trial.start_date,
        "enrollment": trial.enrollment,
        "enrollment_type": _series(trial),
    }
    evidence = (
        Evidence(F_ENROLLMENT, str(trial.enrollment)),
        Evidence(F_START_DATE, trial.start_date),
    )
    return AggRow(values, frozenset({trial.nct_id}), {trial.nct_id: evidence})


@dataclass(frozen=True)
class EnrollmentHistogramAggregator:
    @property
    def intent(self) -> Intent:
        return Intent.NUMERIC

    @property
    def dimension(self) -> Dimension:
        return Dimension.ENROLLMENT

    @property
    def shape(self) -> RowShape:
        return RowShape.BINNED_NUMERIC

    @property
    def columns(self) -> tuple[str, ...]:
        return ("bin_label", "bin_start", "bin_end", "enrollment_type")

    @property
    def excerpt_fields(self) -> tuple[str, ...]:
        return (F_ENROLLMENT,)

    def aggregate(self, cohorts: Sequence[CohortTrials]) -> Aggregation:
        trials = single_cohort(cohorts).batch.trials

        def one(t: NormalizedTrial) -> Iterable[Assignment]:
            if t.enrollment is not None:
                evidence = (Evidence(F_ENROLLMENT, str(t.enrollment)),)
                yield Assignment((_bin_index(t.enrollment), _series(t)), _series(t), evidence)

        buckets = count_by(Categorized({t.nct_id: tuple(one(t)) for t in trials}, {}))
        seen = {_series(t) for t in trials if t.enrollment is not None}
        present = [s for s in SERIES if s in seen]
        rows = []
        for i, (lo, hi, name) in enumerate(BINS):
            for series in present:
                values: dict[str, Value] = {
                    "bin_label": name,
                    "bin_start": lo,
                    "bin_end": hi,
                    "enrollment_type": series,
                }
                bucket = buckets.get((i, series))
                rows.append(bucket.row(values) if bucket else empty_row(values))
        return Aggregation(tuple(rows), gap_counts(trials, Gap.MISSING_ENROLLMENT))


REGISTRY.register(EnrollmentScatterAggregator())
REGISTRY.register(EnrollmentHistogramAggregator())
