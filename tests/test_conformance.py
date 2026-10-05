"""Retrieval conformance (CLAUDE.md §14 Phase 6 step 4): a fetched trial meets every exact filter
sent, read with the API's meaning (§8.4), or it is dropped and counted.

Expected outcomes are worked out by hand from each synthetic trial against that meaning: a phase
in the trial's list, its status, a start year inside the range, a site in the country.
"""

from typing import Any

import pytest

from app.conformance import MAX_OFF_FILTER_SHARE, OffFilterBatchError, conform, failed_filters
from app.schemas import RetrievalFilters
from tests.factories import make_trial

JAPAN = RetrievalFilters(condition="breast cancer", country="Japan")


def test_a_site_in_the_country_meets_the_country_filter() -> None:
    assert failed_filters(make_trial("NCT00000001", countries=["China", "Japan"]), JAPAN) == []


@pytest.mark.parametrize("countries", [["China"], []])
def test_no_site_in_the_country_fails_it(countries: list[str]) -> None:
    trial = make_trial("NCT00000001", countries=countries)
    assert failed_filters(trial, JAPAN) == ["country"]


def test_entity_filters_are_searches_and_never_checked() -> None:
    filters = RetrievalFilters(drug_name="x", condition="y", sponsor="z")
    assert failed_filters(make_trial("NCT00000001"), filters) == []


def test_phase_status_and_year_bounds() -> None:
    filters = RetrievalFilters(
        trial_phase="PHASE2", overall_status="RECRUITING", start_year=2015, end_year=2016
    )
    good: dict[str, Any] = {"phases": ["PHASE1", "PHASE2"], "overall_status": "RECRUITING"}
    assert failed_filters(make_trial("NCT00000001", start_date="2016-05", **good), filters) == []
    off = make_trial(
        "NCT00000002", phases=["PHASE3"], overall_status="COMPLETED", start_date="2017-01"
    )
    assert failed_filters(off, filters) == ["trial_phase", "overall_status", "end_year"]
    early = make_trial("NCT00000003", start_date="2014-12-31", **good)
    assert failed_filters(early, filters) == ["start_year"]
    undated = make_trial("NCT00000004", **good)
    assert failed_filters(undated, filters) == ["start_year", "end_year"]


def test_conform_drops_and_counts_each_trial_once_under_its_first_failed_filter() -> None:
    trials = [make_trial(f"NCT{n:08d}", countries=["Japan"]) for n in range(1, 41)]
    trials.append(make_trial("NCT00000041", countries=["China"]))
    kept, dropped = conform(trials, JAPAN)
    assert [t.nct_id for t in kept] == [t.nct_id for t in trials[:40]]
    assert dropped == {"outside the country filter": 1}


def test_conform_with_every_trial_meeting_the_filters_drops_nothing() -> None:
    trials = [make_trial("NCT00000001", countries=["Japan"])]
    assert conform(trials, JAPAN) == (trials, {})


def test_over_5_percent_off_filter_means_the_param_mapping_is_wrong() -> None:
    assert MAX_OFF_FILTER_SHARE == 0.05
    on = [make_trial(f"NCT{n:08d}", countries=["Japan"]) for n in range(1, 20)]
    conform([*on, make_trial("NCT00000020", countries=["China"])], JAPAN)  # 1 of 20: 5%
    two_off = [make_trial(f"NCT{n:08d}", countries=["China"]) for n in (20, 21)]
    with pytest.raises(OffFilterBatchError, match="2 of 21 .* country"):
        conform([*on, *two_off], JAPAN)
