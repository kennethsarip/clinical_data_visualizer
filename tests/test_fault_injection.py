"""Seeded faults (CLAUDE.md §14 Phase 7 step 7): each corrupts one thing in a valid answer, and
the check named beside it must catch it. The clean answer passes every check, so a fault is
caught by its check and not by an accident of the fixture.

The fixture is the SCHEMAS.md bar example with complete raw records written to match it.
"""

from collections.abc import Callable
from typing import Any

import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.common import PHASE
from app.aggregators.registry import REGISTRY, Dimension, Intent, RowShape
from app.checks import CheckContext, run_checks
from app.ctgov import build_params
from app.schemas import RESPONSE_ADAPTER, OkResponse, RetrievalFilters
from tests.factories import make_trial, raw_record
from tests.test_checks import NETWORK_RECORDS, _bar, _network, _with, bar_records

PHASES = ["NCT00000001", "NCT00000002", "NCT00000003", "NCT00000004"]
Payload = dict[str, Any]
Records = dict[str, dict[str, Any]]


def _rows(p: Payload) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = p["visualization"]["data"]
    return rows


def invented_nct_id(p: Payload, r: Records) -> None:
    row = _rows(p)[1]
    row["nct_ids"].append("NCT09999999")
    row["trial_count"] += 1
    p["meta"]["sample"][0]["fetched"] += 1
    p["meta"]["sample"][0]["total"] += 1


def wrong_bucket_citation(p: Payload, r: Records) -> None:
    # A Phase 2 trial on the Phase 3 bar, cited with its real value "PHASE2".
    r["NCT00000001"] = _with("NCT00000001", designModule={"phases": ["PHASE2"]})
    _rows(p)[1]["citations"][1]["excerpt"] = "PHASE2"


def excerpt_not_in_record(p: Payload, r: Records) -> None:
    _rows(p)[1]["citations"][0]["excerpt"] = "PHASE4"


def miscounted_row(p: Payload, r: Records) -> None:
    _rows(p)[1]["trial_count"] = 3


def unaccounted_trial(p: Payload, r: Records) -> None:
    # A retrieved Phase 3 trial that no bar shows and no exclusion counts.
    r["NCT00000005"] = raw_record(make_trial("NCT00000005", phases=["PHASE3"]))


def off_filter_trial(p: Payload, r: Records) -> None:
    p["meta"]["filters"]["stated"]["country"] = "Japan"
    for n in PHASES:
        r[n] = _with(n, contactsLocationsModule={"locations": [{"country": "Japan"}]})
    r["NCT00000002"] = _with(
        "NCT00000002", contactsLocationsModule={"locations": [{"country": "China"}]}
    )


def stray_title_number(p: Payload, r: Records) -> None:
    p["visualization"]["title"] = "Top 3 Phases for Pembrolizumab"


def undisclosed_inferred_filter(p: Payload, r: Records) -> None:
    p["meta"]["filters"]["inferred"] = {"condition": "melanoma"}
    p["meta"]["assumptions"] = []


def false_cap_disclosure(p: Payload, r: Records) -> None:
    p["meta"]["sample"][0]["capped"] = True


def unknown_encoding_field(p: Payload, r: Records) -> None:
    p["visualization"]["encoding"]["x"]["field"] = "stage"


def uncited_datum(p: Payload, r: Records) -> None:
    _rows(p)[1]["citations"] = _rows(p)[1]["citations"][:1]  # holds 2 trials, cites 1


def wrong_card_description(p: Payload, r: Records) -> None:
    p["trials"]["NCT00000001"]["official_title"] = "A Phase 3 Study of Nivolumab"


def miscounted_exclusion(p: Payload, r: Records) -> None:
    p["meta"]["excluded"] = [{"rule": "no locations", "count": 2, "nct_ids": ["NCT00000004"]}]


Fault = Callable[[Payload, Records], None]
FAULTS: list[tuple[Fault, str]] = [
    (invented_nct_id, "citation ids"),
    (wrong_bucket_citation, "membership"),
    (excerpt_not_in_record, "excerpts"),
    (miscounted_row, "reconciliation"),
    (unaccounted_trial, "membership"),
    (off_filter_trial, "conformance"),
    (stray_title_number, "title"),
    (undisclosed_inferred_filter, "assumptions"),
    (false_cap_disclosure, "disclosures"),
    (unknown_encoding_field, "encoding"),
    (uncited_datum, "coverage"),
    (wrong_card_description, "summaries"),
    (miscounted_exclusion, "accounting"),
]


def _failed(fault: Fault | None) -> set[str]:
    payload = _bar()
    records = bar_records()
    if fault:
        fault(payload, records)
    response = RESPONSE_ADAPTER.validate_python(payload)
    assert isinstance(response, OkResponse)
    filters = {**response.meta.filters.stated, **response.meta.filters.inferred}
    sent = [build_params(RetrievalFilters.model_validate(filters), 1000)]
    context = CheckContext(RowShape.CATEGORICAL, records, sent, PHASE)
    return {e.check for e in run_checks(response, context)}


def test_the_clean_answer_passes_every_check() -> None:
    assert _failed(None) == set()


@pytest.mark.parametrize(("fault", "check"), FAULTS, ids=[f.__name__ for f, _ in FAULTS])
def test_each_seeded_fault_is_caught_by_its_check(fault: Fault, check: str) -> None:
    assert check in _failed(fault)


# --- network faults: the SCHEMAS.md network example, with its raw record ---


def _node(p: Payload, node_id: str) -> dict[str, Any]:
    node: dict[str, Any] = next(
        n for n in p["visualization"]["data"]["nodes"] if n["id"] == node_id
    )
    return node


def node_cited_with_another_drug(p: Payload, r: Records) -> None:
    _node(p, "drug:pembrolizumab")["citations"][0]["excerpt"] = "Ipilimumab"


def edge_cites_one_end(p: Payload, r: Records) -> None:
    edge = p["visualization"]["data"]["edges"][0]
    edge["citations"] = edge["citations"][:1]


def node_given_an_unrelated_trial(p: Payload, r: Records) -> None:
    # NCT00000008 was retrieved (no interventions, so listed under that rule) but names no drug.
    node = _node(p, "drug:pembrolizumab")
    node["nct_ids"] = sorted([*node["nct_ids"], "NCT00000008"], reverse=True)
    node["trial_count"] += 1
    r["NCT00000008"] = raw_record(make_trial("NCT00000008", brief_title="u"))
    p["meta"]["excluded"] = [{"rule": "no interventions", "count": 1, "nct_ids": ["NCT00000008"]}]
    p["meta"]["sample"][0]["fetched"] = p["meta"]["sample"][0]["total"] = 2
    p["trials"]["NCT00000008"] = p["trials"]["NCT00000007"] | {
        "brief_title": "u",
        "phase": "Not specified",
    }


NETWORK_FAULTS: list[tuple[Fault, str]] = [
    (node_cited_with_another_drug, "membership"),
    (edge_cites_one_end, "membership"),
    (node_given_an_unrelated_trial, "recount"),
]


def _network_failed(fault: Fault | None) -> set[str]:
    payload = _network()
    records = dict(NETWORK_RECORDS)
    if fault:
        fault(payload, records)
    response = RESPONSE_ADAPTER.validate_python(payload)
    assert isinstance(response, OkResponse)
    aggregator = REGISTRY.get(Intent.NETWORK, Dimension.DRUG_DRUG)
    ids = [frozenset(records)]
    context = CheckContext(RowShape.GRAPH, records, aggregator=aggregator, cohort_ids=ids)
    return {e.check for e in run_checks(response, context)}


def test_the_clean_network_passes_every_check() -> None:
    assert _network_failed(None) == set()


@pytest.mark.parametrize(
    ("fault", "check"), NETWORK_FAULTS, ids=[f.__name__ for f, _ in NETWORK_FAULTS]
)
def test_each_seeded_network_fault_is_caught_by_its_check(fault: Fault, check: str) -> None:
    assert check in _network_failed(fault)
