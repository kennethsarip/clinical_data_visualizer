"""Small synthetic trials for aggregator and entity tests (CLAUDE.md §9: small, synthetic)."""

from typing import Any

from app.aggregators.registry import CohortTrials
from app.normalize import Gap, NormalizedBatch, NormalizedTrial, UnreadableRecord
from app.schemas import RetrievalFilters

Interventions = list[tuple[str, str | None]]


def make_trial(
    nct_id: str, interventions: Interventions | None = None, **fields: Any
) -> NormalizedTrial:
    interventions = interventions or []
    defaults: dict[str, Any] = {
        "nct_id": nct_id,
        "brief_title": f"Trial {nct_id}",
        "phases": [],
        "overall_status": "COMPLETED",
        "start_date": None,
        "start_year": None,
        "sponsor_name": "Merck Sharp & Dohme LLC",
        "sponsor_class": "INDUSTRY",
        "interventions": [{"type": t, "name": n} for t, n in interventions],
        "conditions": [],
        "countries": [],
        "enrollment": None,
        "enrollment_type": None,
        "study_type": "INTERVENTIONAL",
    }
    if "start_date" in fields and "start_year" not in fields and fields["start_date"]:
        fields["start_year"] = int(fields["start_date"][:4])
    return NormalizedTrial.model_validate(defaults | fields)


def cohort(
    trials: list[NormalizedTrial],
    label: str | None = None,
    filters: RetrievalFilters | None = None,
    total: int | None = None,
    unreadable: int = 0,
) -> CohortTrials:
    gaps = {gap: sum(gap in t.gaps for t in trials) for gap in Gap}
    skipped = [UnreadableRecord(None, "synthetic") for _ in range(unreadable)]
    fetched = len(trials) + unreadable
    batch = NormalizedBatch(trials, gaps, skipped)
    return CohortTrials(
        label, batch, filters or RetrievalFilters(), fetched if total is None else total
    )


def raw_record(trial: NormalizedTrial) -> dict[str, Any]:
    """The API record a normalized trial came from, so checks can run against raw records."""
    design: dict[str, Any] = {"studyType": str(trial.study_type)}
    if trial.phases:
        design["phases"] = [str(p) for p in trial.phases]
    if trial.enrollment is not None:
        design["enrollmentInfo"] = {"count": trial.enrollment}
        if trial.enrollment_type is not None:
            design["enrollmentInfo"]["type"] = str(trial.enrollment_type)
    status: dict[str, Any] = {"overallStatus": str(trial.overall_status)}
    if trial.start_date is not None:
        status["startDateStruct"] = {"date": trial.start_date}
    section: dict[str, Any] = {
        "identificationModule": {"nctId": trial.nct_id, "briefTitle": trial.brief_title},
        "statusModule": status,
        "designModule": design,
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": trial.sponsor_name, "class": str(trial.sponsor_class)}
        },
        "conditionsModule": {"conditions": list(trial.conditions)},
    }
    if trial.interventions:
        section["armsInterventionsModule"] = {
            "interventions": [
                {"type": str(i.type)} | ({"name": i.name} if i.name is not None else {})
                for i in trial.interventions
            ]
        }
    if trial.countries:
        section["contactsLocationsModule"] = {
            "locations": [{"country": c} for c in trial.countries]
        }
    return {"protocolSection": section}


# The shared fixture. Every expected row in the aggregator tests is derived by hand from it.
T1 = make_trial(
    "NCT00000001",
    [("DRUG", "Pembrolizumab"), ("DRUG", "Placebo")],
    phases=["PHASE3"],
    overall_status="RECRUITING",
    start_date="2015-03",
    sponsor_name="Merck Sharp & Dohme LLC",
    conditions=["Melanoma"],
    countries=["Germany", "United States"],
    enrollment=120,
    enrollment_type="ACTUAL",
)
T2 = make_trial(
    "NCT00000002",
    [("BIOLOGICAL", "Pembrolizumab (MK-3475)"), ("DRUG", "Ipilimumab")],
    phases=["PHASE1", "PHASE2"],
    overall_status="COMPLETED",
    start_date="2017-06-01",
    sponsor_name="merck sharp & dohme llc",
    conditions=["melanoma", "Lung Cancer"],
    countries=["United States"],
    enrollment=48,
    enrollment_type="ESTIMATED",
)
T3 = make_trial(
    "NCT00000003",
    [("OTHER", "Laboratory Biomarker Analysis")],
    overall_status="COMPLETED",
    sponsor_name="National Cancer Institute (NCI)",
    sponsor_class="NIH",
    conditions=["Lung Cancer"],
)
T4 = make_trial(
    "NCT00000004",
    [("DRUG", "Nivolumab"), ("DRUG", "Ipilimumab")],
    phases=["PHASE3"],
    overall_status="RECRUITING",
    start_date="2017-01",
    sponsor_name="Bristol-Myers Squibb",
    conditions=["Melanoma"],
    countries=["France"],
    enrollment=0,
    enrollment_type="ACTUAL",
)
T5 = make_trial(
    "NCT00000005",
    [],
    phases=["NA"],
    overall_status="WITHDRAWN",
    start_date="2018-02",
    sponsor_name="Bristol-Myers Squibb",
    conditions=["Melanoma"],
    countries=["France", "Germany"],
    enrollment=5000,
)
FIXTURE = [T1, T2, T3, T4, T5]
