"""The OpenAPI dump the frontend types are generated from (CLAUDE.md §14 Phase 4 step 3).

It must be deterministic (CI diffs the generated types) and document every HTTP code the routes
return (SCHEMAS.md §1, §6), so the frontend client has a type for each body it handles.
"""

import json
from pathlib import Path

from app.export_openapi import openapi_json

COMMITTED = Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"

ERROR_REF = {"$ref": "#/components/schemas/ErrorDetail"}


def _responses(path: str, method: str) -> dict[str, object]:
    spec = json.loads(openapi_json())
    responses: dict[str, object] = spec["paths"][path][method]["responses"]
    return responses


def test_dump_is_deterministic_and_ends_with_a_newline() -> None:
    first = openapi_json()
    assert first == openapi_json()
    assert first.endswith("}\n")


def test_visualize_documents_the_502_body() -> None:
    responses = _responses("/api/visualize", "post")
    assert set(responses) == {"200", "422", "502"}
    assert responses["502"]["content"]["application/json"]["schema"] == ERROR_REF  # type: ignore[index]


def test_trials_documents_the_404_body() -> None:
    responses = _responses("/api/trials/{nct_id}", "get")
    assert set(responses) == {"200", "404", "422"}
    assert responses["404"]["content"]["application/json"]["schema"] == ERROR_REF  # type: ignore[index]


def test_error_detail_is_a_single_message() -> None:
    schemas = json.loads(openapi_json())["components"]["schemas"]
    assert schemas["ErrorDetail"]["properties"] == {"detail": {"type": "string", "title": "Detail"}}
    assert schemas["ErrorDetail"]["required"] == ["detail"]


def test_committed_schema_matches_the_app() -> None:
    # Catches a model change without regenerated frontend types, even where Node is absent.
    # Fix: `cd frontend && npm run gen:types`.
    assert COMMITTED.read_text() == openapi_json()
