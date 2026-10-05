"""The eval question set is coherent with the registry, the request contract and the plan rules.

These expectations are the planner's acceptance tests, so a wrong expectation would certify a wrong
planner. Each rule below comes from CLAUDE.md (§1 coverage, §7.2 plan shape, §7.3 stated vs
inferred, §7.8 anchor rule) or the assignment (§9 coverage), never from system output.
"""

from enum import StrEnum

import pytest
from pydantic import ValidationError

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.registry import REGISTRY, Dimension, Intent
from app.schemas import VisualizeRequest
from app.viz import VIZ_TYPE
from app.vocab import Phase, Status, label
from tests.eval_questions import EvalQuestion, load_questions

QUESTIONS = load_questions()
ANCHORS = ("drug_name", "condition", "sponsor")
ENUM_FILTERS: dict[str, type[StrEnum]] = {"trial_phase": Phase, "overall_status": Status}


def _ids(questions: list[EvalQuestion]) -> list[str]:
    return [q.id for q in questions]


def _registered_key(analysis: str) -> tuple[Intent, Dimension]:
    intent, _, dimension = analysis.partition(".")
    return Intent(intent), Dimension(dimension)


def _is_stated(question: EvalQuestion, key: str, value: str | int) -> bool:
    """§7.3: stated iff the value comes from a request field or appears verbatim in the query.
    An enum value also counts when its display label (e.g. "Phase 3") appears."""
    if question.request.get(key) == value:
        return True
    query = str(question.request["query"]).casefold()
    spellings = {str(value)}
    if key in ENUM_FILTERS:
        spellings.add(label(ENUM_FILTERS[key](str(value))))
    return any(s.casefold() in query for s in spellings)


def test_set_size_and_unique_ids() -> None:
    assert 20 <= len(QUESTIONS) <= 30
    assert len(set(_ids(QUESTIONS))) == len(QUESTIONS)


def test_every_question_class_is_covered() -> None:
    covered = {q.question_class for q in QUESTIONS}
    assert covered == {*(i.value for i in Intent), "edge_case"}


def test_every_viz_type_is_expected_somewhere() -> None:
    expected = {q.expected.viz_type for q in QUESTIONS if q.expected.status == "ok"}
    assert expected == set(VIZ_TYPE.values())


def test_every_appendix_example_is_present() -> None:
    assert sum(q.source == "appendix" for q in QUESTIONS) >= 9


@pytest.mark.parametrize("question", QUESTIONS, ids=_ids(QUESTIONS))
def test_request_validity_matches_expected_http(question: EvalQuestion) -> None:
    if question.expected.http == 422:
        assert question.expected.status is None
        with pytest.raises(ValidationError):
            VisualizeRequest.model_validate(question.request)
    else:
        assert question.expected.status is not None
        VisualizeRequest.model_validate(question.request)


@pytest.mark.parametrize("question", QUESTIONS, ids=_ids(QUESTIONS))
def test_analysis_is_registered_and_fixes_the_viz_type(question: EvalQuestion) -> None:
    expected = question.expected
    if expected.analysis is None:
        assert expected.status != "ok" and expected.viz_type is None
        return
    intent, dimension = _registered_key(expected.analysis)
    aggregator = REGISTRY.get(intent, dimension)
    assert expected.viz_type == VIZ_TYPE[aggregator.shape]
    if question.question_class != "edge_case":
        assert intent.value == question.question_class


@pytest.mark.parametrize("question", QUESTIONS, ids=_ids(QUESTIONS))
def test_cohorts_follow_the_plan_rule(question: EvalQuestion) -> None:
    """§7.2: comparisons take 2-4 cohorts, each one entity override; nothing else has cohorts."""
    expected = question.expected
    is_comparison = expected.analysis is not None and expected.analysis.startswith("comparison.")
    if not is_comparison:
        assert expected.cohorts is None
        return
    assert expected.cohorts is not None and 2 <= len(expected.cohorts) <= 4
    assert len({c.label for c in expected.cohorts}) == len(expected.cohorts)
    assert len({c.entity for c in expected.cohorts}) == 1


@pytest.mark.parametrize("question", QUESTIONS, ids=_ids(QUESTIONS))
def test_stated_and_inferred_follow_the_definition(question: EvalQuestion) -> None:
    expected = question.expected
    for key, value in expected.stated.items():
        assert _is_stated(question, key, value), f"{key}={value!r} is not stated by §7.3"
    for key, values in expected.inferred.items():
        assert values, f"{key} lists no acceptable value"
        assert not any(_is_stated(question, key, v) for v in values), f"{key} is stated"
    assert not expected.stated.keys() & expected.inferred.keys()


@pytest.mark.parametrize("question", QUESTIONS, ids=_ids(QUESTIONS))
def test_anchor_rule(question: EvalQuestion) -> None:
    """§7.8: `missing` lists the anchors iff no anchor is named; every `ok` has an anchor."""
    expected = question.expected
    cohort_anchor = bool(expected.cohorts)
    has_anchor = cohort_anchor or any(k in expected.stated for k in ANCHORS)
    if expected.missing:
        assert expected.status == "clarification_needed" and not has_anchor
        assert set(expected.missing) == set(ANCHORS)
    if expected.status in ("ok", "no_results"):
        assert has_anchor


@pytest.mark.parametrize("question", QUESTIONS, ids=_ids(QUESTIONS))
def test_status_specific_fields(question: EvalQuestion) -> None:
    expected = question.expected
    if expected.not_found:
        assert expected.status == "no_results"
    if expected.field_override:
        assert expected.status == "ok"
