# Build history

The shipped log, newest phase first. Each shipped step gets a few 1-2 line bullets under its phase, moved here from CLAUDE.md §14 in the same commit. The Decisions section holds the reasoning behind CLAUDE.md §13.2.

## Shipped

### Phase 1: Foundation (in progress)

- **1.7 Cache** (2026-10-04): `TrialCache` in `app/cache.py` serves pages for a `params_key` written within `CACHE_TTL_HOURS`, otherwise fetches live. Pages and trial upserts are written in one transaction.
- The key doesn't include the cap, so a cache hit must cover the current cap (`covers_cap`, shared with the client), or a larger cap would get a short copy.
- A refetch upserts pages and drops any pages past the new last one; `records_by_id` matches NCT IDs exactly.
- Live test (`pytest -m live`, excluded by default): pembrolizumab is fetched from the real API, then served from the cache with zero HTTP requests.
- **1.6 API client** (2026-10-04): `app/ctgov.py` maps `RetrievalFilters` to verified params only. Phase and year range are AND-joined in `filter.advanced`; an open-ended range uses `MIN`/`MAX`.
- `params_key` is the params sorted and URL-encoded, without `pageToken`. `fields=` trims records to the §6 paths. Pages follow `nextPageToken` at `pageSize` min(1000, cap).
- Stops at `FETCH_CAP`; `FetchResult` keeps the verbatim pages for the cache and reports `fetched`, `total` (first page's `totalCount`) and `capped`.
- 30 s timeout; 5xx/429 retried twice (1 s, 2 s); 4xx, timeouts and malformed bodies raise `UpstreamError` immediately, keeping the API's reason text.
- Live smoke run: pembrolizumab returned 2,000 of 2,968 (capped); a nonexistent drug returned 0 of 0.
- **1.5 Retrieval filters** (2026-10-04): `RetrievalFilters` in `app/schemas.py` uses the SCHEMAS.md §1 request field names, so a stated filter appears in `meta.filters` under the same key.
- Fields: drug, condition, sponsor and country (stripped, blank rejected); `trial_phase` and `overall_status` from the vocab enums; start and end year. `overall_status` is planner-only.
- `start_year > end_year` is rejected (§7.6). Unknown fields are rejected, because a misspelled filter would otherwise be ignored and silently widen the search. The model is frozen.
- **1.4 Vocabulary** (2026-10-04): `app/vocab.py` holds Phase, Status, InterventionType, AgencyClass and StudyType as `StrEnum`s, re-verified against `GET /studies/enums`.
- Labels are the API's own `legacyValue` strings; AgencyClass has none, so its labels are ours. No other module defines labels.
- `label()` looks up labels per enum class, because members with equal values (`Status.UNKNOWN`, `AgencyClass.UNKNOWN`) collide in a flat dict.
- `phase_label()` makes one category per phase combination ("Phase 1/Phase 2") and "Not specified" for no phase, so phase sums reconcile.
- Tests take expected values from CLAUDE.md §8.4, not from the code.
- **1.3 Migrations** (2026-10-04): `migrations/001_cache.sql` creates `api_pages` (PK `params_key`, `page_index`) and `trials` (PK `nct_id`, CHECK `^NCT[0-9]{8}$`), both jsonb, both with `fetched_at`.
- `app/migrate.py` applies unapplied files in number order in one transaction, so a failing file changes nothing; misnamed or duplicate-numbered files are rejected.
- The `schema_migrations` ledger is created by the runner rather than by 001, because it must exist before the runner can tell which files are unapplied.
- `config.load_database_url()` reads only `DATABASE_URL`, so migrating doesn't need an LLM setting that hasn't been decided yet.
- Tests run in a throwaway schema per test (`tests/conftest.py`), so they never touch the dev cache. They cover order, idempotence, rollback and the table constraints.
- **1.2 Dependencies** (2026-10-04): added `httpx` (sync API client; `MockTransport` serves test fixtures without a mocking library).
- Added `psycopg[binary]` (psycopg3 driver for the Postgres cache and migrations; the binary wheel needs no local libpq).
- **1.1 Infra** (2026-10-04): `docker-compose.yml` runs pinned `postgres:18.6-alpine` on 127.0.0.1, with a healthcheck and a named volume.
- `config.py` + `.env.example` gained `CTGOV_BASE_URL`, `FETCH_CAP` (2000) and `CACHE_TTL_HOURS` (168); blank falls back to the default, invalid raises `ConfigError`.
- CI runs a Postgres service container on the same image, for the cache and migration tests to come.

### Phase 0: Skeleton

- 2026-10-04: repo skeleton per CLAUDE.md §4; uv + ruff + mypy (strict) + pytest on Python 3.12; GitHub Actions CI running the Definition of done; `app/config.py` with a two-way `.env.example` parity test.

## Decisions

- **LLM limited to planning, viz selection and prose.** In a visualization agent, the hallucination-prone step is the model emitting data. A schema-validated planning role makes numeric hallucination structurally impossible, and per-row citations then come for free from deterministic aggregation.
- **Structured API retrieval, not semantic search.** ClinicalTrials.gov exposes typed fields (phase, status, sponsor class, dates, country, intervention). Structured queries answer exactly; embeddings would blur NCT IDs and categorical labels and add latency.
- **Live API plus a Postgres response cache.** A local pre-cached corpus is faster and fully reproducible, but it goes stale. Caching responses by params keeps repeat runs reproducible without that staleness.
- **Hand-rolled orchestration, no agent framework.** The rubric grades design reasoning, and a framework hides exactly those decisions.
- **Aggregator registry keyed on (intent, dimension).** "Multiple question classes without one-off hacks" calls for dispatch through a registry, not branching in route handlers.
- **Networks as co-occurrence aggregations.** A network graph counts entities that co-occur across records, with citations on edges. It needs no knowledge graph or graph retrieval.
- **Explicit statuses (`ok`, `clarification_needed`, `no_results`, `degraded`).** A system that always answers fluently has no observable failure mode.
- **Repair once from the same rows, then `degraded`.** Re-querying the API to fix a spec would shift the data under a response.
- **Zero-fill gap years, disclose caps and pruning, reject contradictory inputs.** Each one prevents a chart that silently misleads the user.
- **Toolchain: uv, ruff, mypy (strict), pytest, Python >=3.12, GitHub Actions** (user choice, 2026-10-04). uv was already installed and gives reviewers a one-command `uv sync` from a lockfile. 3.12 is the floor for reviewer compatibility.
- **LLM provider: OpenAI** (user choice, 2026-10-04). The company supplied an OpenAI API key.
- **Private GitHub repo** (user choice, 2026-10-04). CLAUDE.md holds the interviewer's grading remarks and the CTO's comments on company plans.
- **Local Postgres via Docker Compose** (user choice, 2026-10-04). A reviewer unzipping the project gets the same pinned database with one command, with no local install.
- **psycopg3 + numbered SQL migrations, no ORM** (user choice, 2026-10-04). The cache is two tables; an ORM and Alembic add two dependencies and boilerplate without preventing a real failure.
- **Cache tables `api_pages` + `trials`** (user choice, 2026-10-04). Pages keyed by exact params make identical requests reuse identical records (examples and eval depend on it); the per-trial table gives exact `nct_id` lookup for citation and excerpt checks. TTL comes from `CACHE_TTL_HOURS`.
- **Full stack with a Vite + React + TS frontend** (user choice, 2026-10-04). Seeing the charts is the user's perspective the interviewer grades; rendering only from `SCHEMAS.md` also proves the contract needs no guessing. Vega-Lite covers the five chart types declaratively, and Cytoscape.js covers networks.
- **Contract in `SCHEMAS.md`** (user choice, 2026-10-04). It keeps CLAUDE.md small for every session; a contract test validates its examples against `schemas.py` so the doc cannot drift.
- **Phase 1 retrieval policy** (user approval, 2026-10-04). httpx sync, because requests are sequential and FastAPI threads sync routes. `FETCH_CAP` 2000. A 30 s timeout with 2 retries on 5xx/429, because a transient upstream error should not fail a request. Counting rules: a multi-phase record is its own category so phase sums reconcile; missing values get disclosed buckets or counted exclusions, never silent drops.
