"""The Phase 5 eval runner (CLAUDE.md §9, §14 Phase 5 step 2), offline: the real pipeline with a
fake LLM and fetcher, scored against expectations written here from §1, §7.7 and SCHEMAS.md."""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import httpx2
import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.checks import CheckContext
from app.ctgov import UpstreamError
from app.pipeline import Pipeline
from app.schemas import RESPONSE_ADAPTER, CheckError, OkResponse, RetrievalFilters
from eval.questions import EvalQuestion
from eval.runner import (
    Checker,
    QuestionResult,
    RunMeta,
    RunResult,
    citation_metrics,
    network_metrics,
    run_all,
    run_question,
    summarize,
)
from tests.factories import FIXTURE
from tests.llm_fakes import fake_llm, json_reply, replies
from tests.test_contract import _network_example, _ok_example
from tests.test_pipeline import PROSE, FakeFetcher
from tests.test_planner import reply

TODAY = date(2026, 10, 4)
MELANOMA = RetrievalFilters(condition="melanoma")


def question(
    request: dict[str, Any], question_class: str = "distribution", **expected: Any
) -> EvalQuestion:
    return EvalQuestion.model_validate(
        {
            "id": "q",
            "question_class": question_class,
            "source": "extension",
            "request": request,
            "expected": expected,
            "why": "test",
        }
    )


PHASES = question(
    {"query": "Phases of melanoma trials"},
    status="ok",
    analysis="distribution.phase",
    viz_type="bar_chart",
    stated={"condition": "Melanoma"},  # stated values compare case-insensitively
)


def factory(
    llm_replies: list[httpx2.Response], fetcher: FakeFetcher
) -> Callable[[Checker], Pipeline]:
    llm, _ = fake_llm(replies(*llm_replies))
    return lambda checker: Pipeline(llm, fetcher, checker=checker, today=lambda: TODAY)


def clock(*ticks: float) -> Callable[[], float]:
    values: Iterator[float] = iter(ticks)
    return lambda: next(values)


def run_phases(
    expected: EvalQuestion = PHASES,
    inner: Checker | None = None,
    plan: dict[str, Any] | None = None,
) -> QuestionResult:
    pipeline = factory(
        [json_reply(plan or reply(condition="melanoma")), json_reply(PROSE)],
        FakeFetcher({MELANOMA: FIXTURE}),
    )
    kwargs = {"inner": inner} if inner else {}
    return run_question(expected, pipeline, clock=clock(10.0, 12.5), **kwargs)


# --- one question ---


def test_a_question_that_meets_its_expectation_passes() -> None:
    result = run_phases()
    assert result.passed and result.failures == []
    assert (result.http, result.status) == (200, "ok")
    assert (result.analysis, result.viz_type) == ("distribution.phase", "bar_chart")
    assert (result.records_fetched, result.records_total, result.capped) == (5, 5, False)
    assert result.latency_s == 2.5
    assert (result.check_attempts, result.repaired, result.failed_checks) == (1, False, [])
    assert result.prose_fallback is False
    assert result.citations is not None and result.citations.items > 0
    assert result.citations.excerpts_passed == result.citations.citations > 0
    assert result.network is None


def test_each_mismatch_is_named() -> None:
    wrong = question(
        PHASES.request,
        status="ok",
        analysis="time_trend.start_year",
        viz_type="time_series",
        stated={"condition": "melanoma", "sponsor": "Merck"},
        capped=True,
    )
    result = run_phases(wrong)
    assert not result.passed
    assert result.failures == ["wrong_analysis", "wrong_viz_type", "wrong_stated", "cap_mismatch"]


def test_an_inferred_value_must_be_one_of_the_accepted() -> None:
    plan = reply(condition="melanoma", start_year=2021)
    ok = question(
        PHASES.request,
        status="ok",
        analysis="distribution.phase",
        viz_type="bar_chart",
        stated={"condition": "melanoma"},
        inferred={"start_year": [2021, 2022]},
    )
    narrow = ok.model_copy(
        update={"expected": ok.expected.model_copy(update={"inferred": {"start_year": [2020]}})}
    )
    fetcher = FakeFetcher({RetrievalFilters(condition="melanoma", start_year=2021): FIXTURE})
    for q, failures in ((ok, []), (narrow, ["wrong_inferred"])):
        pipeline = factory([json_reply(plan), json_reply(PROSE)], fetcher)
        assert run_question(q, pipeline, clock=clock(0, 1)).failures == failures


def test_a_repair_is_recorded_but_still_passes() -> None:
    calls = []

    def fails_once(response: OkResponse, context: CheckContext) -> list[CheckError]:
        calls.append(response)
        return [CheckError(check="title", message="stray number")] if len(calls) == 1 else []

    result = run_phases(inner=fails_once)
    assert result.passed
    assert (result.check_attempts, result.repaired, result.failed_checks) == (2, True, ["title"])


def test_degraded_names_the_failing_checks() -> None:
    def always(response: OkResponse, context: CheckContext) -> list[CheckError]:
        return [
            CheckError(check="excerpts", message="x"),
            CheckError(check="excerpts", message="y"),
        ]

    result = run_phases(inner=always)
    assert result.status == "degraded"
    assert result.failures == ["wrong_status"]
    assert (result.check_attempts, result.repaired, result.failed_checks) == (
        2,
        False,
        ["excerpts"],
    )


def test_a_request_rejected_before_planning_is_http_422() -> None:
    q = question(
        {"query": "melanoma phases", "start_year": 2024, "end_year": 2020},
        "edge_case",
        http=422,
        status=None,
        analysis=None,
        viz_type=None,
    )

    def never(checker: Checker) -> Pipeline:
        raise AssertionError("a rejected request must not reach the pipeline")

    result = run_question(q, never, clock=clock(0, 0))
    assert result.passed and (result.http, result.status) == (422, None)


def test_a_dependency_failure_is_http_502() -> None:
    fetcher = FakeFetcher(error=UpstreamError("timeout"))
    pipeline = factory([json_reply(reply(condition="melanoma"))], fetcher)
    result = run_question(PHASES, pipeline, clock=clock(0, 1))
    assert (result.http, result.status, result.failures) == (502, None, ["dependency_error"])
    assert result.error is not None and "timeout" in result.error


def test_not_found_names_compare_case_insensitively() -> None:
    q = question(
        {"query": "Phases of zorblaxumab trials"},
        "edge_case",
        status="no_results",
        analysis="distribution.phase",
        viz_type=None,
        stated={"drug_name": "zorblaxumab"},
        not_found=["Zorblaxumab"],
    )
    pipeline = factory([json_reply(reply(drug_name="zorblaxumab"))], FakeFetcher())
    result = run_question(q, pipeline, clock=clock(0, 1))
    assert result.passed, result.failures
    assert result.status == "no_results" and result.citations is None


def test_clarification_compares_the_missing_anchors() -> None:
    q = question(
        {"query": "show me trials"},
        "edge_case",
        status="clarification_needed",
        analysis=None,
        viz_type=None,
        missing=["condition"],
    )
    pipeline = factory([json_reply(reply())], FakeFetcher())
    result = run_question(q, pipeline, clock=clock(0, 1))
    assert result.failures == ["wrong_missing"]


def test_a_field_override_needs_its_note() -> None:
    q = question(
        {"query": "Phases of melanoma trials", "condition": "glioma"},
        status="ok",
        analysis="distribution.phase",
        viz_type="bar_chart",
        stated={"condition": "glioma"},
        field_override=True,
    )
    fetcher = FakeFetcher({RetrievalFilters(condition="glioma"): FIXTURE})
    pipeline = factory([json_reply(reply(condition="melanoma")), json_reply(PROSE)], fetcher)
    assert run_question(q, pipeline, clock=clock(0, 1)).failures == []
    no_override = q.model_copy(
        update={"request": {"query": "Phases of glioma trials", "condition": "glioma"}}
    )
    pipeline = factory([json_reply(reply(condition="glioma")), json_reply(PROSE)], fetcher)
    assert run_question(no_override, pipeline, clock=clock(0, 1)).failures == [
        "missing_override_note"
    ]


# --- metrics ---


def _phases(nct_id: str, *phases: str) -> dict[str, Any]:
    return {"protocolSection": {"designModule": {"phases": list(phases)} if phases else {}}}


RECORDS = {
    "NCT00000003": _phases("NCT00000003", "PHASE1", "PHASE2"),
    "NCT00000002": _phases("NCT00000002", "PHASE3"),
    "NCT00000001": _phases("NCT00000001", "PHASE2"),  # no longer supports its PHASE3 excerpt
    "NCT00000004": _phases("NCT00000004"),
}


def ok_response(**changes: Any) -> OkResponse:
    body = _ok_example() | changes
    response = RESPONSE_ADAPTER.validate_python(body)
    assert isinstance(response, OkResponse)
    return response


def test_citation_metrics_count_fully_cited_items_and_passing_excerpts() -> None:
    m = citation_metrics(ok_response(), RECORDS)
    assert (m.items, m.fully_cited, m.citations, m.excerpts_passed) == (3, 3, 5, 4)


def test_a_row_citing_fewer_trials_than_it_holds_is_not_fully_cited() -> None:
    body = _ok_example()
    body["visualization"]["data"][1]["citations"] = body["visualization"]["data"][1]["citations"][
        :1
    ]
    m = citation_metrics(ok_response(visualization=body["visualization"]), RECORDS)
    assert (m.items, m.fully_cited) == (3, 2)


def test_the_citation_cap_bounds_what_fully_cited_means() -> None:
    body = _ok_example()
    body["meta"]["citation_cap"] = 1
    body["visualization"]["data"][1]["citations"] = body["visualization"]["data"][1]["citations"][
        :1
    ]
    m = citation_metrics(ok_response(meta=body["meta"]), RECORDS)
    assert m.fully_cited == 3


def test_an_empty_bucket_has_nothing_to_cite() -> None:
    body = _ok_example()
    body["visualization"]["data"].append(
        {"phase": "Phase 4", "trial_count": 0, "nct_ids": [], "citations": []}
    )
    m = citation_metrics(ok_response(visualization=body["visualization"]), RECORDS)
    assert m.items == 3


def test_network_metrics_read_pruning_and_drug_exclusions() -> None:
    body = _ok_example()
    body["visualization"] = _network_example()
    body["meta"]["pruning"] = {
        "min_edge_weight": 1,
        "top_n_nodes": 50,
        "fallback_used": True,
        "nodes_removed": 7,
        "edges_removed": 9,
    }
    body["meta"]["excluded"] = [
        {"rule": "placebo", "count": 3},
        {"rule": "non-drug intervention", "count": 5},
        {"rule": "no drug intervention", "count": 2},
        {"rule": "no locations", "count": 4},
    ]
    m = network_metrics(ok_response(**body))
    assert m is not None
    assert (m.nodes, m.edges, m.fallback_used, m.nodes_removed, m.edges_removed) == (
        2,
        1,
        True,
        7,
        9,
    )
    assert (m.placebo_excluded, m.non_drug_excluded, m.no_drug_excluded) == (3, 5, 2)
    assert network_metrics(ok_response()) is None


# --- summary ---


def _result(
    id: str, cls: str, passed: bool, latency: float, failures: list[str], **extra: Any
) -> QuestionResult:
    return QuestionResult.model_validate(
        {
            "id": id,
            "question_class": cls,
            "passed": passed,
            "failures": failures,
            "http": 200,
            "status": "ok",
            "analysis": None,
            "viz_type": None,
            "records_fetched": 0,
            "records_total": 0,
            "capped": False,
            "latency_s": latency,
            "check_attempts": 1,
            "repaired": False,
            "failed_checks": [],
            "prose_fallback": False,
            "citations": None,
            "network": None,
            "error": None,
        }
        | extra
    )


def test_summary_rolls_up_by_class_failure_mode_and_latency() -> None:
    cited = {"items": 4, "fully_cited": 3, "citations": 10, "excerpts_passed": 9}
    results = [
        _result("a", "distribution", True, 1.0, [], citations=cited),
        _result(
            "b", "distribution", False, 3.0, ["wrong_analysis", "wrong_viz_type"], repaired=True
        ),
        _result("c", "network", False, 2.0, ["wrong_analysis"], citations=cited),
        _result("d", "network", True, 4.0, [], prose_fallback=True),
    ]
    s = summarize(results)
    assert (s.questions, s.passed) == (4, 2)
    assert s.by_class == {"distribution": [1, 2], "network": [1, 2]}
    assert s.failure_modes == {"wrong_analysis": 2, "wrong_viz_type": 1}
    assert (s.repaired, s.prose_fallbacks) == (1, 1)
    assert (s.latency_p50_s, s.latency_max_s) == (2.5, 4.0)
    assert (s.items_fully_cited, s.items) == (6, 8)
    assert (s.excerpts_passed, s.citations) == (18, 20)


@pytest.mark.parametrize("latencies,p50", [([5.0], 5.0), ([1.0, 9.0, 2.0], 2.0)])
def test_median_latency(latencies: list[float], p50: float) -> None:
    results = [_result(str(i), "numeric", True, x, []) for i, x in enumerate(latencies)]
    assert summarize(results).latency_p50_s == p50


# --- a whole run ---


def test_a_run_scores_every_question_in_order_and_summarizes() -> None:
    questions = [PHASES, PHASES.model_copy(update={"id": "q2", "question_class": "network"})]
    fetcher = FakeFetcher({MELANOMA: FIXTURE})
    llm, _ = fake_llm(replies(*[json_reply(reply(condition="melanoma")), json_reply(PROSE)] * 2))
    meta = RunMeta(
        started_at="2026-10-05T12:00:00+00:00",
        git_commit="abc1234",
        model="m",
        reasoning_effort="medium",
        fetch_cap=2000,
        today=TODAY,
        questions_written="2026-10-04",
    )
    run = run_all(
        questions,
        lambda checker: Pipeline(llm, fetcher, checker=checker, today=lambda: TODAY),
        meta,
    )
    assert [r.id for r in run.results] == ["q", "q2"]
    assert run.meta == meta
    assert run.summary.by_class == {"distribution": [1, 1], "network": [1, 1]}
    assert RunResult.model_validate_json(run.model_dump_json()) == run
