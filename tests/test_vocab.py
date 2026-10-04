"""Expected values are copied from CLAUDE.md §8.4 (the verified `GET /studies/enums` output)."""

from enum import StrEnum

import pytest

from app.vocab import (
    PHASE_NOT_SPECIFIED,
    AgencyClass,
    InterventionType,
    Phase,
    Status,
    StudyType,
    label,
    phase_label,
)

SPEC_VALUES: dict[type[StrEnum], list[str]] = {
    Phase: ["NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"],
    Status: [
        "ACTIVE_NOT_RECRUITING",
        "COMPLETED",
        "ENROLLING_BY_INVITATION",
        "NOT_YET_RECRUITING",
        "RECRUITING",
        "SUSPENDED",
        "TERMINATED",
        "WITHDRAWN",
        "AVAILABLE",
        "NO_LONGER_AVAILABLE",
        "TEMPORARILY_NOT_AVAILABLE",
        "APPROVED_FOR_MARKETING",
        "WITHHELD",
        "UNKNOWN",
    ],
    InterventionType: [
        "BEHAVIORAL",
        "BIOLOGICAL",
        "COMBINATION_PRODUCT",
        "DEVICE",
        "DIAGNOSTIC_TEST",
        "DIETARY_SUPPLEMENT",
        "DRUG",
        "GENETIC",
        "PROCEDURE",
        "RADIATION",
        "OTHER",
    ],
    AgencyClass: [
        "NIH",
        "FED",
        "OTHER_GOV",
        "INDIV",
        "INDUSTRY",
        "NETWORK",
        "AMBIG",
        "OTHER",
        "UNKNOWN",
    ],
    StudyType: ["EXPANDED_ACCESS", "INTERVENTIONAL", "OBSERVATIONAL"],
}


@pytest.mark.parametrize("enum_cls", list(SPEC_VALUES))
def test_enum_values_match_spec(enum_cls: type[StrEnum]) -> None:
    assert [member.value for member in enum_cls] == SPEC_VALUES[enum_cls]


@pytest.mark.parametrize("enum_cls", list(SPEC_VALUES))
def test_every_member_has_a_nonempty_label(enum_cls: type[StrEnum]) -> None:
    for member in enum_cls:
        assert label(member).strip()


def test_same_value_in_two_enums_keeps_its_own_label() -> None:
    assert label(Status.UNKNOWN) == "Unknown status"
    assert label(AgencyClass.UNKNOWN) == "Unknown"


def test_labels_match_api_legacy_values() -> None:
    assert label(Phase.PHASE1) == "Phase 1"
    assert label(Phase.NA) == "Not Applicable"
    assert label(Status.ACTIVE_NOT_RECRUITING) == "Active, not recruiting"


@pytest.mark.parametrize(
    ("phases", "expected"),
    [
        ([Phase.PHASE3], "Phase 3"),
        ([Phase.PHASE2, Phase.PHASE1], "Phase 1/Phase 2"),
        ([Phase.PHASE2, Phase.PHASE3, Phase.PHASE2], "Phase 2/Phase 3"),
        ([Phase.NA], "Not Applicable"),
        ([], PHASE_NOT_SPECIFIED),
    ],
)
def test_phase_label_combines_phases_in_order(phases: list[Phase], expected: str) -> None:
    assert phase_label(phases) == expected
