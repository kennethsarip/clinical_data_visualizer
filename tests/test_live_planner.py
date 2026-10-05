"""Live planner acceptance (`-m live`, needs `.env`): the real LLM plus the rules, against every
eval expectation written before the planner (CLAUDE.md §14 Phase 3). One test per question, so a
run shows exactly which questions the prompt gets wrong. Names compare case-insensitively."""

from collections.abc import Mapping
from datetime import date

import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.config import load_settings
from app.llm import LLMClient
from app.planner import Clarification, QueryPlan, plan_request
from app.schemas import FilterKey, VisualizeRequest
from eval.questions import EvalQuestion, load_questions
from tests.eval_pending import eval_params

pytestmark = pytest.mark.live

TODAY = date(2026, 10, 4)  # the date the expectations were written (relative years)
PLANNED = [q for q in load_questions() if q.expected.http == 200]


@pytest.fixture(scope="module")
def llm() -> LLMClient:
    return LLMClient.from_settings(load_settings())


def _fold(values: Mapping[FilterKey, str | int]) -> dict[str, str]:
    return {k: str(v).casefold() for k, v in values.items()}


@pytest.mark.parametrize("question", eval_params(PLANNED))
def test_planner_meets_the_eval_expectation(question: EvalQuestion, llm: LLMClient) -> None:
    e = question.expected
    result = plan_request(VisualizeRequest.model_validate(question.request), llm, today=TODAY)
    if e.status == "clarification_needed":
        assert isinstance(result, Clarification), result
        assert result.missing == tuple(e.missing)
        return
    assert isinstance(result, QueryPlan), result
    assert result.analysis == e.analysis
    assert _fold(result.stated) == _fold(e.stated)
    assert result.inferred.keys() == e.inferred.keys()
    for key, value in result.inferred.items():
        assert value in e.inferred[key]
    if e.cohorts:
        got = [
            (c.label.casefold(), str(getattr(c.filters, x.entity)).casefold())
            for c, x in zip(result.cohorts, e.cohorts, strict=True)
        ]
        assert got == [(x.label.casefold(), x.value.casefold()) for x in e.cohorts]
    assert bool(result.notes) == e.field_override
