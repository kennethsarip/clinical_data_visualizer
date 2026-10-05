"""The endpoint (CLAUDE.md §8.1): one route that calls the pipeline. 200 for every status, 422 for
request validation before the pipeline runs, 502 for a dependency failure."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.aggregators.registry import Dimension, Intent
from app.main import app, get_pipeline
from app.pipeline import DependencyError
from app.schemas import (
    RESPONSE_ADAPTER,
    AnyResponse,
    ClarificationMeta,
    ClarificationResponse,
    Filters,
    VisualizeRequest,
)
from tests.test_viz import _assemble

OK = _assemble(Intent.DISTRIBUTION, Dimension.PHASE)
CLARIFY = ClarificationResponse(
    status="clarification_needed",
    visualization=None,
    trials={},
    meta=ClarificationMeta(
        source="clinicaltrials.gov",
        filters=Filters(stated={}, inferred={}),
        assumptions=[],
        notes=["Name a drug, condition or sponsor to chart."],
        missing=["drug_name", "condition", "sponsor"],
    ),
)


class FakePipeline:
    def __init__(self, outcome: AnyResponse | Exception) -> None:
        self.outcome = outcome
        self.requests: list[VisualizeRequest] = []

    def run(self, request: VisualizeRequest) -> AnyResponse:
        self.requests.append(request)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def serve() -> Iterator[Any]:
    def install(outcome: AnyResponse | Exception) -> tuple[TestClient, FakePipeline]:
        fake = FakePipeline(outcome)
        app.dependency_overrides[get_pipeline] = lambda: fake
        return TestClient(app), fake

    yield install
    app.dependency_overrides.clear()


def test_ok_response_is_returned_whole(serve: Any) -> None:
    client, fake = serve(OK)
    reply = client.post("/api/visualize", json={"query": "phases", "condition": "melanoma"})
    assert reply.status_code == 200
    body = reply.json()
    assert RESPONSE_ADAPTER.validate_python(body) == OK
    assert "phase" in body["visualization"]["data"][0]  # row dimension fields survive serialization
    assert fake.requests == [VisualizeRequest(query="phases", condition="melanoma")]


def test_non_ok_status_is_still_200(serve: Any) -> None:
    client, _ = serve(CLARIFY)
    reply = client.post("/api/visualize", json={"query": "show me trials"})
    assert reply.status_code == 200
    assert reply.json()["status"] == "clarification_needed"


def test_dependency_failure_is_502_with_detail(serve: Any) -> None:
    client, _ = serve(DependencyError("ClinicalTrials.gov: HTTP 503"))
    reply = client.post("/api/visualize", json={"query": "phases of melanoma trials"})
    assert reply.status_code == 502
    assert reply.json() == {"detail": "ClinicalTrials.gov: HTTP 503"}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": ""},
        {"query": "q" * 1001},
        {"query": "melanoma per year", "start_year": 2022, "end_year": 2018},
        {"query": "melanoma", "drug": "aspirin"},
        {"query": "melanoma", "trial_phase": "PHASE9"},
    ],
    ids=["no-query", "blank", "too-long", "contradictory-years", "unknown-field", "bad-phase"],
)
def test_invalid_request_is_422_before_the_pipeline(serve: Any, body: dict[str, Any]) -> None:
    client, fake = serve(OK)
    reply = client.post("/api/visualize", json=body)
    assert reply.status_code == 422
    assert fake.requests == []


def test_the_only_api_route_is_visualize() -> None:
    paths = {route.path for route in app.routes if route.path.startswith("/api")}  # type: ignore[attr-defined]
    assert paths == {"/api/visualize"}
