"""Record -> normalized trial, plus counts of the gaps the counting rules act on (CLAUDE.md §6).

Messy values are data: a record with gaps is kept, and the batch counts how many records have
each gap. The aggregators decide which gaps exclude a record from which chart and disclose those
counts in `meta.excluded`.

A record missing a field that live data always has (title, status, study type, lead sponsor), or
holding a value outside `vocab.py`, is unreadable: guessing would put it in the wrong bar. One odd
record should not cost the user the other 1,999, so an unreadable record is set aside, logged and
counted. Above `MAX_UNREADABLE_SHARE` the API format has probably changed, so the batch raises
rather than chart a skewed remainder.
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.vocab import AgencyClass, InterventionType, Phase, Status, StudyType, phase_label

logger = logging.getLogger(__name__)

# More unreadable records than this share of a batch fails it (user decision, 2026-10-04).
MAX_UNREADABLE_SHARE = 0.05

# The `meta.excluded` rule name for records set aside as unreadable.
UNREADABLE_RULE = "unreadable record"

# The two precisions the API uses (§6); anything else is a shape change, not a messy value.
_START_DATE = re.compile(r"^(\d{4})-\d{2}(-\d{2})?$")


class RecordShapeError(ValueError):
    """A record lacks a field the API always sends, or has a value outside the API enums."""


class Gap(StrEnum):
    """A missing value a counting rule acts on. Values are the `meta.excluded` rule names."""

    MISSING_START_DATE = "missing start date"
    MISSING_ENROLLMENT = "missing enrollment"
    NO_LOCATIONS = "no locations"
    NO_INTERVENTIONS = "no interventions"
    UNNAMED_INTERVENTION = "unnamed intervention"


class Intervention(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: InterventionType
    name: str | None  # free text as registered; a few live records omit it


class NormalizedTrial(BaseModel):
    model_config = ConfigDict(frozen=True)

    nct_id: Annotated[str, Field(pattern=r"^NCT\d{8}$")]
    brief_title: str
    phases: tuple[Phase, ...]
    overall_status: Status
    start_date: str | None  # verbatim, `YYYY-MM-DD` or `YYYY-MM`
    start_year: int | None
    sponsor_name: str
    sponsor_class: AgencyClass
    interventions: tuple[Intervention, ...]
    conditions: tuple[str, ...]
    countries: tuple[str, ...]  # deduped per trial and sorted, so output is deterministic
    enrollment: Annotated[int, Field(ge=0)] | None  # 0 is data (e.g. withdrawn), not missing
    study_type: StudyType

    @property
    def phase_label(self) -> str:
        """The phase category: "Phase 1/Phase 2" for multi-phase, "Not specified" for none."""
        return phase_label(self.phases)

    @property
    def gaps(self) -> frozenset[Gap]:
        found = {
            Gap.MISSING_START_DATE: self.start_date is None,
            Gap.MISSING_ENROLLMENT: self.enrollment is None,
            Gap.NO_LOCATIONS: not self.countries,
            Gap.NO_INTERVENTIONS: not self.interventions,
            Gap.UNNAMED_INTERVENTION: any(i.name is None for i in self.interventions),
        }
        return frozenset(gap for gap, present in found.items() if present)


@dataclass(frozen=True)
class UnreadableRecord:
    nct_id: str | None  # None when the record has no usable nctId
    reason: str


@dataclass(frozen=True)
class NormalizedBatch:
    trials: list[NormalizedTrial]  # every readable record, in input order
    gap_counts: dict[Gap, int]  # every Gap is a key, so a zero count is explicit
    unreadable: list[UnreadableRecord]  # disclosed in `meta.excluded` as UNREADABLE_RULE


def normalize_records(records: Iterable[dict[str, Any]]) -> NormalizedBatch:
    """Normalize every record, setting unreadable ones aside unless there are too many."""
    trials: list[NormalizedTrial] = []
    unreadable: list[UnreadableRecord] = []
    for record in records:
        try:
            trials.append(normalize_record(record))
        except RecordShapeError as exc:
            nct_id = _get(record, "protocolSection", "identificationModule", "nctId")
            skipped = UnreadableRecord(nct_id if isinstance(nct_id, str) else None, str(exc))
            logger.warning("Setting aside unreadable record %s: %s", skipped.nct_id, exc)
            unreadable.append(skipped)
    total = len(trials) + len(unreadable)
    if unreadable and len(unreadable) > MAX_UNREADABLE_SHARE * total:
        raise RecordShapeError(
            f"{len(unreadable)} of {total} records are unreadable (over "
            f"{MAX_UNREADABLE_SHARE:.0%}); the API format may have changed. "
            f"First: {unreadable[0].reason}"
        )
    counts = {gap: sum(gap in trial.gaps for trial in trials) for gap in Gap}
    return NormalizedBatch(trials, counts, unreadable)


def normalize_record(record: dict[str, Any]) -> NormalizedTrial:
    section = record.get("protocolSection", {})
    nct_id = _get(section, "identificationModule", "nctId")
    start_date = _get(section, "statusModule", "startDateStruct", "date")
    sponsor = _get(section, "sponsorCollaboratorsModule", "leadSponsor") or {}
    fields = {
        "nct_id": nct_id,
        "brief_title": _get(section, "identificationModule", "briefTitle"),
        "phases": _get(section, "designModule", "phases") or (),
        "overall_status": _get(section, "statusModule", "overallStatus"),
        "start_date": start_date,
        "start_year": _start_year(nct_id, start_date),
        "sponsor_name": sponsor.get("name"),
        "sponsor_class": sponsor.get("class"),
        "interventions": [
            {"type": item.get("type"), "name": item.get("name")}
            for item in _get(section, "armsInterventionsModule", "interventions") or ()
        ],
        "conditions": _get(section, "conditionsModule", "conditions") or (),
        "countries": _countries(_get(section, "contactsLocationsModule", "locations") or ()),
        "enrollment": _get(section, "designModule", "enrollmentInfo", "count"),
        "study_type": _get(section, "designModule", "studyType"),
    }
    try:
        return NormalizedTrial.model_validate(fields)
    except ValidationError as exc:
        raise RecordShapeError(f"Record {nct_id or '<no nctId>'}: {exc}") from exc


def _get(node: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _start_year(nct_id: Any, start_date: Any) -> int | None:
    if start_date is None:
        return None
    match = _START_DATE.match(start_date) if isinstance(start_date, str) else None
    if match is None:
        raise RecordShapeError(f"Record {nct_id}: unexpected start date {start_date!r}")
    return int(match.group(1))


def _countries(locations: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    # One location per site, so a country repeats across sites; a trial counts once per country.
    return tuple(sorted({loc["country"] for loc in locations if loc.get("country")}))
