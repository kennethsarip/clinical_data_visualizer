"""LLM title and notes (CLAUDE.md §7.2): written from the plan, never from row values; a title with
a number not in the filters, or any failed call, falls back to the plain title and stays `ok`."""

from typing import Any

import httpx2

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.registry import REGISTRY, Dimension, Intent
from app.schemas import Filters, RetrievalFilters
from app.viz import PROSE_FALLBACK_NOTE, Prose, default_title, write_prose
from tests.factories import FIXTURE, cohort
from tests.llm_fakes import fake_llm, json_reply, replies, text_reply

QUERY = "How has the number of trials for pembrolizumab changed per year since 2015?"
TREND = REGISTRY.get(Intent.TIME_TREND, Dimension.START_YEAR)
FILTERS = RetrievalFilters(drug_name="pembrolizumab", start_year=2015)
COHORTS = [cohort(FIXTURE, filters=FILTERS)]
STATED = Filters.model_validate(
    {"stated": {"drug_name": "pembrolizumab", "start_year": 2015}, "inferred": {}}
)


def _write(*responses: httpx2.Response, **kwargs: Any) -> tuple[Prose, list[dict[str, Any]]]:
    llm, bodies = fake_llm(replies(*responses))
    args: dict[str, Any] = {
        "query": QUERY,
        "aggregator": TREND,
        "cohorts": COHORTS,
        "filters": STATED,
    }
    return write_prose(llm, **(args | kwargs)), bodies


def _fallback() -> Prose:
    return Prose(default_title(TREND, COHORTS), (PROSE_FALLBACK_NOTE,))


def test_valid_title_and_notes_are_used() -> None:
    notes = ["Counts trials listing pembrolizumab as an intervention."]
    prose, _ = _write(
        json_reply({"title": "Pembrolizumab Trials Started per Year", "notes": notes})
    )
    assert prose == Prose("Pembrolizumab Trials Started per Year", tuple(notes))


def test_title_call_uses_the_prose_effort_not_the_planner_effort() -> None:
    _, bodies = _write(json_reply({"title": "T", "notes": []}))
    assert bodies[0]["reasoning"] == {"effort": "none"}  # fake_llm: planner "low", prose "none"


def test_request_carries_the_plan_but_no_row_values() -> None:
    _, bodies = _write(json_reply({"title": "T", "notes": []}))
    sent = bodies[0]["input"]
    for expected in (QUERY, "time_trend.start_year", "time_series", "start_year", "pembrolizumab"):
        assert expected in sent
    for trial in FIXTURE:  # rows are never shown: no trial IDs, titles or start years
        assert trial.nct_id not in sent and trial.brief_title not in sent


def test_comparison_request_names_its_cohorts() -> None:
    comparison = REGISTRY.get(Intent.COMPARISON, Dimension.PHASE)
    cohorts = [
        cohort(FIXTURE[:3], label="Keytruda", filters=RetrievalFilters(drug_name="pembrolizumab")),
        cohort(FIXTURE[3:], label="Opdivo", filters=RetrievalFilters(drug_name="nivolumab")),
    ]
    _, bodies = _write(
        json_reply({"title": "T", "notes": []}),
        aggregator=comparison,
        cohorts=cohorts,
        filters=Filters(stated={}, inferred={}),
    )
    assert "Keytruda" in bodies[0]["input"] and "Opdivo" in bodies[0]["input"]


def test_number_from_the_filters_is_allowed_in_the_title() -> None:
    prose, _ = _write(
        json_reply({"title": "Pembrolizumab Trials per Year Since 2015", "notes": []})
    )
    assert prose.title == "Pembrolizumab Trials per Year Since 2015"


def test_title_with_a_number_not_in_the_filters_falls_back() -> None:
    prose, _ = _write(json_reply({"title": "1,204 Pembrolizumab Trials Since 2015", "notes": []}))
    assert prose == _fallback()


def test_note_with_a_number_not_in_the_filters_is_dropped() -> None:
    notes = ["About 300 trials started in 2020.", "Counts each trial once, by its start date."]
    prose, _ = _write(json_reply({"title": "Pembrolizumab Trials per Year", "notes": notes}))
    assert prose.notes == ("Counts each trial once, by its start date.",)


def test_malformed_answer_falls_back_without_a_retry() -> None:
    prose, bodies = _write(text_reply("not json"))
    assert prose == _fallback()
    assert len(bodies) == 1


def test_upstream_failure_falls_back() -> None:
    prose, _ = _write(httpx2.Response(500, json={"error": {"message": "down", "type": "server"}}))
    assert prose == _fallback()


def test_fallback_title_passes_the_number_rule() -> None:
    assert not any(ch.isdigit() for ch in _fallback().title)
