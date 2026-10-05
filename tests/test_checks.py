"""Every §7.6 spec check, with a passing and a failing fixture (CLAUDE.md §9).

The passing fixtures are the SCHEMAS.md examples with raw records written to match them, so the
documented contract is also proven to pass the checks. Each failing fixture breaks one rule.
"""

import copy
import json
import re
from pathlib import Path
from typing import Any

from app.aggregators.common import PHASE
from app.aggregators.registry import RowShape
from app.checks import CheckContext, run_checks
from app.ctgov import build_params
from app.schemas import RESPONSE_ADAPTER, OkResponse, RetrievalFilters
from app.viz import VIZ_TYPE
from tests.factories import make_trial, raw_record

SCHEMAS_MD = Path(__file__).resolve().parents[1] / "SCHEMAS.md"
_BLOCKS = [
    json.loads(b) for b in re.findall(r"```json\n(.*?)```", SCHEMAS_MD.read_text(), re.DOTALL)
]
BAR = next(b for b in _BLOCKS if b.get("status") == "ok")
NETWORK_SPEC = next(b for b in _BLOCKS if b.get("type") == "network_graph")
TIME_SPEC = next(b for b in _BLOCKS if b.get("type") == "time_series")


def _record(nct_id: str, **modules: Any) -> dict[str, Any]:
    return {"protocolSection": {"identificationModule": {"nctId": nct_id}, **modules}}


BAR_RECORDS = {
    "NCT00000001": _record("NCT00000001", designModule={"phases": ["PHASE3"]}),
    "NCT00000002": _record("NCT00000002", designModule={"phases": ["PHASE3"]}),
    "NCT00000003": _record("NCT00000003", designModule={"phases": ["PHASE1", "PHASE2"]}),
    "NCT00000004": _record("NCT00000004", designModule={"studyType": "OBSERVATIONAL"}),
}
NETWORK_RECORDS = {
    "NCT00000007": _record(
        "NCT00000007",
        armsInterventionsModule={
            "interventions": [
                {"type": "BIOLOGICAL", "name": "Pembrolizumab (MK-3475)"},
                {"type": "DRUG", "name": "Ipilimumab"},
            ]
        },
    )
}


def _bar() -> dict[str, Any]:
    return copy.deepcopy(BAR)


def _network() -> dict[str, Any]:
    response = _bar()
    response["visualization"] = copy.deepcopy(NETWORK_SPEC)
    response["trials"] = {
        "NCT00000007": {
            "brief_title": "t",
            "overall_status": "Completed",
            "phase": "Phase 2",
            "start_date": None,
            "sponsor_name": "s",
            "conditions": [],
        }
    }
    response["meta"]["interpretation"] = {
        "intent": "network",
        "dimension": "drug_drug",
        "cohorts": None,
    }
    response["meta"]["grouping"] = {"dimension": "drug_drug", "series": None}
    response["meta"]["sort"] = {"field": "trial_count", "order": "desc"}
    response["meta"]["sample"] = [{"cohort": None, "fetched": 1, "total": 1, "capped": False}]
    response["meta"]["pruning"] = {
        "min_edge_weight": 1,
        "top_n_nodes": 50,
        "fallback_used": True,
        "nodes_removed": 0,
        "edges_removed": 0,
    }
    return response


def _errors(
    payload: dict[str, Any],
    shape: RowShape = RowShape.CATEGORICAL,
    records: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    response = RESPONSE_ADAPTER.validate_python(payload)
    assert isinstance(response, OkResponse)
    context = CheckContext(shape=shape, records=BAR_RECORDS if records is None else records)
    return [(e.check, e.message) for e in run_checks(response, context)]


def _checks(errors: list[tuple[str, str]]) -> set[str]:
    return {check for check, _ in errors}


# --- passing fixtures ---


def test_the_schemas_md_bar_example_passes_every_check() -> None:
    assert _errors(_bar()) == []


def test_the_schemas_md_network_example_passes_every_check() -> None:
    assert _errors(_network(), RowShape.GRAPH, NETWORK_RECORDS) == []


def test_viz_type_table_covers_every_shape() -> None:
    # CLAUDE.md §7.4: one type per shape.
    assert VIZ_TYPE == {
        RowShape.CATEGORICAL: "bar_chart",
        RowShape.TWO_CATEGORICAL: "grouped_bar_chart",
        RowShape.TEMPORAL: "time_series",
        RowShape.PER_TRIAL_NUMERIC: "scatter_plot",
        RowShape.BINNED_NUMERIC: "histogram",
        RowShape.GRAPH: "network_graph",
    }


# --- schema ---


def test_schema_fails_when_the_response_does_not_round_trip() -> None:
    response = RESPONSE_ADAPTER.validate_python(_bar())
    assert isinstance(response, OkResponse)
    broken = response.model_copy(update={"trials": {"not-an-id": "oops"}})  # bypasses validation
    errors = run_checks(broken, CheckContext(shape=RowShape.CATEGORICAL, records=BAR_RECORDS))
    assert "schema" in {e.check for e in errors}


# --- encoding ---


def test_encoding_field_missing_from_a_row_fails() -> None:
    payload = _bar()
    payload["visualization"]["encoding"]["x"]["field"] = "phase_label"
    errors = _errors(payload)
    assert _checks(errors) == {"encoding"}
    assert "phase_label" in errors[0][1]


def test_network_edge_channel_must_exist_on_edges() -> None:
    payload = _network()
    payload["visualization"]["encoding"]["edges"]["weight"]["field"] = "weight"
    assert _checks(_errors(payload, RowShape.GRAPH, NETWORK_RECORDS)) == {"encoding"}


# --- shape ---


def test_type_that_does_not_match_the_row_shape_fails() -> None:
    assert _checks(_errors(_bar(), RowShape.TEMPORAL)) == {"shape"}


def test_time_series_x_must_strictly_ascend() -> None:
    payload = _bar()
    spec = copy.deepcopy(TIME_SPEC)
    spec["data"].reverse()
    payload["visualization"] = spec
    payload["trials"] = {"NCT00000001": BAR["trials"]["NCT00000001"]}
    payload["meta"]["grouping"] = {"dimension": "start_year", "series": None}
    payload["meta"]["sample"] = [{"cohort": None, "fetched": 1, "total": 1, "capped": False}]
    payload["meta"]["filters"]["stated"]["start_year"] = 2015  # the title says "since 2015"
    records = {
        "NCT00000001": _record("NCT00000001", statusModule={"startDateStruct": {"date": "2015-03"}})
    }
    assert _checks(_errors(payload, RowShape.TEMPORAL, records)) == {"shape"}


def test_network_without_edges_fails() -> None:
    payload = _network()
    payload["visualization"]["data"]["edges"] = []
    assert "shape" in _checks(_errors(payload, RowShape.GRAPH, NETWORK_RECORDS))


def test_grouped_bar_needs_a_series_channel() -> None:
    payload = _bar()
    payload["visualization"]["type"] = "grouped_bar_chart"
    assert _checks(_errors(payload, RowShape.TWO_CATEGORICAL)) == {"shape"}


# --- citation ids ---


def test_citation_outside_its_rows_nct_ids_fails() -> None:
    payload = _bar()
    payload["visualization"]["data"][1]["citations"][0]["nct_id"] = "NCT00000003"
    assert "citation ids" in _checks(_errors(payload))


def test_nct_id_outside_the_retrieved_records_fails() -> None:
    records = dict(BAR_RECORDS)
    del records["NCT00000004"]
    assert "citation ids" in _checks(_errors(_bar(), records=records))


def test_trials_lookup_must_cover_every_row_trial() -> None:
    payload = _bar()
    del payload["trials"]["NCT00000004"]
    assert _checks(_errors(payload)) == {"citation ids"}


# --- excerpts ---


def test_excerpt_not_in_the_cited_field_fails() -> None:
    payload = _bar()
    payload["visualization"]["data"][1]["citations"][0]["excerpt"] = "PHASE4"
    errors = _errors(payload)
    assert _checks(errors) == {"excerpts"}
    assert "NCT00000002" in errors[0][1]


def test_excerpt_from_a_different_field_fails() -> None:
    # "OBSERVATIONAL" is in NCT00000004's record, but not in designModule.phases.
    payload = _bar()
    payload["visualization"]["data"][2]["citations"][0]["excerpt"] = "OBSERVATIONAL"
    assert _checks(_errors(payload)) == {"excerpts"}


def test_null_excerpt_requires_the_field_to_be_absent() -> None:
    payload = _bar()
    payload["visualization"]["data"][1]["citations"][0]["excerpt"] = None
    assert _checks(_errors(payload)) == {"excerpts"}


def test_excerpt_inside_a_list_of_objects_passes() -> None:
    payload = _bar()
    payload["visualization"]["data"][1]["citations"][0] = {
        "nct_id": "NCT00000002",
        "excerpt": "Germany",
        "field": "contactsLocationsModule.locations.country",
    }
    records = dict(BAR_RECORDS)
    records["NCT00000002"] = _record(
        "NCT00000002",
        designModule={"phases": ["PHASE3"]},
        contactsLocationsModule={"locations": [{"country": "France"}, {"country": "Germany"}]},
    )
    assert _errors(payload, records=records) == []


def test_numeric_excerpt_matches_the_integer_value() -> None:
    payload = _bar()
    payload["visualization"]["data"][1]["citations"][0] = {
        "nct_id": "NCT00000002",
        "excerpt": "120",
        "field": "designModule.enrollmentInfo.count",
    }
    records = dict(BAR_RECORDS)
    records["NCT00000002"] = _record(
        "NCT00000002", designModule={"phases": ["PHASE3"], "enrollmentInfo": {"count": 120}}
    )
    assert _errors(payload, records=records) == []


# --- reconciliation ---


def test_trial_count_must_equal_the_number_of_nct_ids() -> None:
    payload = _bar()
    payload["visualization"]["data"][1]["trial_count"] = 3
    assert "reconciliation" in _checks(_errors(payload))


def test_single_valued_rows_must_sum_to_trials_minus_exclusions() -> None:
    payload = _bar()
    payload["meta"]["sample"][0].update(fetched=5, total=5)  # 5 fetched, 4 charted, 0 excluded
    errors = _errors(payload)
    assert _checks(errors) == {"reconciliation"}


def test_exclusions_close_the_single_valued_sum() -> None:
    payload = _bar()
    payload["meta"]["sample"][0].update(fetched=5, total=5)
    payload["meta"]["excluded"] = [{"rule": "unreadable record", "count": 1}]
    assert _errors(payload) == []


def test_duplicate_nct_ids_in_a_row_fail() -> None:
    payload = _bar()
    row = payload["visualization"]["data"][1]
    row["nct_ids"] = ["NCT00000002", "NCT00000002"]
    assert "reconciliation" in _checks(_errors(payload))


# --- assumptions ---


def test_inferred_filter_without_an_assumption_fails() -> None:
    payload = _bar()
    payload["meta"]["filters"]["inferred"] = {"condition": "melanoma"}  # a search: no conformance
    payload["meta"]["assumptions"] = []
    assert _checks(_errors(payload)) == {"assumptions"}


# --- conformance (Phase 6 step 4) ---


def test_a_charted_trial_outside_a_country_filter_fails() -> None:
    payload = _bar()
    payload["meta"]["filters"]["stated"]["country"] = "Japan"
    japan = {"locations": [{"country": "Japan"}]}
    records = {
        n: r | {"protocolSection": r["protocolSection"] | {"contactsLocationsModule": japan}}
        for n, r in BAR_RECORDS.items()
    }
    assert _errors(payload, records=records) == []
    beijing = {"locations": [{"facility": "China-Japan Friendship Hospital", "country": "China"}]}
    records["NCT00000002"]["protocolSection"]["contactsLocationsModule"] = beijing
    errors = _errors(payload, records=records)
    assert _checks(errors) == {"conformance"}
    assert "NCT00000002" in errors[0][1] and "country" in errors[0][1]


def test_a_charted_trial_outside_the_phase_filter_fails() -> None:
    payload = _bar()
    payload["meta"]["filters"]["inferred"] = {"trial_phase": "PHASE3"}
    payload["meta"]["assumptions"].append("Phase 3 was inferred.")
    assert _checks(_errors(payload)) == {"conformance"}  # NCT00000003, NCT00000004 are not


def _sent(**filters: Any) -> list[dict[str, str]]:
    return [build_params(RetrievalFilters(**filters), 1000)]


def test_meta_filters_must_equal_the_params_sent() -> None:
    def errors(sent: list[dict[str, str]]) -> set[str]:
        response = RESPONSE_ADAPTER.validate_python(_bar())
        assert isinstance(response, OkResponse)
        context = CheckContext(RowShape.CATEGORICAL, BAR_RECORDS, sent=sent)
        return {e.check for e in run_checks(response, context)}

    assert errors(_sent(drug_name="Pembrolizumab")) == set()
    assert errors(_sent(drug_name="Nivolumab")) == {"conformance"}  # meta shows another value
    assert errors(_sent()) == {"conformance"}  # meta shows a filter never sent
    hidden = _sent(drug_name="Pembrolizumab", country="Japan")
    assert errors(hidden) == {"conformance"}  # a filter was sent that meta does not show


# --- membership (Phase 7 steps 1-2): each trial's raw record puts it in its datum ---

PHASE_TRIALS = {
    "NCT00000001": ["PHASE3"],
    "NCT00000002": ["PHASE3"],
    "NCT00000003": ["PHASE1", "PHASE2"],
    "NCT00000004": [],
}


def _membership_errors(
    payload: dict[str, Any], phases: dict[str, list[str]] | None = None
) -> list[tuple[str, str]]:
    records = {n: raw_record(make_trial(n, phases=p)) for n, p in (phases or PHASE_TRIALS).items()}
    response = RESPONSE_ADAPTER.validate_python(payload)
    assert isinstance(response, OkResponse)
    context = CheckContext(RowShape.CATEGORICAL, records, categorizer=PHASE)
    return [(e.check, e.message) for e in run_checks(response, context)]


def test_every_trial_in_its_records_category_passes_membership() -> None:
    assert _membership_errors(_bar()) == []


def test_a_trial_on_the_wrong_bar_cited_with_its_own_value_fails_membership() -> None:
    """The case the excerpt check cannot see: NCT00000001 is Phase 2, sits on the Phase 3 bar,
    and is cited "PHASE2", which really is in its record."""
    payload = _bar()
    phase3 = payload["visualization"]["data"][1]
    phase3["citations"][1]["excerpt"] = "PHASE2"
    errors = _membership_errors(payload, PHASE_TRIALS | {"NCT00000001": ["PHASE2"]})
    assert _checks(errors) == {"membership"}
    assert any("NCT00000001" in m and "Phase 3" in m for _, m in errors)


def test_a_trial_left_off_its_bar_fails_membership() -> None:
    payload = _bar()
    phase3 = payload["visualization"]["data"][1]
    phase3["nct_ids"] = ["NCT00000001"]
    phase3["trial_count"] = 1
    phase3["citations"] = [c for c in phase3["citations"] if c["nct_id"] == "NCT00000001"]
    errors = _membership_errors(payload)
    assert "membership" in _checks(errors)
    assert any("NCT00000002" in m and "missing" in m for _, m in errors)


# --- title ---


def test_title_number_not_in_the_filters_fails() -> None:
    payload = _bar()
    payload["visualization"]["title"] = "Top 3 Phases for Pembrolizumab"
    errors = _errors(payload)
    assert _checks(errors) == {"title"}
    assert "3" in errors[0][1]


def test_title_numbers_from_the_filters_pass() -> None:
    payload = _bar()
    payload["meta"]["filters"]["stated"] = {"drug_name": "MK-3475", "start_year": 2015}
    payload["visualization"]["title"] = "MK-3475 Trials by Phase since 2015"
    started = {"statusModule": {"startDateStruct": {"date": "2016-03"}}}
    records = {
        n: {"protocolSection": r["protocolSection"] | started} for n, r in BAR_RECORDS.items()
    }
    assert _errors(payload, records=records) == []


# --- disclosures (the §7.6 WARN items must be disclosed consistently) ---


def test_capped_flag_must_match_fetched_and_total() -> None:
    payload = _bar()
    payload["meta"]["sample"][0]["capped"] = True
    assert _checks(_errors(payload)) == {"disclosures"}


def test_network_must_disclose_pruning() -> None:
    payload = _network()
    payload["meta"]["pruning"] = None
    assert _checks(_errors(payload, RowShape.GRAPH, NETWORK_RECORDS)) == {"disclosures"}


def test_non_network_must_not_claim_pruning() -> None:
    payload = _bar()
    payload["meta"]["pruning"] = _network()["meta"]["pruning"]
    assert _checks(_errors(payload)) == {"disclosures"}


def test_top_n_limit_must_bound_the_rows() -> None:
    payload = _bar()
    payload["meta"]["top_n"] = {"limit": 2, "categories_total": 3}
    assert _checks(_errors(payload)) == {"disclosures"}


# --- regressions found in the Phase 2 bug review ---


def test_chart_with_no_trials_fails_shape() -> None:
    # §7.6: never return an empty chart; a zero-filled chart with no trials is empty too.
    payload = _bar()
    payload["visualization"]["data"] = [
        {"phase": "Phase 3", "trial_count": 0, "nct_ids": [], "citations": []}
    ]
    payload["trials"] = {}
    payload["meta"]["sample"] = [{"cohort": None, "fetched": 0, "total": 0, "capped": False}]
    assert "shape" in _checks(_errors(payload))


def test_code_excerpt_must_equal_the_value_not_be_part_of_it() -> None:
    # "PHASE1" is a substring of "EARLY_PHASE1" but is not the trial's phase.
    payload = _bar()
    payload["visualization"]["data"][1]["citations"][0]["excerpt"] = "PHASE1"
    records = dict(BAR_RECORDS)
    records["NCT00000002"] = _record("NCT00000002", designModule={"phases": ["EARLY_PHASE1"]})
    assert "excerpts" in _checks(_errors(payload, records=records))


def test_free_text_excerpt_may_be_a_substring() -> None:
    payload = _bar()
    payload["visualization"]["data"][1]["citations"][0] = {
        "nct_id": "NCT00000002",
        "excerpt": "Pembrolizumab",
        "field": "armsInterventionsModule.interventions.name",
    }
    records = dict(BAR_RECORDS)
    records["NCT00000002"] = _record(
        "NCT00000002",
        designModule={"phases": ["PHASE3"]},
        armsInterventionsModule={"interventions": [{"name": "Pembrolizumab 200 mg IV"}]},
    )
    assert _errors(payload, records=records) == []


def test_every_check_has_a_plain_language_rule_in_order() -> None:
    # The frontend lists these under "Checks passed"; a new check without a rule fails here.
    from app.checks import CHECK_RULES, CHECKS

    assert list(CHECK_RULES) == [name for name, _ in CHECKS]
    assert all(rule.endswith(".") and len(rule) < 120 for rule in CHECK_RULES.values())
