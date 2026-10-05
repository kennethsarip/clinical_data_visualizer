"""Retrieval conformance (CLAUDE.md §14 Phase 6 step 4): every charted trial meets each exact
filter sent, with the API's meaning (§8.4).

Phase, status, start-year and country filters are sent as exact API filters, so a record that
fails one means the API returned it anyway or a param maps to the wrong field (as `query.locn`
did: a text search that matched "Japan" in a Beijing hospital's name). Such a record is dropped
and counted in `meta.excluded`; over 5% of a batch means the mapping itself is wrong, and the
answer is `degraded` rather than a chart of the wrong trials. Entity filters (drug, condition,
sponsor) are searches by design (§7.3) and are not checked.
"""

from collections.abc import Callable

from app.normalize import NormalizedTrial
from app.schemas import FilterKey, RetrievalFilters

MAX_OFF_FILTER_SHARE = 0.05

# The exact filters, in the order a dropped trial is attributed to the first one it fails, and the
# words its `meta.excluded` rule uses.
FILTER_WORDS: dict[FilterKey, str] = {
    "trial_phase": "phase",
    "overall_status": "status",
    "start_year": "start year",
    "end_year": "end year",
    "country": "country",
}


class OffFilterBatchError(Exception):
    """Too many fetched records fail a filter that was sent: the param mapping is wrong."""


def off_filter_rule(key: FilterKey) -> str:
    return f"outside the {FILTER_WORDS[key]} filter"


def failed_filters(trial: NormalizedTrial, filters: RetrievalFilters) -> list[FilterKey]:
    """The exact filters `trial` does not meet, in FILTER_WORDS order. A trial with no start date
    cannot meet a year bound, as the API's date range never returns one."""
    year = trial.start_year
    meets: dict[FilterKey, Callable[[object], bool]] = {
        "trial_phase": lambda v: v in trial.phases,
        "overall_status": lambda v: trial.overall_status == v,
        "start_year": lambda v: year is not None and year >= int(str(v)),
        "end_year": lambda v: year is not None and year <= int(str(v)),
        "country": lambda v: v in trial.countries,
    }
    return [
        key
        for key in FILTER_WORDS
        if (value := getattr(filters, key)) is not None and not meets[key](value)
    ]


def conform(
    trials: list[NormalizedTrial], filters: RetrievalFilters
) -> tuple[list[NormalizedTrial], dict[str, frozenset[str]]]:
    """The trials meeting every exact filter, and the dropped ones per rule (each trial once,
    under the first filter it fails)."""
    kept: list[NormalizedTrial] = []
    dropped_ids: dict[str, set[str]] = {}
    for trial in trials:
        failed = failed_filters(trial, filters)
        if failed:
            dropped_ids.setdefault(off_filter_rule(failed[0]), set()).add(trial.nct_id)
        else:
            kept.append(trial)
    dropped = {rule: frozenset(ids) for rule, ids in dropped_ids.items()}
    off = len(trials) - len(kept)
    if off > MAX_OFF_FILTER_SHARE * len(trials):
        rules = ", ".join(f"{len(ids)} {rule}" for rule, ids in dropped.items())
        raise OffFilterBatchError(
            f"{off} of {len(trials)} fetched trials do not meet the filters sent ({rules}; over "
            f"{MAX_OFF_FILTER_SHARE:.0%}), so a filter probably maps to the wrong API param"
        )
    return kept, dropped
