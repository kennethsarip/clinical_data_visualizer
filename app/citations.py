"""Builds {nct_id, excerpt, field} per row, node and edge from cached records only (§7.5).

Aggregators record, for every trial in a row, the record value that put it there (its evidence),
taken from records normalized out of the cache; the LLM never touches it (§7.2). This module only
orders, caps and formats that evidence. The excerpt check (`checks.py`) then verifies each excerpt
against the raw cached record, so a citation is never trusted just because it was built here.
"""

from collections.abc import Iterable

from app.aggregators.registry import AggRow
from app.normalize import NormalizedTrial
from app.schemas import Citation, Provenance, TrialSummary
from app.vocab import label

# Trials cited per row (decided 2026-10-04): every row keeps all its `nct_ids`, so the cap only
# bounds response size. It is disclosed as `meta.citation_cap`.
CITATION_CAP = 25


class CitationError(ValueError):
    """Evidence and provenance disagree: an aggregator or pipeline bug, never user input."""


def provenance(row: AggRow, cap: int = CITATION_CAP) -> Provenance:
    """A row's `trial_count`, `nct_ids` and `citations` (SCHEMAS.md §2)."""
    missing = row.nct_ids - row.evidence.keys()
    if missing:
        raise CitationError(f"no evidence for {sorted(missing)} in row {dict(row.values)}")
    # Descending NCT ID is newest registration first, a stable and meaningful choice of which
    # trials to cite when the cap applies.
    nct_ids = sorted(row.nct_ids, reverse=True)
    citations = [
        Citation(nct_id=nct_id, excerpt=evidence.excerpt, field=evidence.field)
        for nct_id in nct_ids[:cap]
        for evidence in row.evidence[nct_id]
    ]
    return Provenance(trial_count=len(nct_ids), nct_ids=nct_ids, citations=citations)


def trial_summaries(
    trials: Iterable[NormalizedTrial], nct_ids: Iterable[str]
) -> dict[str, TrialSummary]:
    """The `trials` lookup: one summary per NCT ID behind the chart, so a sources panel can list
    titles without a second request."""
    by_id = {t.nct_id: t for t in trials}
    wanted = sorted(set(nct_ids), reverse=True)
    unknown = [n for n in wanted if n not in by_id]
    if unknown:
        raise CitationError(f"{unknown} are not in the retrieved records")
    return {n: _summary(by_id[n]) for n in wanted}


def _summary(trial: NormalizedTrial) -> TrialSummary:
    return TrialSummary(
        brief_title=trial.brief_title,
        official_title=trial.official_title,
        overall_status=label(trial.overall_status),
        phase=trial.phase_label,
        start_date=trial.start_date,
        sponsor_name=trial.sponsor_name,
        conditions=list(trial.conditions),
    )
