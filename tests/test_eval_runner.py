"""The Phase 5 eval runner (CLAUDE.md §9, §14 Phase 5 step 2), offline: the real pipeline with a
fake LLM and fetcher, scored against expectations written here from §1, §7.7 and SCHEMAS.md."""

from collections.abc import Callable, Iterator
from datetime import date
from typing import Any, cast

import httpx2
import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.registry import RowShape
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
    off_filter_metrics,
    run_all,
    run_question,
    summarize,
)
from tests.factories import FIXTURE, make_trial, raw_record
from tests.llm_fakes import fake_llm, json_reply, replies
from tests.test_contract import _network_example, _ok_example
from tests.test_pipeline import PROSE, FakeFetcher
from tests.test_planner import cohort, reply

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
    since_2021 = [
        t.model_copy(update={"start_date": "2021-03", "start_year": 2021}) for t in FIXTURE
    ]
    fetcher = FakeFetcher({RetrievalFilters(condition="melanoma", start_year=2021): since_2021})
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


# --- off-filter (Phase 6 step 0) ---
# Expected counts are worked out by hand from each record against the filter's meaning in §8.4.


def _filtered(stated: dict[str, Any], inferred: dict[str, Any] | None = None) -> OkResponse:
    body = _ok_example()
    body["meta"]["filters"] = {"stated": stated, "inferred": inferred or {}}
    return ok_response(meta=body["meta"])


def _charted(response: OkResponse) -> list[str]:
    return sorted({n for row in response.visualization.data for n in row.nct_ids})  # type: ignore[union-attr]


def _records(fields: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """One raw record per charted trial of the ok example; `fields` overrides by NCT ID."""
    ids = _charted(_filtered({}))
    return {n: raw_record(make_trial(n, **(fields or {}).get(n, {}))) for n in ids}


def test_entity_filters_are_searches_so_nothing_is_checked_against_them() -> None:
    m = off_filter_metrics(_filtered({"drug_name": "Pembrolizumab"}), _records())
    assert (m.trials_checked, m.off_filter, m.by_filter) == (len(_charted(_filtered({}))), 0, {})


def test_a_country_filter_needs_a_site_in_that_country() -> None:
    ids = _charted(_filtered({}))
    records = _records(
        {
            ids[0]: {"countries": ["Japan", "China"]},
            ids[1]: {"countries": ["China"]},  # the Beijing hospital case
            ids[2]: {"countries": []},  # no locations
        }
    )
    m = off_filter_metrics(_filtered({"country": "japan"}), records)
    assert (m.off_filter, m.by_filter) == (len(ids) - 1, {"country": len(ids) - 1})


def test_a_variant_country_name_is_off_filter_because_records_use_registry_names() -> None:
    ids = _charted(_filtered({}))
    records = _records({n: {"countries": ["South Korea"]} for n in ids})
    m = off_filter_metrics(_filtered({}, {"country": "Korea"}), records)
    assert m.off_filter == len(ids)


def test_phase_status_and_year_filters() -> None:
    ids = _charted(_filtered({}))
    good: dict[str, Any] = {
        "phases": ["PHASE1", "PHASE2"],
        "overall_status": "RECRUITING",
        "start_date": "2016-05",
    }
    off = good | {"phases": ["PHASE3"], "start_date": "2014-12-31"}
    records = _records({n: good for n in ids[1:]} | {ids[0]: off})
    stated = {"trial_phase": "PHASE2", "start_year": 2015, "end_year": 2016}
    m = off_filter_metrics(_filtered(stated, {"overall_status": "RECRUITING"}), records)
    assert (m.off_filter, m.by_filter) == (1, {"trial_phase": 1, "start_year": 1})
    late = _records({n: good | {"start_date": "2017-01"} for n in ids})
    m = off_filter_metrics(_filtered(stated), late)
    assert m.by_filter == {"end_year": len(ids)}
    stopped = _records({n: good | {"overall_status": "COMPLETED"} for n in ids})
    m = off_filter_metrics(_filtered({}, {"overall_status": "RECRUITING"}), stopped)
    assert m.by_filter == {"overall_status": len(ids)}


def test_a_year_filter_is_not_met_by_a_trial_with_no_start_date() -> None:
    ids = _charted(_filtered({}))
    m = off_filter_metrics(_filtered({"start_year": 2015}), _records())
    assert m.by_filter == {"start_year": len(ids)}


def test_a_charted_trial_missing_from_the_records_is_off_filter() -> None:
    records = _records()
    records.pop(_charted(_filtered({}))[0])
    m = off_filter_metrics(_filtered({}), records)
    assert (m.off_filter, m.by_filter) == (1, {"no_record": 1})


class _ChartsOffFilter:
    """A pipeline with a conformance bug: it charts the ok example's trials under a Germany filter
    although only one of them has a site there. The runner must catch it from raw records alone,
    since the real pipeline now drops such trials (Phase 6 step 4)."""

    def __init__(self, checker: Checker) -> None:
        self.checker = checker

    def run(self, request: Any) -> OkResponse:
        response = _filtered({"drug_name": "Pembrolizumab", "country": "Germany"})
        first = _charted(response)[0]
        records = _records({first: {"countries": ["Germany"]}})  # the rest list no sites
        self.checker(response, CheckContext(RowShape.CATEGORICAL, records))
        return response


def test_an_off_filter_trial_fails_the_question() -> None:
    expected = question(
        {"query": "Phases of pembrolizumab trials in Germany"},
        status="ok",
        analysis="distribution.phase",
        viz_type="bar_chart",
        stated={"drug_name": "Pembrolizumab", "country": "Germany"},
    )
    make = cast(Callable[[Checker], Pipeline], _ChartsOffFilter)
    result = run_question(expected, make, clock=clock(0.0, 1.0), inner=lambda r, c: [])
    charted = len(_charted(_filtered({})))
    assert result.off_filter is not None
    assert (result.off_filter.trials_checked, result.off_filter.off_filter) == (
        charted,
        charted - 1,
    )
    assert result.failures == ["off_filter"]
    assert run_phases().off_filter is not None and run_phases().off_filter.off_filter == 0  # type: ignore[union-attr]


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


def test_summary_totals_trials_checked_and_off_filter() -> None:
    results = [
        _result(
            "a",
            "geographic",
            True,
            1.0,
            [],
            off_filter={"trials_checked": 10, "off_filter": 0, "by_filter": {}},
        ),
        _result(
            "b",
            "distribution",
            False,
            1.0,
            ["off_filter"],
            off_filter={"trials_checked": 336, "off_filter": 9, "by_filter": {"country": 9}},
        ),
        _result("c", "edge_case", True, 1.0, []),
    ]
    s = summarize(results)
    assert (s.off_filter_trials_checked, s.off_filter_trials) == (346, 9)


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


# --- found reviewing the runner (2026-10-05) ---


def test_an_extra_cohort_is_a_mismatch() -> None:
    drugs = ["pembrolizumab", "nivolumab", "ipilimumab"]
    q = question(
        {"query": "Compare phases for pembrolizumab vs nivolumab vs ipilimumab"},
        "comparison",
        status="ok",
        analysis="comparison.phase",
        viz_type="grouped_bar_chart",
        cohorts=[cohort("pembrolizumab") | {"entity": "drug_name"}, cohort("nivolumab")],
    )
    plan = reply("comparison.phase", [cohort(d) for d in drugs])
    fetcher = FakeFetcher({RetrievalFilters(drug_name=d): FIXTURE for d in drugs})
    pipeline = factory([json_reply(plan), json_reply(PROSE)], fetcher)
    assert "wrong_cohorts" in run_question(q, pipeline, clock=clock(0, 1)).failures


def test_an_inferred_value_compares_case_insensitively_like_a_stated_one() -> None:
    q = question(
        {"query": "melanoma trials that are enrolling now"},
        status="ok",
        analysis="distribution.phase",
        viz_type="bar_chart",
        stated={"condition": "melanoma"},
        inferred={"overall_status": ["recruiting"]},
    )
    plan = reply(condition="melanoma", overall_status="RECRUITING")
    filters = RetrievalFilters(condition="melanoma", overall_status="RECRUITING")
    recruiting = [t for t in FIXTURE if t.overall_status == "RECRUITING"]
    pipeline = factory([json_reply(plan), json_reply(PROSE)], FakeFetcher({filters: recruiting}))
    assert run_question(q, pipeline, clock=clock(0, 1)).failures == []


def test_latency_summary_skips_requests_rejected_before_any_work() -> None:
    results = [
        _result("a", "numeric", True, 4.0, []),
        _result("b", "numeric", True, 6.0, []),
        _result("c", "edge_case", True, 0.0, [], http=422, status=None),
    ]
    s = summarize(results)
    assert (s.latency_p50_s, s.latency_max_s) == (5.0, 6.0)


def test_a_crash_is_recorded_and_the_run_goes_on() -> None:
    fetcher = FakeFetcher(error=RuntimeError("bad row"))
    pipeline = factory([json_reply(reply(condition="melanoma"))], fetcher)
    result = run_question(PHASES, pipeline, clock=clock(0, 1))
    assert (result.http, result.failures) == (500, ["crash"])
    assert result.error == "RuntimeError('bad row')"


def test_a_request_that_should_be_rejected_but_is_not() -> None:
    q = PHASES.model_copy(
        update={"expected": PHASES.expected.model_copy(update={"http": 422, "status": None})}
    )
    result = run_phases(q)
    assert (result.http, result.failures) == (200, ["wrong_http"])
