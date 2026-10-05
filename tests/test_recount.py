"""The recount check (CLAUDE.md §14 Phase 7 step 2): every row, node, edge, point and bin, and
every exclusion, is rebuilt from the raw records with the same aggregator and must match.

Responses are assembled from the shared fixture; each failing case tampers with one datum the
categorizer-based membership check cannot see (networks, numeric charts, exclusions)."""

from typing import Any

import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.registry import REGISTRY, Dimension, Intent
from app.checks import CheckContext, run_checks
from app.schemas import OkResponse
from tests.factories import FIXTURE, cohort, raw_record
from tests.test_viz import _assemble

RECORDS = {t.nct_id: raw_record(t) for t in FIXTURE}
IDS = [frozenset(RECORDS)]
CASES = [
    (Intent.NETWORK, Dimension.DRUG_DRUG),
    (Intent.NUMERIC, Dimension.ENROLLMENT),
    (Intent.NUMERIC, Dimension.ENROLLMENT_BY_START_DATE),
    (Intent.DISTRIBUTION, Dimension.PHASE),
    (Intent.TIME_TREND, Dimension.START_YEAR),
]


def _failed(intent: Intent, dimension: Dimension, response: OkResponse) -> dict[str, list[str]]:
    aggregator = REGISTRY.get(intent, dimension)
    context = CheckContext(aggregator.shape, RECORDS, aggregator=aggregator, cohort_ids=IDS)
    failed: dict[str, list[str]] = {}
    for e in run_checks(response, context):
        failed.setdefault(e.check, []).append(e.message)
    return failed


def _tampered(response: OkResponse, change: Any) -> OkResponse:
    body = response.model_dump(mode="json")
    change(body)
    return OkResponse.model_validate(body)


@pytest.mark.parametrize(("intent", "dimension"), CASES)
def test_an_untouched_answer_recounts_exactly(intent: Intent, dimension: Dimension) -> None:
    assert _failed(intent, dimension, _assemble(intent, dimension, [cohort(FIXTURE)])) == {}


def test_a_node_given_a_trial_that_never_names_its_drug_fails_recount() -> None:
    response = _assemble(Intent.NETWORK, Dimension.DRUG_DRUG, [cohort(FIXTURE)])

    def add_t3(body: dict[str, Any]) -> None:
        node = body["visualization"]["data"]["nodes"][0]
        node["nct_ids"] = sorted([*node["nct_ids"], "NCT00000003"], reverse=True)
        node["trial_count"] += 1

    failed = _failed(Intent.NETWORK, Dimension.DRUG_DRUG, _tampered(response, add_t3))
    assert "recount" in failed


def test_a_trial_moved_between_histogram_bins_fails_recount() -> None:
    response = _assemble(Intent.NUMERIC, Dimension.ENROLLMENT, [cohort(FIXTURE)])

    def move(body: dict[str, Any]) -> None:
        rows = body["visualization"]["data"]
        src = next(r for r in rows if r["nct_ids"] == ["NCT00000001"])
        dst = next(r for r in rows if not r["nct_ids"] and r["enrollment_type"] == "Actual")
        dst["nct_ids"], dst["trial_count"], dst["citations"] = (src["nct_ids"], 1, src["citations"])
        src["nct_ids"], src["trial_count"], src["citations"] = [], 0, []

    failed = _failed(Intent.NUMERIC, Dimension.ENROLLMENT, _tampered(response, move))
    assert "recount" in failed


def test_an_exclusion_naming_the_wrong_trial_fails_recount() -> None:
    response = _assemble(Intent.TIME_TREND, Dimension.START_YEAR, [cohort(FIXTURE)])

    def swap(body: dict[str, Any]) -> None:
        body["meta"]["excluded"][0]["nct_ids"] = ["NCT00000005"]  # T3 lacks the date, not T5

    failed = _failed(Intent.TIME_TREND, Dimension.START_YEAR, _tampered(response, swap))
    assert "recount" in failed
