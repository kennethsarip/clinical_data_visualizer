"""The pipeline: CLAUDE.md §1 steps end to end, offline (fake LLM, in-memory fetcher).

Expected statuses come from §1 (steps 3, 5, 9), §7.7 (repair once, error mapping), §7.8 (anchor
rule, zero results, not-found probe) and SCHEMAS.md §5 (non-`ok` shapes and notes).
"""

import json
import threading
import time
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import httpx2
import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.checks import CheckContext, run_checks
from app.ctgov import FetchResult, UpstreamError, build_params, params_key
from app.normalize import NormalizedTrial
from app.pipeline import DependencyError, Pipeline
from app.planner import ANCHOR_NOTE, PLAN_SCHEMA_NAME
from app.schemas import (
    CheckError,
    ClarificationResponse,
    DegradedResponse,
    NoResultsResponse,
    OkResponse,
    RetrievalFilters,
    VisualizeRequest,
)
from app.viz import PROSE_FALLBACK_NOTE, PROSE_SCHEMA_NAME
from tests.factories import FIXTURE, T3, make_trial, raw_record
from tests.llm_fakes import fake_llm, json_reply
from tests.test_planner import constraint, reply

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
        return FetchResult(params_key(build_params(filters, 1000)), [], records, len(records))

    def fetch_many(self, filters: Sequence[RetrievalFilters]) -> list[FetchResult]:
        return [self.fetch(f) for f in filters]

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
    queue = iter(llm_replies)
    # Past the scripted replies, answer like an LLM outage: a non-ok answer's title call still
    # runs in the background, and it must not fail the test from there.
    llm, bodies = fake_llm(lambda request: next(queue, httpx2.Response(503)))
    pipeline = Pipeline(llm, fetcher, checker=checker, today=lambda: TODAY)
    return pipeline.run(VisualizeRequest.model_validate({"query": query, **fields})), bodies


MELANOMA = RetrievalFilters(condition="melanoma")


# --- retrieval conformance (Phase 6 step 4) ---

GERMANY = RetrievalFilters(condition="melanoma", country="Germany")
IN_GERMANY = [
    make_trial(f"NCT{n:08d}", phases=["PHASE2"], countries=["Germany"]) for n in range(10, 29)
]  # 19 trials, so one off-filter trial is 5% of the batch


def test_an_off_filter_trial_is_dropped_and_counted() -> None:
    off = make_trial("NCT00000099", phases=["PHASE2"], countries=["United States"])
    response, _ = run(
        "Phases of melanoma trials in Germany",
        [json_reply(reply(condition="melanoma", country="Germany")), json_reply(PROSE)],
        FakeFetcher({GERMANY: [*IN_GERMANY, off]}),
    )
    assert isinstance(response, OkResponse)
    charted = {n for row in response.visualization.data for n in row.nct_ids}  # type: ignore[union-attr]
    assert charted == {t.nct_id for t in IN_GERMANY}
    assert "NCT00000099" not in response.trials
    excluded = {e.rule: e.count for e in response.meta.excluded}
    assert excluded["outside the country filter"] == 1
    assert response.meta.sample[0].fetched == 20


def test_mostly_off_filter_records_are_degraded_not_charted() -> None:
    """FIXTURE by hand: T2 (US), T3 (no sites) and T4 (France) have no site in Germany."""
    response, _ = run(
        "Phases of melanoma trials in Germany",
        [json_reply(reply(condition="melanoma", country="Germany")), json_reply(PROSE)],
        FakeFetcher({GERMANY: FIXTURE}),
    )
    assert isinstance(response, DegradedResponse)
    [error] = response.meta.errors
    assert error.check == "retrieval"
    assert "3 of 5" in error.message and "country" in error.message


class _WrongParamsFetcher(FakeFetcher):
    """Reports the params of a different search than the one meta describes."""

    def fetch(self, filters: RetrievalFilters) -> FetchResult:
        result = super().fetch(filters)
        other = params_key(build_params(RetrievalFilters(condition="lung cancer"), 1000))
        return FetchResult(other, result.pages, result.records, result.total)


def test_meta_filters_that_were_not_sent_fail_conformance() -> None:
    response, _ = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        _WrongParamsFetcher({MELANOMA: FIXTURE}),
    )
    assert isinstance(response, DegradedResponse)
    assert {e.check for e in response.meta.errors} == {"conformance"}


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
    since_2021 = [
        t.model_copy(update={"start_date": "2022-01", "start_year": 2022}) for t in FIXTURE
    ]
    fetcher = FakeFetcher({RetrievalFilters(condition="melanoma", start_year=2021): since_2021})
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


def test_a_constraint_no_filter_expresses_asks_before_any_fetch() -> None:
    fetcher = FakeFetcher()
    plan = reply(
        condition="asthma",
        constraints=[
            constraint("asthma", "condition"),
            constraint("pediatric", None, "no filter for age group"),
        ],
        suggested="How are asthma trials distributed across phases?",
    )
    response, _ = run(
        "How are pediatric asthma trials distributed across phases?", [json_reply(plan)], fetcher
    )
    assert isinstance(response, ClarificationResponse)
    meta = response.meta
    assert meta.missing == [] and meta.conflicts == []
    assert [u.model_dump() for u in meta.unapplied] == [
        {"quote": "pediatric", "reason": "no filter for age group"}
    ]
    assert meta.suggested_query == "How are asthma trials distributed across phases?"
    assert meta.filters.stated == {"condition": "asthma"}
    assert fetcher.fetched == []


def test_two_values_for_one_filter_name_both_in_meta() -> None:
    plan = reply(
        condition="lung cancer",
        country="Japan",
        constraints=[constraint("Japan", "country"), constraint("Korea", "country")],
    )
    response, _ = run(
        "Lung cancer trials in Japan and Korea by phase", [json_reply(plan)], FakeFetcher()
    )
    assert isinstance(response, ClarificationResponse)
    assert [c.model_dump() for c in response.meta.conflicts] == [
        {"filter": "country", "quotes": ["Japan", "Korea"]}
    ]
    assert response.meta.suggested_query is None


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
            return FetchResult(
                params_key(build_params(filters, 1000)), [], [{"protocolSection": {}}] * 10, 10
            )

    with pytest.raises(DependencyError, match="unreadable"):
        run("Phases of melanoma trials", [json_reply(reply(condition="melanoma"))], Garbage())


def test_one_record_without_an_id_is_set_aside_not_fatal() -> None:
    trials = [
        make_trial(f"NCT{n:08d}", conditions=["Melanoma"], phases=["PHASE2"]) for n in range(1, 21)
    ]

    class OneBad(FakeFetcher):
        def fetch(self, filters: RetrievalFilters) -> FetchResult:
            records = [raw_record(t) for t in trials] + [{"protocolSection": {}}]
            return FetchResult(params_key(build_params(filters, 1000)), [], records, len(records))

    response, _ = run(
        "Phases of melanoma trials",
        [json_reply(reply(condition="melanoma")), json_reply(PROSE)],
        OneBad(),
    )
    assert isinstance(response, OkResponse)
    assert {e.rule: e.count for e in response.meta.excluded}.get("unreadable record") == 1


# --- the title call runs alongside retrieval (Phase 5.3 latency) ---

WAIT = 5.0  # seconds; a test that would hang fails with an assertion instead


def _is_title_call(request: httpx2.Request) -> bool:
    return bool(json.loads(request.content)["text"]["format"]["name"] == PROSE_SCHEMA_NAME)


def _scripted_llm(plan: dict[str, Any], on_title: Callable[[], httpx2.Response]) -> Any:
    """The plan reply, then `on_title()` for the title call, which may block to stall it."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return on_title() if _is_title_call(request) else json_reply(plan)

    return fake_llm(handler)


def _assert_threads_return_to(before: set[threading.Thread]) -> None:
    """Waits for the threads started since `before`: a global count would also see threads
    another test left finishing in the background, and flake."""
    deadline = time.monotonic() + WAIT
    while (started := set(threading.enumerate()) - before) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not started, "a title thread outlived its request"


def test_title_call_overlaps_the_fetch() -> None:
    # The fetch waits until the title call has started: run one after the other, this stalls.
    title_started = threading.Event()

    def title() -> httpx2.Response:
        title_started.set()
        return json_reply(PROSE)

    class AfterTitle(FakeFetcher):
        def fetch(self, filters: RetrievalFilters) -> FetchResult:
            assert title_started.wait(WAIT), "the title call did not start before the fetch"
            return super().fetch(filters)

    llm, _ = _scripted_llm(reply(condition="melanoma"), title)
    pipeline = Pipeline(llm, AfterTitle({MELANOMA: FIXTURE}), today=lambda: TODAY)
    response = pipeline.run(VisualizeRequest(query="Phases of melanoma trials"))
    assert isinstance(response, OkResponse)
    assert response.visualization.title == PROSE["title"]


NOT_OK = {
    "not found": (reply("time_trend.start_year", drug_name="Zorblaxumab"), FakeFetcher()),
    "nothing charted": (
        reply("geographic.country", condition="melanoma"),
        FakeFetcher({MELANOMA: [T3, make_trial("NCT00000099", conditions=["Melanoma"])]}),
    ),
    "upstream error": (
        reply(condition="melanoma"),
        FakeFetcher(error=UpstreamError("ClinicalTrials.gov HTTP 503")),
    ),
}


@pytest.mark.parametrize("case", NOT_OK)
def test_non_ok_answers_return_without_waiting_for_a_stalled_title_call(case: str) -> None:
    plan, fetcher = NOT_OK[case]
    release = threading.Event()
    before = set(threading.enumerate())

    def stalled() -> httpx2.Response:
        release.wait(WAIT)
        return json_reply(PROSE)

    llm, _ = _scripted_llm(plan, stalled)
    pipeline = Pipeline(llm, fetcher, today=lambda: TODAY)
    start = time.monotonic()
    try:
        response = pipeline.run(VisualizeRequest(query="q"))
    except DependencyError:
        response = None
    assert time.monotonic() - start < WAIT / 2, "a non-ok answer waited for the title"
    assert response is None or isinstance(response, NoResultsResponse)
    release.set()
    _assert_threads_return_to(before)


def test_ok_answer_waits_for_the_title_it_shows() -> None:
    def slow() -> httpx2.Response:
        time.sleep(0.2)
        return json_reply(PROSE)

    llm, _ = _scripted_llm(reply(condition="melanoma"), slow)
    response = Pipeline(llm, FakeFetcher({MELANOMA: FIXTURE}), today=lambda: TODAY).run(
        VisualizeRequest(query="Phases of melanoma trials")
    )
    assert isinstance(response, OkResponse)
    assert response.visualization.title == PROSE["title"]


@pytest.mark.parametrize(
    ("plan_replies", "fields"),
    [([reply()], {}), ([reply("distribution.investigator")] * 2, {"condition": "melanoma"})],
    ids=["clarification", "plan invalid twice"],
)
def test_no_title_call_starts_before_the_plan_is_valid(
    plan_replies: list[Any], fields: dict[str, Any]
) -> None:
    response, bodies = run("trials", [json_reply(p) for p in plan_replies], FakeFetcher(), **fields)
    assert isinstance(response, ClarificationResponse | DegradedResponse)
    assert [b["text"]["format"]["name"] for b in bodies] == [PLAN_SCHEMA_NAME] * len(plan_replies)


def test_a_bug_in_the_title_thread_surfaces_on_an_ok_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("title bug")

    monkeypatch.setattr("app.pipeline.write_prose", broken)
    with pytest.raises(RuntimeError, match="title bug"):
        run(
            "Phases of melanoma trials",
            [json_reply(reply(condition="melanoma"))],
            FakeFetcher({MELANOMA: FIXTURE}),
        )


def test_a_bug_in_an_abandoned_title_thread_is_logged_not_lost(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("title bug")

    monkeypatch.setattr("app.pipeline.write_prose", broken)
    response, _ = run(
        "Trials per year for Zorblaxumab",
        [json_reply(reply("time_trend.start_year", drug_name="Zorblaxumab"))],
        FakeFetcher(),
    )
    assert isinstance(response, NoResultsResponse)
    deadline = time.monotonic() + WAIT
    while "title bug" not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "title bug" in caplog.text
