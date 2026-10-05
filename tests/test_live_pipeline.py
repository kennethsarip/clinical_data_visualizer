"""Live end to end (`-m live`, needs `.env` and the Compose Postgres): every plannable eval question
through the real LLM, ClinicalTrials.gov and the cache, against the expectations written before
the code. This is the Phase 3 "Done when": each §1 class returns `ok` with every check passing
(a failing check would surface as `degraded`), and each §7.8 case returns its behavior."""

from datetime import date

import psycopg
import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.cache import TrialCache
from app.config import load_settings
from app.ctgov import CtgovClient
from app.llm import LLMClient
from app.migrate import apply_migrations
from app.pipeline import Pipeline
from app.schemas import (
    ClarificationResponse,
    NoResultsResponse,
    OkResponse,
    VisualizeRequest,
)
from tests.eval_questions import EvalQuestion, load_questions

pytestmark = pytest.mark.live

TODAY = date(2026, 10, 4)
PLANNED = [q for q in load_questions() if q.expected.http == 200]


@pytest.mark.parametrize("question", PLANNED, ids=[q.id for q in PLANNED])
def test_pipeline_meets_the_eval_expectation(
    question: EvalQuestion, db: psycopg.Connection
) -> None:
    apply_migrations(db)
    settings = load_settings()
    cache = TrialCache(db, CtgovClient.from_settings(settings), settings.cache_ttl_hours)
    pipeline = Pipeline(LLMClient.from_settings(settings), cache, today=lambda: TODAY)
    response = pipeline.run(VisualizeRequest.model_validate(question.request))

    e = question.expected
    assert response.status == e.status, response.meta
    if isinstance(response, OkResponse):
        interpretation = response.meta.interpretation
        assert f"{interpretation.intent}.{interpretation.dimension}" == e.analysis
        assert response.visualization.type == e.viz_type
        if e.capped is not None:
            assert any(s.capped for s in response.meta.sample) == e.capped
    elif isinstance(response, NoResultsResponse):
        assert [n.casefold() for n in response.meta.not_found] == [
            n.casefold() for n in e.not_found
        ]
    elif isinstance(response, ClarificationResponse):
        assert response.meta.missing == e.missing
