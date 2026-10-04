"""Single source of API enums and display labels (CLAUDE.md §8.4).

Enum values mirror `GET /studies/enums` (verified 2026-10-04, apiVersion 2.0.5). Display labels
are the API's own `legacyValue` strings, except AgencyClass, whose legacy values are just the
codes, so its labels are ours. No other module defines labels.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum


class Phase(StrEnum):
    NA = "NA"
    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"


class Status(StrEnum):
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    COMPLETED = "COMPLETED"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"
    AVAILABLE = "AVAILABLE"
    NO_LONGER_AVAILABLE = "NO_LONGER_AVAILABLE"
    TEMPORARILY_NOT_AVAILABLE = "TEMPORARILY_NOT_AVAILABLE"
    APPROVED_FOR_MARKETING = "APPROVED_FOR_MARKETING"
    WITHHELD = "WITHHELD"
    UNKNOWN = "UNKNOWN"


class InterventionType(StrEnum):
    BEHAVIORAL = "BEHAVIORAL"
    BIOLOGICAL = "BIOLOGICAL"
    COMBINATION_PRODUCT = "COMBINATION_PRODUCT"
    DEVICE = "DEVICE"
    DIAGNOSTIC_TEST = "DIAGNOSTIC_TEST"
    DIETARY_SUPPLEMENT = "DIETARY_SUPPLEMENT"
    DRUG = "DRUG"
    GENETIC = "GENETIC"
    PROCEDURE = "PROCEDURE"
    RADIATION = "RADIATION"
    OTHER = "OTHER"


class AgencyClass(StrEnum):
    NIH = "NIH"
    FED = "FED"
    OTHER_GOV = "OTHER_GOV"
    INDIV = "INDIV"
    INDUSTRY = "INDUSTRY"
    NETWORK = "NETWORK"
    AMBIG = "AMBIG"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class StudyType(StrEnum):
    EXPANDED_ACCESS = "EXPANDED_ACCESS"
    INTERVENTIONAL = "INTERVENTIONAL"
    OBSERVATIONAL = "OBSERVATIONAL"


PHASE_LABELS: Mapping[StrEnum, str] = {
    Phase.NA: "Not Applicable",
    Phase.EARLY_PHASE1: "Early Phase 1",
    Phase.PHASE1: "Phase 1",
    Phase.PHASE2: "Phase 2",
    Phase.PHASE3: "Phase 3",
    Phase.PHASE4: "Phase 4",
}

STATUS_LABELS: Mapping[StrEnum, str] = {
    Status.ACTIVE_NOT_RECRUITING: "Active, not recruiting",
    Status.COMPLETED: "Completed",
    Status.ENROLLING_BY_INVITATION: "Enrolling by invitation",
    Status.NOT_YET_RECRUITING: "Not yet recruiting",
    Status.RECRUITING: "Recruiting",
    Status.SUSPENDED: "Suspended",
    Status.TERMINATED: "Terminated",
    Status.WITHDRAWN: "Withdrawn",
    Status.AVAILABLE: "Available",
    Status.NO_LONGER_AVAILABLE: "No longer available",
    Status.TEMPORARILY_NOT_AVAILABLE: "Temporarily not available",
    Status.APPROVED_FOR_MARKETING: "Approved for marketing",
    Status.WITHHELD: "Withheld",
    Status.UNKNOWN: "Unknown status",
}

INTERVENTION_TYPE_LABELS: Mapping[StrEnum, str] = {
    InterventionType.BEHAVIORAL: "Behavioral",
    InterventionType.BIOLOGICAL: "Biological",
    InterventionType.COMBINATION_PRODUCT: "Combination Product",
    InterventionType.DEVICE: "Device",
    InterventionType.DIAGNOSTIC_TEST: "Diagnostic Test",
    InterventionType.DIETARY_SUPPLEMENT: "Dietary Supplement",
    InterventionType.DRUG: "Drug",
    InterventionType.GENETIC: "Genetic",
    InterventionType.PROCEDURE: "Procedure",
    InterventionType.RADIATION: "Radiation",
    InterventionType.OTHER: "Other",
}

AGENCY_CLASS_LABELS: Mapping[StrEnum, str] = {
    AgencyClass.NIH: "NIH",
    AgencyClass.FED: "U.S. Federal",
    AgencyClass.OTHER_GOV: "Other Government",
    AgencyClass.INDIV: "Individual",
    AgencyClass.INDUSTRY: "Industry",
    AgencyClass.NETWORK: "Network",
    AgencyClass.AMBIG: "Ambiguous",
    AgencyClass.OTHER: "Other",
    AgencyClass.UNKNOWN: "Unknown",
}

STUDY_TYPE_LABELS: Mapping[StrEnum, str] = {
    StudyType.EXPANDED_ACCESS: "Expanded Access",
    StudyType.INTERVENTIONAL: "Interventional",
    StudyType.OBSERVATIONAL: "Observational",
}

# Keyed by enum class: StrEnum members hash as their string value, so Status.UNKNOWN and
# AgencyClass.UNKNOWN would collide in one flat dict.
_LABELS_BY_ENUM: Mapping[type[StrEnum], Mapping[StrEnum, str]] = {
    Phase: PHASE_LABELS,
    Status: STATUS_LABELS,
    InterventionType: INTERVENTION_TYPE_LABELS,
    AgencyClass: AGENCY_CLASS_LABELS,
    StudyType: STUDY_TYPE_LABELS,
}

# Counting-rule label for a record with no phase (CLAUDE.md §14 Phase 1).
PHASE_NOT_SPECIFIED = "Not specified"


def label(value: StrEnum) -> str:
    """Display label for any vocab enum member."""
    return _LABELS_BY_ENUM[type(value)][value]


def phase_label(phases: Iterable[Phase]) -> str:
    """One category per phase combination, e.g. "Phase 1/Phase 2", so phase sums reconcile."""
    distinct = set(phases)
    if not distinct:
        return PHASE_NOT_SPECIFIED
    ordered = [phase for phase in Phase if phase in distinct]
    return "/".join(PHASE_LABELS[phase] for phase in ordered)
