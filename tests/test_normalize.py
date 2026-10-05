"""Counting rules (CLAUDE.md §6) on synthetic records shaped like the live-data evidence.

Expected values are written by hand from §6 and the API record shape, not copied from output.
"""

from copy import deepcopy
from typing import Any

import pytest

from app.normalize import (
    Gap,
    Intervention,
    RecordShapeError,
    UnreadableRecord,
    normalize_record,
    normalize_records,
)
from app.vocab import AgencyClass, EnrollmentType, InterventionType, Phase, Status, StudyType


def _record(**overrides: Any) -> dict[str, Any]:
    """A complete record; each override replaces one module of protocolSection."""
    section: dict[str, Any] = {
        "identificationModule": {"nctId": "NCT00000001", "briefTitle": "A trial"},
        "statusModule": {"overallStatus": "COMPLETED", "startDateStruct": {"date": "2016-03-15"}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Merck", "class": "INDUSTRY"}},
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE3"],
            "enrollmentInfo": {"count": 120, "type": "ACTUAL"},
        },
        "armsInterventionsModule": {"interventions": [{"type": "DRUG", "name": "Pembrolizumab"}]},
        "conditionsModule": {"conditions": ["Melanoma"]},
        "contactsLocationsModule": {"locations": [{"country": "United States"}]},
    }
    section.update(overrides)
    return {"protocolSection": section}


def _design(**fields: Any) -> dict[str, Any]:
    design: dict[str, Any] = {"studyType": "INTERVENTIONAL"}
    design.update(fields)
    return design


def _status(date: str | None) -> dict[str, Any]:
    status: dict[str, Any] = {"overallStatus": "COMPLETED"}
    if date is not None:
        status["startDateStruct"] = {"date": date}
    return status


# --- field mapping ---


def test_complete_record_maps_every_field() -> None:
    trial = normalize_record(_record())
    assert trial.nct_id == "NCT00000001"
    assert trial.brief_title == "A trial"
    assert trial.phases == (Phase.PHASE3,)
    assert trial.overall_status is Status.COMPLETED
    assert (trial.start_date, trial.start_year) == ("2016-03-15", 2016)
    assert (trial.sponsor_name, trial.sponsor_class) == ("Merck", AgencyClass.INDUSTRY)
    assert trial.interventions == (Intervention(type=InterventionType.DRUG, name="Pembrolizumab"),)
    assert trial.conditions == ("Melanoma",)
    assert trial.countries == ("United States",)
    assert (trial.enrollment, trial.enrollment_type) == (120, EnrollmentType.ACTUAL)
    assert trial.study_type is StudyType.INTERVENTIONAL
    assert trial.gaps == frozenset()


# --- phases: one category per combination ---


@pytest.mark.parametrize(
    ("phases", "label"),
    [
        (["PHASE1", "PHASE2"], "Phase 1/Phase 2"),
        (["PHASE2", "PHASE3"], "Phase 2/Phase 3"),
        (["NA"], "Not Applicable"),
        ([], "Not specified"),
        (None, "Not specified"),
    ],
)
def test_phase_category(phases: list[str] | None, label: str) -> None:
    design = _design() if phases is None else _design(phases=phases)
    assert normalize_record(_record(designModule=design)).phase_label == label


def test_a_record_with_no_phase_is_kept_not_dropped() -> None:
    batch = normalize_records([_record(designModule=_design())])
    assert len(batch.trials) == 1
    assert batch.trials[0].phases == ()


# --- start date ---


def test_month_precision_start_date_keeps_its_year() -> None:
    trial = normalize_record(_record(statusModule=_status("2015-07")))
    assert (trial.start_date, trial.start_year) == ("2015-07", 2015)


def test_missing_start_date_is_a_gap() -> None:
    trial = normalize_record(_record(statusModule=_status(None)))
    assert (trial.start_date, trial.start_year) == (None, None)
    assert Gap.MISSING_START_DATE in trial.gaps


@pytest.mark.parametrize("date", ["2015", "2015/07/01", "July 2015"])
def test_unexpected_start_date_format_raises(date: str) -> None:
    with pytest.raises(RecordShapeError, match="NCT00000001.*start date"):
        normalize_record(_record(statusModule=_status(date)))


# --- enrollment ---


def test_missing_enrollment_is_a_gap() -> None:
    trial = normalize_record(_record(designModule=_design(phases=["PHASE3"])))
    assert trial.enrollment is None
    assert Gap.MISSING_ENROLLMENT in trial.gaps


def test_zero_enrollment_is_data_not_a_gap() -> None:
    trial = normalize_record(_record(designModule=_design(enrollmentInfo={"count": 0})))
    assert trial.enrollment == 0
    assert Gap.MISSING_ENROLLMENT not in trial.gaps


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        ({"count": 300, "type": "ESTIMATED"}, (300, EnrollmentType.ESTIMATED)),
        ({"count": 300}, (300, None)),  # live records sometimes omit the type
    ],
)
def test_enrollment_type(info: dict[str, Any], expected: tuple[int, EnrollmentType | None]) -> None:
    trial = normalize_record(_record(designModule=_design(enrollmentInfo=info)))
    assert (trial.enrollment, trial.enrollment_type) == expected


def test_unknown_enrollment_type_is_unreadable() -> None:
    info = {"count": 300, "type": "ANTICIPATED"}
    with pytest.raises(RecordShapeError):
        normalize_record(_record(designModule=_design(enrollmentInfo=info)))


# --- countries: deduped per trial ---


def test_countries_dedupe_across_sites_and_sort() -> None:
    sites = [{"country": "United States"}, {"country": "Germany"}, {"country": "United States"}]
    trial = normalize_record(_record(contactsLocationsModule={"locations": sites}))
    assert trial.countries == ("Germany", "United States")


def test_no_locations_is_a_gap() -> None:
    trial = normalize_record(_record(contactsLocationsModule={}))
    assert trial.countries == ()
    assert Gap.NO_LOCATIONS in trial.gaps


# --- interventions: kept as registered ---


def test_same_drug_under_two_types_is_kept_verbatim() -> None:
    items = [{"type": "DRUG", "name": "Pembrolizumab"}, {"type": "BIOLOGICAL", "name": "MK-3475"}]
    trial = normalize_record(_record(armsInterventionsModule={"interventions": items}))
    assert trial.interventions == (
        Intervention(type=InterventionType.DRUG, name="Pembrolizumab"),
        Intervention(type=InterventionType.BIOLOGICAL, name="MK-3475"),
    )


def test_unnamed_intervention_is_kept_and_is_a_gap() -> None:
    items = [{"type": "DRUG"}]
    trial = normalize_record(_record(armsInterventionsModule={"interventions": items}))
    assert trial.interventions == (Intervention(type=InterventionType.DRUG, name=None),)
    assert Gap.UNNAMED_INTERVENTION in trial.gaps


def test_no_interventions_is_a_gap() -> None:
    trial = normalize_record(_record(armsInterventionsModule={}))
    assert trial.interventions == ()
    assert Gap.NO_INTERVENTIONS in trial.gaps


# --- batch counts ---


def test_batch_counts_each_gap_and_keeps_every_readable_record() -> None:
    records = [
        _record(),  # no gaps
        _record(statusModule=_status(None), contactsLocationsModule={}),
        _record(statusModule=_status(None), designModule=_design()),
        _record(armsInterventionsModule={}),
    ]
    batch = normalize_records(records)
    assert len(batch.trials) == 4
    assert batch.gap_counts == {
        Gap.MISSING_START_DATE: 2,
        Gap.MISSING_ENROLLMENT: 1,
        Gap.NO_LOCATIONS: 1,
        Gap.NO_INTERVENTIONS: 1,
        Gap.UNNAMED_INTERVENTION: 0,
    }


# --- shape changes fail loudly ---


@pytest.mark.parametrize(
    ("module", "path"),
    [
        ("identificationModule", "briefTitle"),
        ("statusModule", "overallStatus"),
        ("designModule", "studyType"),
    ],
)
def test_missing_always_present_field_raises(module: str, path: str) -> None:
    record = _record()
    del record["protocolSection"][module][path]
    with pytest.raises(RecordShapeError, match="NCT00000001"):
        normalize_record(record)


def test_missing_lead_sponsor_raises() -> None:
    with pytest.raises(RecordShapeError, match="sponsor_name"):
        normalize_record(_record(sponsorCollaboratorsModule={}))


@pytest.mark.parametrize(
    ("module", "value"),
    [
        ("designModule", _design(phases=["PHASE5"])),
        ("statusModule", {"overallStatus": "OPEN"}),
        ("armsInterventionsModule", {"interventions": [{"type": "VACCINE", "name": "x"}]}),
    ],
)
def test_value_outside_the_api_enums_raises(module: str, value: dict[str, Any]) -> None:
    with pytest.raises(RecordShapeError):
        normalize_record(_record(**{module: value}))


def test_input_record_is_not_mutated() -> None:
    record = _record()
    snapshot = deepcopy(record)
    normalize_record(record)
    assert record == snapshot


# --- unreadable records: set aside up to 5% of a batch, else the batch fails ---


def _numbered(n: int) -> dict[str, Any]:
    return _record(identificationModule={"nctId": f"NCT{n:08d}", "briefTitle": "A trial"})


def _unreadable(n: int) -> dict[str, Any]:
    return _record(
        identificationModule={"nctId": f"NCT{n:08d}", "briefTitle": "A trial"},
        statusModule={"overallStatus": "OPEN"},  # not a Status value
    )


def test_all_readable_batch_sets_nothing_aside() -> None:
    assert normalize_records([_numbered(1), _numbered(2)]).unreadable == []


def test_one_in_twenty_is_set_aside_at_exactly_five_percent() -> None:
    records = [_numbered(n) for n in range(1, 20)] + [_unreadable(20)]
    batch = normalize_records(records)
    assert [t.nct_id for t in batch.trials] == [f"NCT{n:08d}" for n in range(1, 20)]
    assert [u.nct_id for u in batch.unreadable] == ["NCT00000020"]
    assert "overall_status" in batch.unreadable[0].reason


def test_two_in_twenty_fails_the_batch() -> None:
    records = [_numbered(n) for n in range(1, 19)] + [_unreadable(19), _unreadable(20)]
    with pytest.raises(RecordShapeError, match="2 of 20 records are unreadable"):
        normalize_records(records)


def test_a_lone_unreadable_record_fails_a_small_batch() -> None:
    # 1 of 10 is 10%: in a small batch one bad record is already a large share.
    records = [_numbered(n) for n in range(1, 10)] + [_unreadable(10)]
    with pytest.raises(RecordShapeError, match="1 of 10"):
        normalize_records(records)


def test_set_aside_records_are_not_in_the_gap_counts() -> None:
    no_dates = [_record(statusModule=_status(None)) for _ in range(19)]
    batch = normalize_records([*no_dates, _unreadable(99)])
    assert batch.gap_counts[Gap.MISSING_START_DATE] == 19


def test_unreadable_record_without_an_nct_id_is_reported_as_none() -> None:
    records = [_numbered(n) for n in range(1, 20)]
    records.append({"protocolSection": {}})
    batch = normalize_records(records)
    assert batch.unreadable == [UnreadableRecord(None, batch.unreadable[0].reason)]


def test_the_official_title_is_read_verbatim_and_may_be_absent() -> None:
    record = _record(
        identificationModule={
            "nctId": "NCT00000001",
            "briefTitle": "A trial",
            "officialTitle": "A Randomized, Double-Blind Study of X  in Y",
        }
    )
    assert normalize_record(record).official_title == "A Randomized, Double-Blind Study of X  in Y"
    assert normalize_record(_record()).official_title is None
