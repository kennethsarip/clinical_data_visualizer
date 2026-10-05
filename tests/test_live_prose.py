"""Live title-and-notes check (`-m live`, needs `.env`): for each `ok` eval question, the real LLM
writes a title that passes the number rule without falling back, and no note survives with a stray
number. Rows are not needed (the prose step never sees them), so cohorts carry no trials."""

from datetime import date

import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.registry import REGISTRY, CohortTrials
from app.config import load_settings
from app.llm import LLMClient
from app.normalize import NormalizedBatch
from app.planner import QueryPlan, plan_request
from app.schemas import Filters, VisualizeRequest
from app.viz import PROSE_FALLBACK_NOTE, write_prose
from tests.eval_questions import EvalQuestion, load_questions

pytestmark = pytest.mark.live

TODAY = date(2026, 10, 4)
OK = [q for q in load_questions() if q.expected.status == "ok"]
EMPTY = NormalizedBatch([], {}, [])


@pytest.fixture(scope="module")
def llm() -> LLMClient:
    return LLMClient.from_settings(load_settings())


def _cohorts(plan: QueryPlan) -> list[CohortTrials]:
    if plan.cohorts:
        return [CohortTrials(c.label, EMPTY, c.filters, 0) for c in plan.cohorts]
    return [CohortTrials(None, EMPTY, plan.filters, 0)]


@pytest.mark.parametrize("question", OK, ids=[q.id for q in OK])
def test_llm_title_passes_without_fallback(question: EvalQuestion, llm: LLMClient) -> None:
    request = VisualizeRequest.model_validate(question.request)
    plan = plan_request(request, llm, today=TODAY)
    assert isinstance(plan, QueryPlan), plan
    filters = Filters.model_validate({"stated": plan.stated, "inferred": plan.inferred})
    prose = write_prose(
        llm,
        query=request.query,
        aggregator=REGISTRY.get(plan.intent, plan.dimension),
        cohorts=_cohorts(plan),
        filters=filters,
    )
    assert PROSE_FALLBACK_NOTE not in prose.notes, prose
    assert prose.title and len(prose.title) <= 120
