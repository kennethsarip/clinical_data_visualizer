from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas import FILTER_TEXT_MAX_LENGTH, RetrievalFilters, VisualizeRequest
from app.vocab import COUNTRIES, Phase, Status

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


# country is a registry name instead (below), so no length cap applies to it.
@pytest.mark.parametrize("field", ["drug_name", "condition", "sponsor"])
def test_text_filters_are_capped_at_200_characters(field: str) -> None:
    assert FILTER_TEXT_MAX_LENGTH == 200
    RetrievalFilters.model_validate({field: "x" * 200})
    with pytest.raises(ValidationError):
        RetrievalFilters.model_validate({field: "x" * 201})


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


# --- country is a registry name (CLAUDE.md §14 Phase 6 step 2) ---


# A request also needs its query; the plan's filters do not.
COUNTRY_MODELS: list[tuple[type[BaseModel], dict[str, str]]] = [
    (RetrievalFilters, {}),
    (VisualizeRequest, {"query": "q"}),
]


@pytest.mark.parametrize("model,extra", COUNTRY_MODELS)
def test_country_is_stored_as_its_registry_name(
    model: type[BaseModel], extra: dict[str, str]
) -> None:
    parsed = model.model_validate({"country": "south korea", **extra})
    assert parsed.model_dump()["country"] == "South Korea"


@pytest.mark.parametrize("model,extra", COUNTRY_MODELS)
def test_a_country_outside_the_registry_is_rejected(
    model: type[BaseModel], extra: dict[str, str]
) -> None:
    with pytest.raises(ValidationError, match="not a ClinicalTrials.gov country name"):
        model.model_validate({"country": "Korea", **extra})


def test_country_schema_lists_every_registry_name() -> None:
    schema = VisualizeRequest.model_json_schema()["properties"]["country"]
    enums = [option["enum"] for option in schema["anyOf"] if "enum" in option]
    assert enums == [list(COUNTRIES)]
