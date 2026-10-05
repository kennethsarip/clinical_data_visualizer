# ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns a natural-language clinical-trials question into a structured,
frontend-renderable visualization spec built from ClinicalTrials.gov Data API records, with
citations from each data point back to the trials that produced it.

**Status:** early development. The query endpoint is not built yet.

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs the pinned Python (3.12) if you don't have it.
- [Docker](https://docs.docker.com/get-docker/) with Compose, for the local Postgres cache.

## Setup

```bash
uv sync
cp .env.example .env   # fill in the Required values; Optional ones may stay blank
docker compose up -d   # local Postgres 18 on 127.0.0.1:5432
uv run --env-file .env python -m app.migrate   # create the cache tables; safe to rerun
```

`DATABASE_URL` for the Compose database is `postgresql://cheiron:cheiron@127.0.0.1:5432/cheiron`.

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

Live tests against the real API are excluded by default; run them with `uv run pytest -m live`.
The database tests need the Compose Postgres running. Each test uses a throwaway schema, so
your cached data is never touched.

## Still to write

- Request and response schema (locked in [SCHEMAS.md](SCHEMAS.md))
- Bonuses: deep citations, condition-anchored networks, the model comparison and the demo video
- Key design decisions and tradeoffs
- Limitations and what more time would improve
- Example runs (3-5 queries with actual JSON outputs)
- AI tools used, how correctness was validated, and what was designed vs generated
