"""Live check of the Phase 2 core on real records (`uv run pytest -m live`).

Runs every registered aggregator and the citation step on live ClinicalTrials.gov data and checks
the invariants that must hold whatever the data: provenance is consistent, every cited trial was
retrieved, every excerpt occurs in its cited field of the raw record, single-valued dimensions
reconcile (§8.5) and network edges join kept nodes. The offline tests prove exact rows on
synthetic data; this proves the same code survives real, messy records.
"""

import os
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

import app.aggregators  # noqa: F401  (registers every aggregator)
from app.aggregators.registry import (
    REGISTRY,
    Aggregation,
    AggRow,
    CohortTrials,
    Dimension,
    GraphAggregation,
    Intent,
)
from app.checks import excerpt_matches
from app.citations import provenance, trial_summaries
from app.ctgov import TIMEOUT_SECONDS, CtgovClient, record_nct_id
from app.normalize import normalize_records
from app.schemas import RetrievalFilters

pytestmark = pytest.mark.live

SINGLE_VALUED = {Dimension.PHASE, Dimension.OVERALL_STATUS, Dimension.SPONSOR_CLASS}


class Live:
    def __init__(self, client: CtgovClient, filters: RetrievalFilters, label: str | None) -> None:
        result = client.fetch(filters)
        self.raw = {record_nct_id(r): r for r in result.records}
        self.cohort = CohortTrials(label, normalize_records(result.records), filters)


@pytest.fixture(scope="module")
def live() -> Iterator[dict[str, Live]]:
    base_url = os.environ.get("CTGOV_BASE_URL") or "https://clinicaltrials.gov/api/v2"
    with httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS) as http:
        client = CtgovClient(http, fetch_cap=1000)
        yield {
            "melanoma": Live(client, RetrievalFilters(condition="melanoma"), None),
            "pembrolizumab": Live(
                client, RetrievalFilters(drug_name="pembrolizumab"), "Pembrolizumab"
            ),
            "nivolumab": Live(client, RetrievalFilters(drug_name="nivolumab"), "Nivolumab"),
        }


def _check_rows(rows: tuple[AggRow, ...], sources: list[Live]) -> None:
    raw: dict[str, Any] = {k: v for s in sources for k, v in s.raw.items()}
    for row in rows:
        result = provenance(row)
        assert result.trial_count == len(result.nct_ids)
        assert set(result.nct_ids) <= raw.keys()
        for citation in result.citations:
            assert citation.nct_id in result.nct_ids
            # Field-level: the excerpt must be in the cited field, not just anywhere in the record.
            assert excerpt_matches(raw[citation.nct_id], citation), (citation, row.values)


@pytest.mark.parametrize(
    ("intent", "dimension"),
    [pytest.param(i, d, id=f"{i}-{d}") for i, d in REGISTRY.registered()],
)
def test_every_aggregator_on_live_data(
    live: dict[str, Live], intent: Intent, dimension: Dimension
) -> None:
    if intent is Intent.COMPARISON:
        sources = [live["pembrolizumab"], live["nivolumab"]]
    else:
        sources = [live["melanoma"]]
    result = REGISTRY.get(intent, dimension).aggregate([s.cohort for s in sources])

    if isinstance(result, GraphAggregation):
        assert result.nodes and result.edges, "melanoma should yield a non-empty network"
        node_ids = {n.values["id"] for n in result.nodes}
        assert all({e.values["source"], e.values["target"]} <= node_ids for e in result.edges)
        _check_rows(result.nodes + result.edges, sources)
        return

    assert isinstance(result, Aggregation)
    assert result.rows
    _check_rows(result.rows, sources)
    if intent is Intent.DISTRIBUTION and dimension in SINGLE_VALUED:
        # §8.5: a single-valued dimension's rows sum to the trials minus the exclusions.
        trials = len(sources[0].cohort.batch.trials)
        assert sum(len(r.nct_ids) for r in result.rows) == trials - sum(result.excluded.values())

    all_ids = {n for r in result.rows for n in r.nct_ids}
    trials_in_sources = [t for s in sources for t in s.cohort.batch.trials]
    assert set(trial_summaries(trials_in_sources, all_ids)) == all_ids


def test_condition_network_marks_its_anchor(live: dict[str, Live]) -> None:
    graph = REGISTRY.get(Intent.NETWORK, Dimension.CONDITION_DRUG).aggregate(
        [live["melanoma"].cohort]
    )
    assert isinstance(graph, GraphAggregation)
    assert [n.values["id"] for n in graph.nodes if n.values["is_anchor"]] == ["condition:melanoma"]
