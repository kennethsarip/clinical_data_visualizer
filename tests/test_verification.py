"""The verification ledger (CLAUDE.md §14 Phase 7 step 5): `meta.verification` on every status
says, per pipeline step, which checks ran, how many items they verified, and where an answer
stopped. Expected values come from the fixture by hand (FIXTURE: five melanoma trials)."""

from typing import Any

from app.schemas import (
    ClarificationResponse,
    DegradedResponse,
    NoResultsResponse,
    OkResponse,
    RetrievalFilters,
)
from tests.factories import FIXTURE
from tests.llm_fakes import json_reply
from tests.test_pipeline import MELANOMA, PROSE, FakeFetcher, _failing, run
from tests.test_planner import constraint, reply

STEPS = ["request", "plan", "retrieval", "records", "aggregation", "citations", "prose", "response"]


def _ledger(response: Any) -> dict[str, Any]:
    entries = [e.model_dump() for e in response.meta.verification]
    assert [e["step"] for e in entries] == STEPS
    return {e["step"]: e for e in entries}


def test_an_ok_answer_passes_every_step_with_its_counts() -> None:
    response, _ = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        FakeFetcher({MELANOMA: FIXTURE}),
    )
    assert isinstance(response, OkResponse)
    ledger = _ledger(response)
    assert {e["status"] for e in ledger.values()} == {"passed"}
    assert (ledger["retrieval"]["verified"], ledger["retrieval"]["total"]) == (5, 5)
    # Every fixture trial is on a phase bar (T3 under "Not specified"): 5 of 5 accounted for.
    assert (ledger["aggregation"]["verified"], ledger["aggregation"]["total"]) == (5, 5)
    rows = response.visualization.data
    assert isinstance(rows, list)
    citations = sum(len(r.citations) for r in rows)
    assert ledger["citations"]["verified"] == ledger["citations"]["total"] == citations
    assert "membership" in ledger["aggregation"]["checks"]
    assert "excerpts" in ledger["citations"]["checks"]
    assert all(e["result"] for e in ledger.values())


def test_a_clarification_stops_at_the_plan_and_names_why() -> None:
    plan = reply(
        condition="asthma",
        constraints=[
            constraint("asthma", "condition"),
            constraint("pediatric", None, "no filter for age group"),
        ],
    )
    response, _ = run(
        "How are pediatric asthma trials distributed across phases?",
        [json_reply(plan)],
        FakeFetcher(),
    )
    assert isinstance(response, ClarificationResponse)
    ledger = _ledger(response)
    assert ledger["request"]["status"] == "passed"
    assert ledger["plan"]["status"] == "stopped"
    assert "pediatric" in ledger["plan"]["result"]
    assert {ledger[s]["status"] for s in STEPS[2:]} == {"not_reached"}


def test_no_results_stops_at_retrieval() -> None:
    response, _ = run(
        "status breakdown",
        [json_reply(reply("distribution.overall_status"))],
        FakeFetcher(counts={RetrievalFilters(condition="Erdheim-Chester disease"): 26}),
        condition="Erdheim-Chester disease",
        trial_phase="PHASE4",
        country="Iceland",
    )
    assert isinstance(response, NoResultsResponse)
    ledger = _ledger(response)
    assert ledger["plan"]["status"] == "passed"
    assert ledger["retrieval"]["status"] == "stopped"
    assert (ledger["retrieval"]["verified"], ledger["retrieval"]["total"]) == (0, 0)
    assert {ledger[s]["status"] for s in STEPS[3:]} == {"not_reached"}


def test_a_failed_check_marks_its_step_failed() -> None:
    checker, _ = _failing(2)  # fails "encoding" on both attempts
    response, _ = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        FakeFetcher({MELANOMA: FIXTURE}),
        checker=checker,
    )
    assert isinstance(response, DegradedResponse)
    ledger = _ledger(response)
    assert ledger["response"]["status"] == "failed"
    assert "encoding" in ledger["response"]["result"]
    assert ledger["retrieval"]["status"] == "passed"


def test_an_invalid_plan_fails_the_plan_step() -> None:
    bad = json_reply(reply("distribution.investigator"))
    response, _ = run("melanoma by investigator", [bad, bad], FakeFetcher(), condition="melanoma")
    assert isinstance(response, DegradedResponse)
    ledger = _ledger(response)
    assert ledger["plan"]["status"] == "failed"
    assert {ledger[s]["status"] for s in STEPS[2:]} == {"not_reached"}
