"""SCHEMAS.md <-> schemas.py contract (CLAUDE.md §8.3, §9).

Every JSON example in SCHEMAS.md must validate against the models, so the documented contract and
the code cannot drift. Expected values come from SCHEMAS.md, never from model output.
"""

import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from app.schemas import (
    RESPONSE_ADAPTER,
    VISUALIZATION_ADAPTER,
    FilterKey,
    RetrievalFilters,
    VisualizeRequest,
)

SCHEMAS_MD = Path(__file__).resolve().parents[1] / "SCHEMAS.md"
_JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.DOTALL)

# CLAUDE.md §8.3: the three assignment types plus the three decided on 2026-10-04.
VIZ_TYPES = {
    "bar_chart",
    "grouped_bar_chart",
    "time_series",
    "scatter_plot",
    "histogram",
    "network_graph",
}
STATUSES = {"ok", "clarification_needed", "no_results", "degraded"}


def _examples() -> list[dict[str, Any]]:
    return [json.loads(block) for block in _JSON_BLOCK.findall(SCHEMAS_MD.read_text())]


def _kind(example: dict[str, Any]) -> str:
    if "status" in example:
        return "response"
    if "query" in example:
        return "request"
    if "encoding" in example:
        return "visualization"
    raise AssertionError(f"SCHEMAS.md example of unknown kind: {sorted(example)}")


EXAMPLES = _examples()


def test_schemas_md_has_examples() -> None:
    # Guards the parser: a broken regex would otherwise make every test below vacuous.
    assert len(EXAMPLES) >= 10


@pytest.mark.parametrize(
    "example", EXAMPLES, ids=lambda e: f"{_kind(e)}:{e.get('type') or e.get('status', '')}"
)
def test_every_example_validates(example: dict[str, Any]) -> None:
    kind = _kind(example)
    if kind == "request":
        VisualizeRequest.model_validate(example)
    elif kind == "response":
        RESPONSE_ADAPTER.validate_python(example)
    else:
        VISUALIZATION_ADAPTER.validate_python(example)


def test_every_viz_type_has_an_example() -> None:
    shown = {e.get("type") or (e.get("visualization") or {}).get("type") for e in EXAMPLES}
    assert shown >= VIZ_TYPES


def test_every_status_has_an_example() -> None:
    assert {e["status"] for e in EXAMPLES if "status" in e} == STATUSES


def _ok_example() -> dict[str, Any]:
    """A fresh copy each call: tests edit it, and EXAMPLES is shared across tests."""
    return _copy(next(e for e in EXAMPLES if e.get("status") == "ok"))


def _network_example() -> dict[str, Any]:
    return _copy(next(e for e in EXAMPLES if e.get("type") == "network_graph"))


def _copy(example: dict[str, Any]) -> dict[str, Any]:
    copied: dict[str, Any] = json.loads(json.dumps(example))
    return copied


def test_examples_round_trip_unchanged() -> None:
    # The `schema` check (CLAUDE.md §7.6) relies on a response surviving the model unchanged.
    # The only default is Channel.scale ("linear"), which the API emits explicitly.
    ok = _ok_example()
    parsed = RESPONSE_ADAPTER.validate_python(ok)
    dumped = RESPONSE_ADAPTER.dump_python(parsed, mode="json", exclude_defaults=True)
    assert dumped == ok


# --- what the contract rejects ---


def _broken(base: dict[str, Any], path: list[str | int], value: Any) -> dict[str, Any]:
    copy: dict[str, Any] = json.loads(json.dumps(base))
    target: Any = copy
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return copy


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (["visualization"], None),  # ok must carry a spec
        (["visualization", "type"], "pie_chart"),  # not one of the six types
        (["visualization", "encoding", "x", "type"], "categorical"),  # not a channel type
        (["visualization", "encoding", "y", "scale"], "sqrt"),
        (["visualization", "data", 0, "citations", 0, "nct_id"], "NCT123"),  # bad NCT ID
        (["visualization", "data", 0, "nct_ids"], ["nct00000003"]),
        (["meta", "source"], "pubmed"),
        (["meta", "sort", "order"], "random"),
        (["meta", "filters", "stated", "drug"], "Pembrolizumab"),  # not a request field name
        (["status"], "error"),
    ],
)
def test_malformed_ok_response_is_rejected(path: list[str | int], value: Any) -> None:
    with pytest.raises(ValidationError):
        RESPONSE_ADAPTER.validate_python(_broken(_ok_example(), path, value))


@pytest.mark.parametrize("key", ["interpretation", "sample", "citation_cap", "pruning"])
def test_ok_meta_requires_its_keys(key: str) -> None:
    ok = _ok_example()
    del ok["meta"][key]
    with pytest.raises(ValidationError):
        RESPONSE_ADAPTER.validate_python(ok)


@pytest.mark.parametrize("status", ["clarification_needed", "no_results", "degraded"])
def test_non_ok_carries_no_spec_and_no_trials(status: str) -> None:
    example = next(e for e in EXAMPLES if e.get("status") == status)
    spec = _ok_example()["visualization"]
    with pytest.raises(ValidationError):
        RESPONSE_ADAPTER.validate_python(_broken(example, ["visualization"], spec))
    with pytest.raises(ValidationError):
        RESPONSE_ADAPTER.validate_python(_broken(example, ["trials"], _ok_example()["trials"]))


def test_network_node_entity_type_is_restricted() -> None:
    bad = _broken(_network_example(), ["data", "nodes", 0, "entity_type"], "gene")
    with pytest.raises(ValidationError):
        VISUALIZATION_ADAPTER.validate_python(bad)


def test_network_needs_nodes_and_edges() -> None:
    bad = _broken(_network_example(), ["data"], {"nodes": []})
    with pytest.raises(ValidationError):
        VISUALIZATION_ADAPTER.validate_python(bad)


# --- request ---


def test_request_needs_a_query() -> None:
    with pytest.raises(ValidationError):
        VisualizeRequest.model_validate({"drug_name": "Pembrolizumab"})


@pytest.mark.parametrize("query", ["", "   "])
def test_blank_query_is_rejected(query: str) -> None:
    with pytest.raises(ValidationError):
        VisualizeRequest.model_validate({"query": query})


def test_query_is_capped_at_1000_characters() -> None:
    VisualizeRequest.model_validate({"query": "q" * 1000})
    with pytest.raises(ValidationError, match="1000"):
        VisualizeRequest.model_validate({"query": "q" * 1001})


def test_request_rejects_contradictory_years() -> None:
    with pytest.raises(ValidationError, match="start_year"):
        VisualizeRequest.model_validate({"query": "q", "start_year": 2020, "end_year": 2015})


@pytest.mark.parametrize("field", ["overall_status", "drug"])
def test_request_rejects_fields_outside_schemas_md(field: str) -> None:
    # overall_status exists only in the plan (SCHEMAS.md §1 has no such request field).
    with pytest.raises(ValidationError):
        VisualizeRequest.model_validate({"query": "q", field: "RECRUITING"})


def test_filter_keys_match_the_plan_filters() -> None:
    # meta.filters keys must be exactly the fields a filter can come from (SCHEMAS.md §4).
    assert set(get_args(FilterKey)) == set(RetrievalFilters.model_fields)
