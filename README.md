# ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns a natural-language clinical-trials question into a structured,
frontend-renderable visualization spec built from ClinicalTrials.gov Data API records, with
citations from each data point back to the trials that produced it.

**Status:** early development. The query endpoint is not built yet.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs the pinned Python (3.12) if you don't have it.

## Setup

```bash
uv sync
cp .env.example .env   # then fill in every value
```

## Run

```bash
uv run --env-file .env uvicorn app.main:app --reload
```

Interactive API docs: http://127.0.0.1:8000/docs

## Quality checks

The same commands run in CI:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

## Still to write

- Request and response schema
- Key design decisions and tradeoffs
- Limitations and what more time would improve
- Example runs (3-5 queries with actual JSON outputs)
- AI tools used, how correctness was validated, and what was designed vs generated
