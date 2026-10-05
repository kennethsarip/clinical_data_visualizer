"""`meta.name_merges` and the `name merges` check (CLAUDE.md §14 Phase 8 step 5).

Two trials register RAD001 as an other name of everolimus and a third names RAD001 itself, so the
rule merges RAD001 into everolimus. Expected disclosures are derived by hand from that rule; each
failing case breaks one thing the check must catch.
"""

import copy
from typing import Any

from app.aggregators.registry import REGISTRY, Dimension, Intent
from app.checks import CheckContext, run_checks
from app.normalize import NormalizedTrial
from app.schemas import RESPONSE_ADAPTER, Citation, Filters, NameMerge, OkResponse, RetrievalFilters
from app.viz import assemble, default_title
from tests.factories import cohort, make_trial, raw_record

OTHER_NAMES = "armsInterventionsModule.interventions.otherNames"

EVEROLIMUS = [
    make_trial("NCT00000011", [("DRUG", "Everolimus", ["RAD001"]), ("DRUG", "Exemestane")]),
    make_trial("NCT00000012", [("DRUG", "Everolimus", ["RAD001"]), ("DRUG", "Exemestane")]),
    make_trial("NCT00000013", [("DRUG", "RAD001"), ("DRUG", "Exemestane")]),
]
KEYTRUDA = [
    make_trial("NCT00000021", [("DRUG", "Pembrolizumab", ["Keytruda"]), ("DRUG", "Axitinib")]),
    make_trial("NCT00000022", [("DRUG", "Pembrolizumab", ["Keytruda"]), ("DRUG", "Axitinib")]),
]


def _records(trials: list[NormalizedTrial]) -> dict[str, Any]:
    return {t.nct_id: raw_record(t) for t in trials}


def _response(
    intent: Intent,
    dimension: Dimension,
    trials: list[NormalizedTrial] = EVEROLIMUS,
    filters: RetrievalFilters | None = None,
) -> OkResponse:
    cohorts = [cohort(trials, filters=filters)]
    stated = (filters or RetrievalFilters()).model_dump(mode="json", exclude_none=True)
    aggregator = REGISTRY.get(intent, dimension)
    return assemble(
        aggregator,
        aggregator.aggregate(cohorts),
        cohorts,
        filters=Filters.model_validate({"stated": stated, "inferred": {}}),
        title=default_title(aggregator, cohorts),
    )


def _messages(
    response: OkResponse | dict[str, Any],
    dimension: Dimension = Dimension.DRUG,
    records: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    if isinstance(response, dict):
        validated = RESPONSE_ADAPTER.validate_python(response)
        assert isinstance(validated, OkResponse)
        response = validated
    intent = Intent.NETWORK if dimension is Dimension.DRUG_DRUG else Intent.DISTRIBUTION
    shape = REGISTRY.get(intent, dimension).shape
    context = CheckContext(shape=shape, records=records or _records(EVEROLIMUS))
    return [(e.check, e.message) for e in run_checks(response, context)]


def _merge_messages(payload: dict[str, Any], records: dict[str, Any] | None = None) -> list[str]:
    return [m for check, m in _messages(payload, records=records) if check == "name merges"]


def _payload() -> dict[str, Any]:
    return copy.deepcopy(_response(Intent.DISTRIBUTION, Dimension.DRUG).model_dump(mode="json"))


# --- disclosure ---


def test_meta_discloses_each_merge_with_its_evidence() -> None:
    assert _response(Intent.DISTRIBUTION, Dimension.DRUG).meta.name_merges == [
        NameMerge(
            entity_type="drug",
            name="Everolimus",
            merged_names=["RAD001"],
            evidence=[
                Citation(nct_id="NCT00000012", excerpt="RAD001", field=OTHER_NAMES),
                Citation(nct_id="NCT00000011", excerpt="RAD001", field=OTHER_NAMES),
            ],
        )
    ]


def test_charts_without_a_drug_dimension_disclose_no_merges() -> None:
    assert _response(Intent.DISTRIBUTION, Dimension.PHASE).meta.name_merges == []


def test_merged_charts_pass_every_check() -> None:
    assert _messages(_response(Intent.DISTRIBUTION, Dimension.DRUG)) == []
    network = _response(Intent.NETWORK, Dimension.DRUG_DRUG)
    assert _messages(network, Dimension.DRUG_DRUG) == []


def test_a_named_synonym_may_anchor_the_drug_it_merged_into() -> None:
    response = _response(
        Intent.NETWORK, Dimension.DRUG_DRUG, KEYTRUDA, RetrievalFilters(drug_name="Keytruda")
    )
    assert _messages(response, Dimension.DRUG_DRUG, _records(KEYTRUDA)) == []


# --- the name merges check ---


def test_an_excerpt_not_in_the_records_other_names_fails() -> None:
    payload = _payload()
    payload["meta"]["name_merges"][0]["evidence"][0]["excerpt"] = "Afinitor"
    assert any("Afinitor" in m for m in _merge_messages(payload))


def test_evidence_from_another_drugs_intervention_fails() -> None:
    # Trial 12 registers RAD001 under exemestane, so it is no evidence for everolimus.
    records = _records(EVEROLIMUS)
    interventions = records["NCT00000012"]["protocolSection"]["armsInterventionsModule"]
    interventions["interventions"] = [
        {"type": "DRUG", "name": "Everolimus"},
        {"type": "DRUG", "name": "Exemestane", "otherNames": ["RAD001"]},
    ]
    messages = _merge_messages(_payload(), records)
    assert any("NCT00000012" in m and "Everolimus" in m for m in messages)


def test_evidence_from_a_trial_never_retrieved_fails() -> None:
    payload = _payload()
    payload["meta"]["name_merges"][0]["evidence"][0]["nct_id"] = "NCT00000099"
    assert any("NCT00000099" in m for m in _merge_messages(payload))


def test_an_undisclosed_merge_fails() -> None:
    payload = _payload()
    payload["meta"]["name_merges"] = []
    assert any("Everolimus" in m for m in _merge_messages(payload))


def test_an_invented_merge_fails() -> None:
    payload = _payload()
    invented = copy.deepcopy(payload["meta"]["name_merges"][0])
    invented |= {"name": "Exemestane", "merged_names": ["Letrozole"]}
    payload["meta"]["name_merges"].append(invented)
    assert any("Exemestane" in m for m in _merge_messages(payload))


def test_evidence_beyond_the_citation_cap_fails() -> None:
    payload = _payload()
    payload["meta"]["citation_cap"] = 1
    assert any("citation_cap" in m for m in _merge_messages(payload))
