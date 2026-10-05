"""The pipeline: CLAUDE.md §1 steps end to end, offline (fake LLM, in-memory fetcher).

Expected statuses come from §1 (steps 3, 5, 9), §7.7 (repair once, error mapping), §7.8 (anchor
rule, zero results, not-found probe) and SCHEMAS.md §5 (non-`ok` shapes and notes).
"""

from collections.abc import Callable
from datetime import date
from typing import Any

import httpx2
import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.checks import CheckContext, run_checks
from app.ctgov import FetchResult, UpstreamError
from app.normalize import NormalizedTrial
from app.pipeline import DependencyError, Pipeline
from app.planner import ANCHOR_NOTE
from app.schemas import (
    CheckError,
    ClarificationResponse,
    DegradedResponse,
    NoResultsResponse,
    OkResponse,
    RetrievalFilters,
    VisualizeRequest,
)
from app.viz import PROSE_FALLBACK_NOTE
from tests.factories import FIXTURE, T3, make_trial, raw_record
from tests.llm_fakes import fake_llm, json_reply, replies
from tests.test_planner import reply

TODAY = date(2026, 10, 4)
PROSE = {"title": "Melanoma Trials by Phase", "notes": ["Counts trials listing melanoma."]}


class FakeFetcher:
    """Serves records per filter set; anything unlisted matches nothing."""

    def __init__(
        self,
        data: dict[RetrievalFilters, list[NormalizedTrial]] | None = None,
        counts: dict[RetrievalFilters, int] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.data = data or {}
        self.counts = counts or {}
        self.error = error
        self.fetched: list[RetrievalFilters] = []
        self.counted: list[RetrievalFilters] = []

    def fetch(self, filters: RetrievalFilters) -> FetchResult:
        self.fetched.append(filters)
        if self.error:
            raise self.error
        records = [raw_record(t) for t in self.data.get(filters, [])]
        return FetchResult("key", [], records, len(records))

    def count(self, filters: RetrievalFilters) -> int:
        self.counted.append(filters)
        return self.counts.get(filters, len(self.data.get(filters, [])))


def run(
    query: str,
    llm_replies: list[httpx2.Response],
    fetcher: FakeFetcher,
    checker: Callable[[OkResponse, CheckContext], list[CheckError]] = run_checks,
    **fields: Any,
) -> tuple[Any, list[dict[str, Any]]]:
    llm, bodies = fake_llm(replies(*llm_replies))
    pipeline = Pipeline(llm, fetcher, checker=checker, today=lambda: TODAY)
    return pipeline.run(VisualizeRequest.model_validate({"query": query, **fields})), bodies


MELANOMA = RetrievalFilters(condition="melanoma")


# --- ok (§1 step 9) ---


def test_ok_response_with_llm_title_and_checked_spec() -> None:
    fetcher = FakeFetcher({MELANOMA: FIXTURE})
    response, bodies = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        fetcher,
    )
    assert isinstance(response, OkResponse)
    assert response.visualization.title == "Melanoma Trials by Phase"
    assert response.visualization.type == "bar_chart"
    assert response.meta.filters.stated == {"condition": "melanoma"}
    assert "Counts trials listing melanoma." in response.meta.notes
    assert fetcher.fetched == [MELANOMA] and len(bodies) == 2
    records = {t.nct_id: raw_record(t) for t in FIXTURE}
    assert (
        run_checks(response, CheckContext(app.aggregators.registry.RowShape.CATEGORICAL, records))
        == []
    )


def test_planner_notes_and_assumptions_reach_meta() -> None:
    fetcher = FakeFetcher({RetrievalFilters(condition="melanoma", start_year=2021): FIXTURE})
    response, _ = run(
        "melanoma trials started each year over the last five years",
        [
            json_reply(reply("time_trend.start_year", condition="melanoma", start_year=2021)),
            json_reply(PROSE),
        ],
        fetcher,
    )
    assert isinstance(response, OkResponse)
    assert response.meta.filters.inferred == {"start_year": 2021}
    assert any("2021" in a for a in response.meta.assumptions)


def test_comparison_fetches_each_cohort() -> None:
    pembro, nivo = (
        RetrievalFilters(drug_name="pembrolizumab"),
        RetrievalFilters(drug_name="nivolumab"),
    )
    fetcher = FakeFetcher({pembro: FIXTURE[:3], nivo: FIXTURE[3:]})
    cohorts = [
        {"label": "pembrolizumab", "entity": "drug_name", "value": "pembrolizumab"},
        {"label": "nivolumab", "entity": "drug_name", "value": "nivolumab"},
    ]
    response, _ = run(
        "Compare phases for pembrolizumab vs nivolumab",
        [
            json_reply(reply("comparison.phase", cohorts)),
            json_reply({"title": "Phases", "notes": []}),
        ],
        fetcher,
    )
    assert isinstance(response, OkResponse)
    assert response.visualization.type == "grouped_bar_chart"
    assert fetcher.fetched == [pembro, nivo]
    assert response.meta.filters.stated == {}


def test_failed_title_call_keeps_the_response_ok() -> None:
    fetcher = FakeFetcher({MELANOMA: FIXTURE})
    response, _ = run(
        "Phases of melanoma trials",
        [
            json_reply(reply(condition="melanoma")),
            httpx2.Response(500, json={"error": {"message": "x"}}),
        ],
        fetcher,
    )
    assert isinstance(response, OkResponse)
    assert PROSE_FALLBACK_NOTE in response.meta.notes


# --- clarification (§1 step 3) and plan failure (§7.7) ---


def test_no_anchor_asks_before_any_fetch() -> None:
    fetcher = FakeFetcher()
    response, bodies = run("Show me trials", [json_reply(reply())], fetcher)
    assert isinstance(response, ClarificationResponse)
    assert response.meta.missing == ["drug_name", "condition", "sponsor"]
    assert ANCHOR_NOTE in response.meta.notes
    assert fetcher.fetched == [] and len(bodies) == 1


def test_plan_invalid_twice_is_degraded_with_the_request_filters() -> None:
    bad = json_reply(reply("distribution.investigator"))
    response, _ = run("melanoma by investigator", [bad, bad], FakeFetcher(), condition="melanoma")
    assert isinstance(response, DegradedResponse)
    assert [e.check for e in response.meta.errors] == ["plan"]
    assert response.meta.filters.stated == {"condition": "melanoma"}


# --- zero results and the not-found probe (§1 step 5, §7.8) ---


def test_lone_entity_with_zero_results_is_not_found_without_a_probe() -> None:
    fetcher = FakeFetcher()
    response, _ = run(
        "Trials per year for Zorblaxumab",
        [json_reply(reply("time_trend.start_year", drug_name="Zorblaxumab"))],
        fetcher,
    )
    assert isinstance(response, NoResultsResponse)
    assert response.meta.not_found == ["Zorblaxumab"]
    assert any("Zorblaxumab" in n and "substituted" in n for n in response.meta.notes)
    assert fetcher.counted == []  # the search itself was the probe


def test_existing_entity_under_filters_that_match_nothing_is_not_widened() -> None:
    fetcher = FakeFetcher(counts={RetrievalFilters(condition="Erdheim-Chester disease"): 26})
    response, _ = run(
        "status breakdown",
        [json_reply(reply("distribution.overall_status"))],
        fetcher,
        condition="Erdheim-Chester disease",
        trial_phase="PHASE4",
        country="Iceland",
    )
    assert isinstance(response, NoResultsResponse)
    assert response.meta.not_found == []
    assert any("not widened" in n for n in response.meta.notes)
    assert fetcher.counted == [RetrievalFilters(condition="Erdheim-Chester disease")]
    assert response.meta.filters.stated["country"] == "Iceland"


def test_unknown_entity_under_filters_is_reported_not_found() -> None:
    fetcher = FakeFetcher()
    response, _ = run(
        "Zorblaxumab Phase 3 trials by status",
        [
            json_reply(
                reply("distribution.overall_status", drug_name="Zorblaxumab", trial_phase="PHASE3")
            )
        ],
        fetcher,
    )
    assert isinstance(response, NoResultsResponse)
    assert response.meta.not_found == ["Zorblaxumab"]
    assert fetcher.counted == [RetrievalFilters(drug_name="Zorblaxumab")]


def test_comparison_with_every_cohort_empty_probes_each_entity() -> None:
    fetcher = FakeFetcher(counts={RetrievalFilters(drug_name="aspirin"): 900})
    cohorts = [
        {"label": "aspirin", "entity": "drug_name", "value": "aspirin"},
        {"label": "Zorblaxumab", "entity": "drug_name", "value": "Zorblaxumab"},
    ]
    response, _ = run(
        "Compare phases for aspirin vs Zorblaxumab in Iceland",
        [json_reply(reply("comparison.phase", cohorts, country="Iceland"))],
        fetcher,
    )
    assert isinstance(response, NoResultsResponse)
    assert response.meta.not_found == ["Zorblaxumab"]


def test_trials_that_all_fall_out_of_the_chart_are_no_results_naming_the_rule() -> None:
    no_locations = [T3, make_trial("NCT00000099", conditions=["Melanoma"])]
    fetcher = FakeFetcher({MELANOMA: no_locations})
    response, _ = run(
        "Which countries host melanoma trials?",
        [json_reply(reply("geographic.country", condition="melanoma"))],
        fetcher,
    )
    assert isinstance(response, NoResultsResponse)
    assert response.meta.not_found == []
    assert any("no locations" in n for n in response.meta.notes)


# --- repair once, then degraded (§7.7) ---


def _failing(
    times: int,
) -> tuple[Callable[[OkResponse, CheckContext], list[CheckError]], list[OkResponse]]:
    seen: list[OkResponse] = []

    def checker(response: OkResponse, context: CheckContext) -> list[CheckError]:
        seen.append(response)
        if len(seen) <= times:
            return [CheckError(check="encoding", message="synthetic failure")]
        return run_checks(response, context)

    return checker, seen


def test_failed_check_is_repaired_once_without_llm_prose() -> None:
    checker, seen = _failing(1)
    fetcher = FakeFetcher({MELANOMA: FIXTURE})
    response, _ = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        fetcher,
        checker=checker,
    )
    assert isinstance(response, OkResponse) and len(seen) == 2
    assert response.visualization.title != PROSE["title"]  # the repair drops LLM prose
    assert "Counts trials listing melanoma." not in response.meta.notes
    assert fetcher.fetched == [MELANOMA]  # never re-queried


def test_check_failing_after_the_repair_is_degraded_with_the_errors() -> None:
    checker, seen = _failing(2)
    response, _ = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        FakeFetcher({MELANOMA: FIXTURE}),
        checker=checker,
    )
    assert isinstance(response, DegradedResponse) and len(seen) == 2
    assert response.meta.errors == [CheckError(check="encoding", message="synthetic failure")]
    assert response.meta.filters.stated == {"condition": "melanoma"}


# --- dependency failures -> DependencyError (502, §7.7) ---


def test_clinicaltrials_failure_is_a_dependency_error() -> None:
    with pytest.raises(DependencyError, match="ClinicalTrials"):
        run(
            "Phases of melanoma trials",
            [json_reply(reply(condition="melanoma"))],
            FakeFetcher(error=UpstreamError("ClinicalTrials.gov HTTP 503")),
        )


def test_llm_failure_while_planning_is_a_dependency_error() -> None:
    with pytest.raises(DependencyError, match="LLM"):
        run(
            "Phases of melanoma trials",
            [httpx2.Response(503, json={"error": {"message": "x"}})],
            FakeFetcher(),
        )


def test_mostly_unreadable_records_are_a_dependency_error() -> None:
    class Garbage(FakeFetcher):
        def fetch(self, filters: RetrievalFilters) -> FetchResult:
            return FetchResult("key", [], [{"protocolSection": {}}] * 10, 10)

    with pytest.raises(DependencyError, match="unreadable"):
        run("Phases of melanoma trials", [json_reply(reply(condition="melanoma"))], Garbage())


def test_one_record_without_an_id_is_set_aside_not_fatal() -> None:
    trials = [
        make_trial(f"NCT{n:08d}", conditions=["Melanoma"], phases=["PHASE2"]) for n in range(1, 21)
    ]

    class OneBad(FakeFetcher):
        def fetch(self, filters: RetrievalFilters) -> FetchResult:
            records = [raw_record(t) for t in trials] + [{"protocolSection": {}}]
            return FetchResult("key", [], records, len(records))

    response, _ = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        OneBad(),
    )
    assert isinstance(response, OkResponse)
    assert {e.rule: e.count for e in response.meta.excluded}.get("unreadable record") == 1
