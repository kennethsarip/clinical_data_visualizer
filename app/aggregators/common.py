"""Shared building blocks: per-dimension categorizers and the one count-by-key helper (§7.4).

A categorizer says, for each trial, which categories it belongs to and the record values that put
it there (its evidence), and counts the trials a counting rule (§6) leaves out. Every chart
aggregator is a thin layer over `count_by`, so the counting itself exists exactly once.
"""

from collections.abc import Callable, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.aggregators.registry import (
    AggregationInputError,
    AggRow,
    CohortTrials,
    Dimension,
    Evidence,
)
from app.entities import (
    DrugMerge,
    condition_mentions,
    most_common_spelling,
    select_drugs,
    sponsor_mention,
)
from app.normalize import Gap, NormalizedTrial
from app.vocab import Phase, label, phase_label

# Record paths under protocolSection that excerpts quote (SCHEMAS.md §2).
F_PHASES = "designModule.phases"
F_STATUS = "statusModule.overallStatus"
F_START_DATE = "statusModule.startDateStruct.date"
F_COUNTRY = "contactsLocationsModule.locations.country"
F_INTERVENTION_TYPE = "armsInterventionsModule.interventions.type"
F_INTERVENTION_NAME = "armsInterventionsModule.interventions.name"
F_INTERVENTION_OTHER_NAMES = "armsInterventionsModule.interventions.otherNames"
F_SPONSOR = "sponsorCollaboratorsModule.leadSponsor.name"
F_SPONSOR_CLASS = "sponsorCollaboratorsModule.leadSponsor.class"
F_CONDITION = "conditionsModule.conditions"
F_ENROLLMENT = "designModule.enrollmentInfo.count"
F_ENROLLMENT_TYPE = "designModule.enrollmentInfo.type"

NO_CONDITIONS_RULE = "no conditions"

# Top-N bar charts keep this many categories and disclose the total (SCHEMAS.md §3.1).
TOP_N = 20

Value = str | int | bool | None


@dataclass(frozen=True)
class Assignment:
    """One trial placed in one category."""

    key: Hashable  # what rows group on
    label: Value  # a vote for the row's display value
    evidence: tuple[Evidence, ...]
    rank: tuple[int, ...] = ()  # canonical position; empty means "order by count"


@dataclass(frozen=True)
class Categorized:
    by_trial: Mapping[str, tuple[Assignment, ...]]  # nct_id -> categories; empty = left out
    excluded: Mapping[str, int]  # counting rule -> trials (non-zero only)
    merges: tuple[DrugMerge, ...] = ()  # synonyms merged into one drug (drug dimension only)


@dataclass
class Bucket:
    """One category's trials, accumulated by `count_by`."""

    key: Hashable
    rank: tuple[int, ...]
    nct_ids: set[str] = field(default_factory=set)
    evidence: dict[str, tuple[Evidence, ...]] = field(default_factory=dict)
    votes: list[Value] = field(default_factory=list)

    @property
    def label(self) -> Value:
        if all(isinstance(v, str) for v in self.votes):
            return most_common_spelling(str(v) for v in self.votes)
        return self.votes[0]

    def sort_key(self) -> tuple[object, ...]:
        # Canonical order when the dimension has one; otherwise count desc, then label.
        return self.rank if self.rank else (-len(self.nct_ids), str(self.label))

    def row(self, values: Mapping[str, Value]) -> AggRow:
        return AggRow(values=dict(values), nct_ids=frozenset(self.nct_ids), evidence=self.evidence)


def count_by(categorized: Categorized) -> dict[Hashable, Bucket]:
    """Group trials into buckets by assignment key: the one place trials are counted."""
    buckets: dict[Hashable, Bucket] = {}
    for nct_id, assignments in categorized.by_trial.items():
        for a in assignments:
            bucket = buckets.setdefault(a.key, Bucket(a.key, a.rank))
            if nct_id not in bucket.nct_ids:
                bucket.nct_ids.add(nct_id)
                bucket.evidence[nct_id] = a.evidence
                bucket.votes.append(a.label)
    return buckets


def ordered(buckets: Iterable[Bucket]) -> list[Bucket]:
    return sorted(buckets, key=Bucket.sort_key)


def empty_row(values: Mapping[str, Value]) -> AggRow:
    """A zero-filled row: a category or year with no trials is information, not missing data."""
    return AggRow(values=dict(values), nct_ids=frozenset(), evidence={})


def single_cohort(cohorts: Sequence[CohortTrials]) -> CohortTrials:
    if len(cohorts) != 1:
        raise AggregationInputError(f"expected one cohort, got {len(cohorts)}")
    return cohorts[0]


def nonzero(counts: Mapping[str, int]) -> dict[str, int]:
    return {rule: n for rule, n in counts.items() if n}


def gap_counts(trials: Sequence[NormalizedTrial], *gaps: Gap) -> dict[str, int]:
    return nonzero({str(gap): sum(gap in t.gaps for t in trials) for gap in gaps})


# --- categorizers ---


@dataclass(frozen=True)
class Categorizer:
    dimension: Dimension
    excerpt_fields: tuple[str, ...]
    # (trials to categorize, trials synonym evidence comes from: every cohort in a comparison)
    assign: Callable[[Sequence[NormalizedTrial], Sequence[NormalizedTrial]], Categorized]
    top_n: int | None = None

    def categorize(
        self, trials: Sequence[NormalizedTrial], universe: Sequence[NormalizedTrial] | None = None
    ) -> Categorized:
        return self.assign(trials, trials if universe is None else universe)

    @property
    def column(self) -> str:
        return str(self.dimension)


def _per_trial(
    trials: Sequence[NormalizedTrial], fn: Callable[[NormalizedTrial], Iterable[Assignment]]
) -> dict[str, tuple[Assignment, ...]]:
    return {t.nct_id: tuple(fn(t)) for t in trials}


_PHASE_INDEX = {phase: i for i, phase in enumerate(Phase)}


def _phase_rank(phases: tuple[Phase, ...]) -> tuple[int, ...]:
    # Early Phase 1 ... Phase 4, then Not Applicable, then Not specified (CLAUDE.md §6).
    if not phases:
        return (2,)
    if set(phases) == {Phase.NA}:
        return (1,)
    return (0, *sorted(_PHASE_INDEX[p] for p in phases))


def _assign_phase(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        ordered_phases = tuple(p for p in Phase if p in t.phases)
        evidence = tuple(Evidence(F_PHASES, str(p)) for p in ordered_phases) or (
            Evidence(F_PHASES, None),
        )
        name = phase_label(t.phases)
        yield Assignment(name, name, evidence, _phase_rank(ordered_phases))

    return Categorized(_per_trial(trials, one), {})


def _assign_status(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        status = t.overall_status
        yield Assignment(str(status), label(status), (Evidence(F_STATUS, str(status)),))

    return Categorized(_per_trial(trials, one), {})


def _assign_sponsor_class(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        cls = t.sponsor_class
        yield Assignment(str(cls), label(cls), (Evidence(F_SPONSOR_CLASS, str(cls)),))

    return Categorized(_per_trial(trials, one), {})


def _assign_intervention_type(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    # Unnamed interventions are left out (§6); the trial still counts through its named ones.
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        seen = set()
        for i in t.interventions:
            if i.name is not None and i.type not in seen:
                seen.add(i.type)
                yield Assignment(
                    str(i.type), label(i.type), (Evidence(F_INTERVENTION_TYPE, str(i.type)),)
                )

    excluded = gap_counts(trials, Gap.NO_INTERVENTIONS, Gap.UNNAMED_INTERVENTION)
    return Categorized(_per_trial(trials, one), excluded)


def _assign_country(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        for country in t.countries:  # already deduped per trial (§6)
            yield Assignment(country, country, (Evidence(F_COUNTRY, country),))

    return Categorized(_per_trial(trials, one), gap_counts(trials, Gap.NO_LOCATIONS))


def _assign_drug(
    trials: Sequence[NormalizedTrial], universe: Sequence[NormalizedTrial]
) -> Categorized:
    selection = select_drugs(trials, universe)
    by_trial = {
        nct_id: tuple(
            Assignment(m.key, m.label, (Evidence(F_INTERVENTION_NAME, m.raw),)) for m in mentions
        )
        for nct_id, mentions in selection.mentions.items()
    }
    excluded = nonzero(selection.excluded) | gap_counts(
        trials, Gap.NO_INTERVENTIONS, Gap.UNNAMED_INTERVENTION
    )
    return Categorized(by_trial, excluded, selection.merges)


def _assign_sponsor(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        m = sponsor_mention(t)
        yield Assignment(m.key, m.label, (Evidence(F_SPONSOR, m.raw),))

    return Categorized(_per_trial(trials, one), {})


def _assign_condition(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        for m in condition_mentions(t):
            yield Assignment(m.key, m.label, (Evidence(F_CONDITION, m.raw),))

    excluded = nonzero({NO_CONDITIONS_RULE: sum(not t.conditions for t in trials)})
    return Categorized(_per_trial(trials, one), excluded)


def _assign_start_year(
    trials: Sequence[NormalizedTrial], _universe: Sequence[NormalizedTrial]
) -> Categorized:
    def one(t: NormalizedTrial) -> Iterable[Assignment]:
        if t.start_year is not None and t.start_date is not None:
            evidence = (Evidence(F_START_DATE, t.start_date),)
            yield Assignment(t.start_year, t.start_year, evidence, (t.start_year,))

    return Categorized(_per_trial(trials, one), gap_counts(trials, Gap.MISSING_START_DATE))


PHASE = Categorizer(Dimension.PHASE, (F_PHASES,), _assign_phase)
OVERALL_STATUS = Categorizer(Dimension.OVERALL_STATUS, (F_STATUS,), _assign_status)
INTERVENTION_TYPE = Categorizer(
    Dimension.INTERVENTION_TYPE, (F_INTERVENTION_TYPE,), _assign_intervention_type
)
SPONSOR_CLASS = Categorizer(Dimension.SPONSOR_CLASS, (F_SPONSOR_CLASS,), _assign_sponsor_class)
COUNTRY = Categorizer(Dimension.COUNTRY, (F_COUNTRY,), _assign_country, TOP_N)
DRUG = Categorizer(Dimension.DRUG, (F_INTERVENTION_NAME,), _assign_drug, TOP_N)
SPONSOR = Categorizer(Dimension.SPONSOR, (F_SPONSOR,), _assign_sponsor, TOP_N)
CONDITION = Categorizer(Dimension.CONDITION, (F_CONDITION,), _assign_condition, TOP_N)
START_YEAR = Categorizer(Dimension.START_YEAR, (F_START_DATE,), _assign_start_year)

# The categorical dimensions a distribution or comparison can group on.
CATEGORICAL = (PHASE, OVERALL_STATUS, INTERVENTION_TYPE, SPONSOR_CLASS, DRUG, SPONSOR, CONDITION)
