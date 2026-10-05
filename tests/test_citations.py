"""Citations and the trial lookup (CLAUDE.md §7.5, SCHEMAS.md §2).

Expected values follow SCHEMAS.md: `nct_ids` sorted descending, citations for at most `cap`
trials (the first in `nct_ids`), every evidence entry of a cited trial kept, null excerpts kept.
"""

import pytest

from app.aggregators.registry import AggRow, Evidence
from app.citations import CITATION_CAP, CitationError, provenance, trial_summaries
from app.schemas import Citation, TrialSummary
from tests.factories import FIXTURE

PHASES = "designModule.phases"


def _row(evidence: dict[str, tuple[Evidence, ...]]) -> AggRow:
    return AggRow({"phase": "x"}, frozenset(evidence), evidence)


def test_nct_ids_sort_descending_and_count_matches() -> None:
    row = _row(
        {n: (Evidence(PHASES, "PHASE3"),) for n in ["NCT00000002", "NCT00000010", "NCT00000001"]}
    )
    result = provenance(row)
    assert result.nct_ids == ["NCT00000010", "NCT00000002", "NCT00000001"]
    assert result.trial_count == 3
    assert [c.nct_id for c in result.citations] == result.nct_ids


def test_cap_limits_cited_trials_not_nct_ids() -> None:
    ids = [f"NCT{i:08d}" for i in range(1, 31)]
    result = provenance(_row({n: (Evidence(PHASES, "PHASE3"),) for n in ids}))
    assert CITATION_CAP == 25
    assert result.trial_count == 30
    assert len(result.nct_ids) == 30
    # The 25 newest registrations: NCT00000030 down to NCT00000006.
    assert [c.nct_id for c in result.citations] == [f"NCT{i:08d}" for i in range(30, 5, -1)]


def test_cap_counts_trials_so_a_multi_evidence_trial_keeps_every_entry() -> None:
    two = (Evidence(PHASES, "PHASE1"), Evidence(PHASES, "PHASE2"))
    one = (Evidence(PHASES, "PHASE3"),)
    result = provenance(_row({"NCT00000002": two, "NCT00000001": one}), cap=1)
    assert result.citations == [
        Citation(nct_id="NCT00000002", excerpt="PHASE1", field=PHASES),
        Citation(nct_id="NCT00000002", excerpt="PHASE2", field=PHASES),
    ]


def test_absent_value_is_cited_as_a_null_excerpt() -> None:
    result = provenance(_row({"NCT00000003": (Evidence(PHASES, None),)}))
    assert result.citations == [Citation(nct_id="NCT00000003", excerpt=None, field=PHASES)]


def test_zero_filled_row_has_no_citations() -> None:
    result = provenance(AggRow({"start_year": 2016}, frozenset(), {}))
    assert (result.trial_count, result.nct_ids, result.citations) == (0, [], [])


def test_a_trial_without_evidence_is_a_bug_not_an_uncited_row() -> None:
    row = AggRow({"phase": "x"}, frozenset({"NCT00000001"}), {})
    with pytest.raises(CitationError, match="NCT00000001"):
        provenance(row)


# --- trial lookup ---


def test_trial_summaries_use_display_labels_and_registered_names() -> None:
    # Sponsor and conditions stay as registered, unnormalized: they label a source card.
    titled = FIXTURE[1].model_copy(update={"official_title": "A Phase 1/2 Study of MK-3475"})
    summaries = trial_summaries([titled, *FIXTURE[2:]], ["NCT00000002", "NCT00000003"])
    assert summaries == {
        "NCT00000002": TrialSummary(
            brief_title="Trial NCT00000002",
            official_title="A Phase 1/2 Study of MK-3475",  # verbatim (Phase 7 step 4)
            overall_status="Completed",
            phase="Phase 1/Phase 2",
            start_date="2017-06-01",
            sponsor_name="merck sharp & dohme llc",
            conditions=["melanoma", "Lung Cancer"],
        ),
        "NCT00000003": TrialSummary(
            brief_title="Trial NCT00000003",
            official_title=None,  # not every record registers one
            overall_status="Completed",
            phase="Not specified",
            start_date=None,
            sponsor_name="National Cancer Institute (NCI)",
            conditions=["Lung Cancer"],
        ),
    }


def test_trial_summaries_reject_an_id_outside_the_retrieved_set() -> None:
    # A cited trial must come from the records this request retrieved (CLAUDE.md §7.6).
    with pytest.raises(CitationError, match="NCT00000099"):
        trial_summaries(FIXTURE, ["NCT00000099"])
