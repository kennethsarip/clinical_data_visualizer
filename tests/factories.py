"""Small synthetic trials for aggregator and entity tests (CLAUDE.md §9: small, synthetic)."""

from typing import Any

from app.aggregators.registry import CohortTrials
from app.normalize import Gap, NormalizedBatch, NormalizedTrial
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
) -> CohortTrials:
    gaps = {gap: sum(gap in t.gaps for t in trials) for gap in Gap}
    return CohortTrials(label, NormalizedBatch(trials, gaps, []), filters or RetrievalFilters())


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
