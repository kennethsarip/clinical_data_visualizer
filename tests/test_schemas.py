from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas import RetrievalFilters
from app.vocab import Phase, Status

# --- year range (CLAUDE.md §7.6: contradictory inputs are rejected) ---


def test_start_after_end_is_rejected() -> None:
    with pytest.raises(ValidationError, match="start_year \\(2020\\) is after end_year \\(2015\\)"):
        RetrievalFilters(start_year=2020, end_year=2015)


@pytest.mark.parametrize(
    "years",
    [
        {"start_year": 2015, "end_year": 2015},
        {"start_year": 2015, "end_year": 2024},
        {"start_year": 2015},
        {"end_year": 2015},
    ],
)
def test_ordered_or_open_ended_ranges_are_accepted(years: dict[str, int]) -> None:
    RetrievalFilters.model_validate(years)


# --- enums come from vocab.py (CLAUDE.md §8.4) ---


def test_phase_and_status_parse_from_api_codes() -> None:
    filters = RetrievalFilters.model_validate(
        {"trial_phase": "PHASE3", "overall_status": "RECRUITING"}
    )
    assert filters.trial_phase is Phase.PHASE3
    assert filters.overall_status is Status.RECRUITING


@pytest.mark.parametrize(
    "bad", [{"trial_phase": "Phase 3"}, {"trial_phase": "PHASE5"}, {"overall_status": "OPEN"}]
)
def test_values_outside_the_api_enums_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RetrievalFilters.model_validate(bad)


# --- text filters ---


def test_text_filters_are_stripped() -> None:
    filters = RetrievalFilters(drug_name="  Pembrolizumab ", country="Germany\n")
    assert filters.drug_name == "Pembrolizumab"
    assert filters.country == "Germany"


@pytest.mark.parametrize("field", ["drug_name", "condition", "sponsor", "country"])
@pytest.mark.parametrize("value", ["", "   "])
def test_blank_text_filters_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        RetrievalFilters.model_validate({field: value})


# --- shape ---


def test_no_filters_is_valid_and_all_none() -> None:
    # Whether an unfiltered plan is answerable is the clarification rule's call (Phase 3).
    assert RetrievalFilters().model_dump(exclude_none=True) == {}


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="drug"):
        RetrievalFilters.model_validate({"drug": "Pembrolizumab"})


def test_filters_are_immutable() -> None:
    filters = RetrievalFilters(drug_name="Pembrolizumab")
    with pytest.raises(ValidationError):
        filters.drug_name = "Nivolumab"  # type: ignore[misc]
