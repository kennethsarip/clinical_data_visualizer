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


class EnrollmentType(StrEnum):
    ACTUAL = "ACTUAL"
    ESTIMATED = "ESTIMATED"


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

ENROLLMENT_TYPE_LABELS: Mapping[StrEnum, str] = {
    EnrollmentType.ACTUAL: "Actual",
    EnrollmentType.ESTIMATED: "Estimated",
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
    EnrollmentType: ENROLLMENT_TYPE_LABELS,
    StudyType: STUDY_TYPE_LABELS,
}

# Counting-rule label for a record with no phase (CLAUDE.md §6).
PHASE_NOT_SPECIFIED = "Not specified"

# Series label for a record whose enrollment count has no ACTUAL/ESTIMATED type (CLAUDE.md §6).
ENROLLMENT_TYPE_NOT_REPORTED = "Type not reported"


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


# Every LocationCountry value in the registry (`GET /stats/field/values?fields=LocationCountry`,
# 226 names, fetched 2026-10-05; a live test keeps the two in step). Records spell a site's country
# exactly this way, so a country filter can be checked by equality (§8.4).
COUNTRIES: tuple[str, ...] = (
    "Afghanistan",
    "Aland Islands",
    "Albania",
    "Algeria",
    "American Samoa",
    "Andorra",
    "Angola",
    "Anguilla",
    "Antarctica",
    "Antigua and Barbuda",
    "Argentina",
    "Armenia",
    "Aruba",
    "Australia",
    "Austria",
    "Azerbaijan",
    "Bahrain",
    "Bangladesh",
    "Barbados",
    "Belarus",
    "Belgium",
    "Belize",
    "Benin",
    "Bermuda",
    "Bhutan",
    "Bolivia",
    "Bonaire, Saint Eustatius and Saba ",
    "Bosnia and Herzegovina",
    "Botswana",
    "Brazil",
    "Brunei",
    "Bulgaria",
    "Burkina Faso",
    "Burma",
    "Burundi",
    "Cabo Verde",
    "Cambodia",
    "Cameroon",
    "Canada",
    "Cayman Islands",
    "Central African Republic",
    "Chad",
    "Chile",
    "China",
    "Christmas Island",
    "Colombia",
    "Comoros",
    "Costa Rica",
    "Croatia",
    "Cuba",
    "Curacao",
    "Cyprus",
    "Czechia",
    "C\u00f4te d\u2019Ivoire",
    "Democratic Republic of the Congo",
    "Denmark",
    "Djibouti",
    "Dominica",
    "Dominican Republic",
    "Ecuador",
    "Egypt",
    "El Salvador",
    "Equatorial Guinea",
    "Eritrea",
    "Estonia",
    "Eswatini",
    "Ethiopia",
    "Faroe Islands",
    "Federal Republic of Yugoslavia",
    "Fiji",
    "Finland",
    "France",
    "French Guiana",
    "French Polynesia",
    "French Southern and Antarctic Lands",
    "Gabon",
    "Georgia",
    "Germany",
    "Ghana",
    "Gibraltar",
    "Greece",
    "Greenland",
    "Grenada",
    "Guadeloupe",
    "Guam",
    "Guatemala",
    "Guinea",
    "Guinea-Bissau",
    "Guyana",
    "Haiti",
    "Holy See",
    "Honduras",
    "Hong Kong",
    "Hungary",
    "Iceland",
    "India",
    "Indonesia",
    "Iran",
    "Iraq",
    "Ireland",
    "Israel",
    "Italy",
    "Jamaica",
    "Japan",
    "Jersey",
    "Jordan",
    "Kazakhstan",
    "Kenya",
    "Kiribati",
    "Kosovo",
    "Kuwait",
    "Kyrgyzstan",
    "Laos",
    "Latvia",
    "Lebanon",
    "Lesotho",
    "Liberia",
    "Libya",
    "Liechtenstein",
    "Lithuania",
    "Luxembourg",
    "Macau",
    "Madagascar",
    "Malawi",
    "Malaysia",
    "Maldives",
    "Mali",
    "Malta",
    "Martinique",
    "Mauritania",
    "Mauritius",
    "Mayotte",
    "Mexico",
    "Micronesia",
    "Moldova",
    "Monaco",
    "Mongolia",
    "Montenegro",
    "Montserrat",
    "Morocco",
    "Mozambique",
    "Namibia",
    "Nepal",
    "Netherlands",
    "Netherlands Antilles",
    "New Caledonia",
    "New Zealand",
    "Nicaragua",
    "Niger",
    "Nigeria",
    "Niue",
    "North Korea",
    "North Macedonia",
    "Northern Mariana Islands",
    "Norway",
    "Oman",
    "Pakistan",
    "Palestinian Territories",
    "Panama",
    "Papua New Guinea",
    "Paraguay",
    "Peru",
    "Philippines",
    "Poland",
    "Portugal",
    "Puerto Rico",
    "Qatar",
    "Republic of the Congo",
    "Reunion",
    "Romania",
    "Russia",
    "Rwanda",
    "Saint Kitts and Nevis",
    "Saint Lucia",
    "Saint Martin",
    "Saint Vincent and the Grenadines",
    "Samoa",
    "San Marino",
    "Saudi Arabia",
    "Senegal",
    "Serbia",
    "Serbia and Montenegro",
    "Seychelles",
    "Sierra Leone",
    "Singapore",
    "Slovakia",
    "Slovenia",
    "Solomon Islands",
    "Somalia",
    "South Africa",
    "South Korea",
    "South Sudan",
    "Spain",
    "Sri Lanka",
    "Sudan",
    "Suriname",
    "Sweden",
    "Switzerland",
    "Syria",
    "Taiwan",
    "Tajikistan",
    "Tanzania",
    "Thailand",
    "The Bahamas",
    "The Gambia",
    "Timor-Leste",
    "Togo",
    "Trinidad and Tobago",
    "Tunisia",
    "Turkey (T\u00fcrkiye)",
    "Turkmenistan",
    "Uganda",
    "Ukraine",
    "United Arab Emirates",
    "United Kingdom",
    "United States",
    "United States Minor Outlying Islands",
    "Uruguay",
    "Uzbekistan",
    "Vanuatu",
    "Venezuela",
    "Vietnam",
    "Virgin Islands",
    "Yemen",
    "Zambia",
    "Zimbabwe",
)
_COUNTRY_BY_FOLDED = {name.casefold(): name for name in COUNTRIES}


def canonical_country(name: str) -> str:
    """The registry spelling of `name`, ignoring case and surrounding space. A variant ("Korea",
    "USA") is rejected rather than guessed: the planner maps it and discloses the mapping."""
    canonical = _COUNTRY_BY_FOLDED.get(name.strip().casefold())
    if canonical is None:
        raise ValueError(f"{name!r} is not a ClinicalTrials.gov country name")
    return canonical
