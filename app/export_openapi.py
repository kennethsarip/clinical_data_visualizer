"""Prints the app's OpenAPI schema, the input the frontend's TypeScript types are generated from
(CLAUDE.md §14 Phase 4). It reads the app object, so no server, database or API key is needed.

Usage: `uv run python -m app.export_openapi > frontend/openapi.json`
"""

import json

from app.main import app


def openapi_json() -> str:
    """Sorted keys and a trailing newline, so regenerating unchanged models gives identical bytes
    and CI can fail on any diff."""
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    print(openapi_json(), end="")
