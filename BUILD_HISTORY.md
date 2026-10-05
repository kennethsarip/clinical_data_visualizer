# Build history

The shipped log, newest phase first. Each shipped step gets a few 1-2 line bullets under its phase, moved here from CLAUDE.md §14 in the same commit. The Decisions section holds the reasoning behind CLAUDE.md §13.2.

## Shipped

### Phase 4: Frontend (in progress)

- **4.2 Scaffold** (2026-10-04): `frontend/` from `create-vite` 9.2.1 (`react-ts`): React 19, Vite 8, TypeScript 6 (`strict`), oxlint (the template's linter, replacing the planned ESLint: one fast dev dependency, no config to maintain), Vitest 4 + Testing Library on jsdom. Demo assets removed; a red-first smoke test covers the shell.
  - Design tokens from the reference screenshots are CSS variables in `src/index.css`; Pretendard is self-hosted from npm (dynamic subset), so no third-party font request.
  - The Vite proxy sends `/api` to `127.0.0.1:8000`, checked against a running backend (a cached record came back through the proxy). CI gains a `frontend` job (Node 24 from `.nvmrc`), and the Definition of done gains the npm checks.
- **4.1 Contract additions** (2026-10-04): the trial summary gains `sponsor_name` and `conditions`, as registered, for source-card chips. New `GET /api/trials/{nct_id}` (`StoredTrial`) serves the verbatim cached record and its `fetched_at`; 404 if not cached, 422 on a malformed ID. SCHEMAS.md §2 and the new §6 updated in the same commit.
  - It reads the cache regardless of TTL and never calls the API, so the Viewer shows the record the excerpt check ran against. `TrialCache.stored_trial` does the lookup; `get_cache` is now the per-request connection dependency, and `get_pipeline` builds on it.
  - Smoke-tested on the dev cache with a running server: 200 with the verbatim record, 404 for an uncached ID, 422 for a lowercase ID.
- **4.0 Reference pass** (2026-10-04): read the two product screenshots in `docs/product_frontend/` and settled the interaction patterns taken from them and the visual elements left out (Decisions below), plus two contract additions (Phase 4 step 1).

### Phase 3: LLM planning and the endpoint (done 2026-10-04; tagged `phase-3`)

- **Done when, met:** one query per §1 class returns `ok` with every check passing and each §7.8 case returns its behavior (live end to end, 29/29 eval questions); planner tests pass against a stubbed LLM, including malformed output.
- **3.5 Endpoint** (2026-10-04): `app/main.py` has one route, `POST /api/visualize`, which calls `Pipeline.run`. Every status is 200, `VisualizeRequest` failures are 422 before the pipeline runs, and `DependencyError` is 502 with `{"detail": ...}`.
  - One DB connection per request (psycopg connections are not thread-safe; sync routes run in a threadpool); settings and the HTTP and LLM clients are built once and shared.
  - `logging.basicConfig` in `main.py`, because uvicorn configures only its own loggers and the app's INFO logs (cache hits, retries, repairs) were dropped.
  - 10 offline tests via a dependency override, seen red (10 failures). Live over HTTP: an `ok` pembrolizumab time series (2,000 of 2,968, capped and disclosed) in 7.9 s cold and 4.7 s from the cache; clarification for "Show me trials"; 422 for reversed years.

- **3.4 Pipeline** (2026-10-04): `app/pipeline.py` `Pipeline(llm, fetcher).run(request)` runs the §1 steps and is the one place errors become outcomes.
  - Plan -> clarification before any fetch; one fetch per cohort through the cache; zero records -> the not-found probe; aggregate; nothing chartable -> `no_results` naming the exclusion rule; prose; assemble; checks; one repair without the LLM prose; else `degraded`.
  - `DependencyError` (-> 502) wraps ClinicalTrials.gov `UpstreamError`, a batch over 5% unreadable, and `LLMUpstreamError` while planning. `PlanError` -> `degraded` with check "plan" and the request fields as stated filters. The checker is injected so the repair path is tested.
  - `CtgovClient.count` / `TrialCache.count`: one single-ID page (`fields=NCTId`), uncached, for the probe; skipped when the entity was the only filter, since that search already ran.
  - Bug found by the tests: building the record lookup before normalizing made one ID-less record abort the request; normalize now runs first. The cache still raises on such a record (Phase 1 decision, pinned by a test), logged in §13.4 rather than changed.
  - 17 offline tests, seen red (16 failures) against a stub, plus 3 ctgov and 1 cache test for `count`.
  - **Live end to end** (`tests/test_live_pipeline.py`): 29/29 plannable eval questions return their expected status, analysis, viz type, not-found names and cap on the first run (172 s; comparisons ~8 s each, single-cohort ~4-6 s).

- **3.3 Title and notes** (2026-10-04): `viz.write_prose(llm, query, aggregator, cohorts, filters)` makes the second LLM call (`LLMProse`: a title of up to 120 characters, up to 3 notes) from the question, analysis key, chart type, columns, filters and cohort labels; rows never reach the prompt (a test asserts no trial ID or title is sent).
  - The §7.6 number rule moved to `viz.stray_numbers`, shared with `checks._title`, so the prose step and the check cannot disagree. A title with a stray number falls back; a note with one is dropped on its own.
  - Any failure (malformed answer, refusal, upstream error, stray number) returns `default_title` plus a note saying so, with no retry, keeping the response `ok`.
  - 9 offline tests, seen red (8 failures) against a stub.
- **Live runs, steps 3.1-3.3** (2026-10-04, after a working key): `test_live_llm` passes, so OpenAI accepts the generated strict schema. Planner on the 29 plannable eval questions, `gpt-5.4-mini` at `low`:
  - Baseline 27/29. Misses: "last five years" also set `end_year` 2026, which would drop future-dated trials; "distribution of enrollment sizes" went to `distribution.drug` (intermittent).
  - Prompt fix 1: `end_year` only for an explicit upper bound; any enrollment question is `numeric.*`. 3 runs: 28, 26, 29. New intermittent miss: with a conflicting `drug_name` field, the model sometimes omitted the query's drug, so the override note was lost.
  - Prompt fix 2: always copy values written in the question; sponsor name vs category made explicit. 3 runs: 29, 28, 28. The remaining miss is only the enrollment histogram.
  - That question alone, 15 samples each: `low` 12/15 correct (1.5 s mean), `medium` 15/15 (1.7 s). Full set at `medium`, 3 runs: 87/87, ~55-66 s per run vs ~45 s at `low`. The default is now `medium` (user decision); at the new default, `test_live_planner` + `test_live_prose` passed 52/52.
  - Prose (`tests/test_live_prose.py`): all 23 `ok` questions get an LLM title with no fallback. One note used the field name "drug_name"; the prose prompt now forbids internal field names (rerun 23/23).
- **Earlier key problems** (same day): the first key returned 401 `invalid_api_key`; the second authenticated but had no credits (429 `insufficient_quota`, which the SDK retries uselessly, ~6 s); the third works.

- **3.2 Planner** (2026-10-04): `app/planner.py` `plan_request(request, llm)` returns a `QueryPlan` or a `Clarification`; `build_plan` holds every rule and needs no LLM.
  - `plan_schema()` is the strict `LLMPlan` schema with `analysis` narrowed to the 22 registered keys. The prompt lists each key from per-intent and per-dimension guides, so a new aggregator fails a test until it is described. Today's date is in the prompt for relative years.
  - Rules: fields override the query with a note; stated iff from a field or verbatim in the query (or an enum's display label, "recruiting" -> `RECRUITING`), else inferred with a Python-written assumption; 2-4 cohorts of one kind, overriding the shared filters; the anchor rule; `unsupported_reason` -> clarification. A rule only the LLM can fix (unknown key, cohorts outside a comparison, reversed merged years) raises `LLMOutputError`, retried once with the error, then `PlanError`. `LLMUpstreamError` is never retried by the planner.
  - Plan shape change: `missing_anchor` became `unsupported_reason`, since Python owns the anchor rule. Named cohorts count as anchors, which the first implementation missed (5 drugs gave `missing` anchors; the eval expectation caught it).
  - `llm.complete` gained an optional `schema` override for the runtime enum. `is_stated` is now the one copy of the §7.3 test; `test_eval_questions.py` uses it.
  - 61 offline tests, seen red (61 failures) against a stub: rules, retry loop, and 26 eval questions with the LLM's part stubbed. `tests/test_live_planner.py` runs all 29 planned questions on the real LLM; blocked by the rejected key.

- **3.1 LLM client** (2026-10-04): `app/llm.py` `LLMClient.complete(instructions, user_input, name, output_type)` makes one Responses API call in strict structured-output mode and returns a validated Pydantic model.
  - `gpt-5.4-mini` checked against OpenAI's model page: Responses API, structured outputs, reasoning effort `none` (the default), `low`, `medium`, `high` or `xhigh`. `OPENAI_REASONING_EFFORT` defaults to `low`. Timeout 30 s, 2 SDK retries, 4,000 output tokens.
  - `strict_json_schema` turns a model's schema into strict form (every property required, no extras, null unions kept) and drops keywords strict mode may reject (lengths, defaults, titles), which Pydantic re-checks after the call.
  - Typed errors for the §7.7 mapping: `LLMUpstreamError` (HTTP error or unreachable -> 502) and `LLMOutputError` (refusal, incomplete reply, non-JSON or invalid output; keeps the raw text and a compact `field: message` summary for the retry prompt).
  - 17 offline tests on an `httpx2.MockTransport` fake, seen red (16 failures) against a stub. The OpenAI SDK 3.x uses its own `httpx2`, not `httpx`, so passing an `httpx` client only worked by duck typing; the fakes now use `httpx2`.
  - The live smoke test `tests/test_live_llm.py` is blocked: OpenAI rejects the key in `.env` with 401 `invalid_api_key`. `OPENAI_MODEL` was blank in `.env` and is now `gpt-5.4-mini`.

- **3.0 Eval questions first** (2026-10-04): `eval/questions.json` holds 30 questions with the expected status, `analysis` key, viz type, stated and inferred filters, cohorts, missing anchors and not-found entities, each with a written `why`. All 9 appendix examples are included (the unanchored drug-drug one expects `clarification_needed`), plus every question class, every viz type and each §7.8 edge case.
  - `tests/test_eval_questions.py` checks every expectation against the registry, the request model and the §7.2/§7.3/§7.8 rules, so a wrong expectation cannot certify a wrong planner. Breaking four expectations (viz type, stated vs inferred, cohort count, anchor) failed 6 tests for those reasons.
  - Inferred filters list every acceptable value ("last five years" -> 2021 or 2022), since inference is ambiguous by definition. An enum filter counts as stated when its display label appears ("recruiting" -> `RECRUITING`), which the planner's stated test must match.

### Phase 2: Aggregation, citations, checks (done 2026-10-04; merged and tagged `phase-2`)

- **Done when, met:** every §1 row has a registered aggregator (22); all six viz types assemble specs that pass every check, offline on the fixture and live on real records; each aggregator test matches hand-computed rows; each check has a passing and a failing fixture.
- **2.7 Spec assembly** (2026-10-04): `viz.assemble` builds the full `ok` response from an aggregator's result.
  - Python picks the type (`VIZ_TYPE`) and the encoding per shape: channel types, plus a log scale for scatter enrollment.
  - Rows carry their citations; the `trials` lookup is built from the cohorts.
  - `meta` is filled in full: interpretation (cohorts and their filters for comparisons), units, sort (canonical phase, count desc, asc time and bins), time granularity, grouping and series, one sample entry per cohort, citation cap, exclusions (unreadable records added, named per cohort in comparisons), top-N and pruning.
  - Counting-rule assumptions are written by Python per dimension (multi-phase, "Not specified", drug rule, start-date basis, enrollment split, log-axis zero, edge weight, anchor hub, comparison overlap). Caller assumptions and LLM notes are appended.
  - `default_title` is a number-free title from the plan, used until Phase 3. `CohortTrials` gained `total` (the API totalCount) for the sample disclosure.
- **Bug review** (2026-10-04). Six defects found, each fixed red-first with a regression test:
  1. A stated year range could drop trials outside it; the time trend now spans stated and data years.
  2. A totalCount read from page 1 could fall below `fetched` if trials were added mid-fetch; it is now raised to `fetched`.
  3. An empty chart passed every check vacuously; `shape` now blocks a chart with no trials (§7.6).
  4. Code, number and date excerpts matched as substrings (`PHASE1` inside `EARLY_PHASE1`); they must now equal the value.
  5. `assemble` accepted `meta.filters` that differed from the filters actually applied. It now raises `AssemblyError`; found by the live sweep, where "COVID-19" in a title failed the title check against undisclosed filters.
  6. The default time-trend title read "Trials Started per Start Year"; it now reads "per Year".
- **Robustness:** every aggregator handles an empty cohort and trials with no optional fields. Real charts pass every check, and empty ones are blocked.
- **Live sweep** (2026-10-04, not committed): all 22 aggregators over 11 live queries were assembled and checked, 128/128 passing.
  - Queries: broad cancer (2,000 of 123,756), pembrolizumab, Pfizer, diabetes in Germany, melanoma 2015-2020, melanoma Phase 3, recruiting COVID-19, Erdheim-Chester (26), and the comparisons pembrolizumab vs nivolumab and diabetes vs obesity.
  - Two HTTP 429s were absorbed by the retries (logged in §13.4).
- **Committed live test** `tests/test_live_core.py`: 45 passed. It assembles every aggregator's response from live records and runs all nine checks.

- **2.6 Checks** (2026-10-04): `app/checks.py` `run_checks(response, CheckContext(shape, records))` returns `CheckError`s from nine checks: schema, encoding, shape, citation ids, excerpts, reconciliation, assumptions, title and disclosures. They read only the response, the declared shape and the raw cached records.
- Excerpts are matched at their `field` path, descending through lists such as `locations[].country`; a null excerpt must mean the field is absent. Reconciliation enforces `trial_count == len(nct_ids)`, no duplicate IDs, and, for phase, status, sponsor class and start year, rows summing to fetched minus excluded per cohort. The title check allows only numbers that occur in filter values or cohort labels.
- `disclosures` is new: §7.6's WARN items keep a response `ok` only if `meta` discloses them consistently (capped vs fetched/total, pruning for networks only, top-N bounding the categories), so it is added to the §7.6 table.
- Messages are capped at 5 per check plus a "... and N more", so a broken aggregator yields a readable `meta.errors`.
- The passing fixtures are the SCHEMAS.md bar and network examples with matching raw records, so the documented contract passes the checks. Every check has a failing fixture. Seen red (22 failures) against a placeholder.
- `viz.VIZ_TYPE` (the shape -> type table) shipped early, because the shape check needs it.
- The live core test now uses the same field-level `excerpt_matches`: 23 passed, so every live excerpt sits in the field it cites.
- **2.5 Citations** (2026-10-04): `app/citations.py` turns each row's evidence into `trial_count`, `nct_ids` (sorted descending) and `citations` for the first 25 of those trials. The cap counts trials, so a multi-phase trial keeps both of its phase citations. Null excerpts pass through.
- `trial_summaries` builds the `trials` lookup (title, status label, phase label, start date). A row trial with no evidence, or a lookup ID outside the retrieved records, raises `CitationError`, since either is a bug, never a user error.
- Seen red against placeholders (7 failures).
- **Live core test** `tests/test_live_core.py` (`-m live`) runs all 22 aggregators plus citations on live melanoma, pembrolizumab and nivolumab records (1,000 each; the comparisons use pembrolizumab vs nivolumab). It checks provenance, retrieved IDs, excerpts in raw records, §8.5 reconciliation for phase, status and sponsor class, edges joining kept nodes, and the condition anchor.
- 23 passed in 3.7 s. Corrupting the country excerpts made it fail on both country aggregators, so it can catch real bugs. Until step 6 the excerpt match is against the whole record.
- **2.4 Aggregators** (2026-10-04): 22 registered, covering every §1 class (first logged as 28, a miscount).
  - Distribution: phase, status, intervention type, sponsor class, top-20 drug, sponsor and condition. Geographic: top-20 country. Time trend: start year. Comparison: all eight categorical dimensions. Numeric: enrollment scatter and histogram. Networks: sponsor-drug, drug-drug and condition-drug.
  - `common.py` holds one categorizer per dimension (the categories a trial goes in, the evidence, the counting-rule exclusions) and the single `count_by`. Each family module (`categorical`, `comparison`, `time_trend`, `numeric`, `network`) is a thin layer that registers itself on import.
  - Ordering: phase is canonical; everything else is count desc, ties alphabetical. Top-N discloses `categories_total`.
  - Time trend zero-fills from the stated start year (or the first trial) to the stated end year (or the last). The aggregator reads only the bounds from `CohortTrials.filters`.
  - Comparison zero-fills every category for every cohort, orders by the cohorts combined, and names each exclusion with its cohort ("placebo (Pembrolizumab)").
  - Histogram: fixed half-open bins, every bin for every enrollment type present. The scatter has one row per trial.
  - Networks: one `CooccurrenceAggregator` configured with two `Side`s; drug-drug pairs are ordered by id. Pruning: weight >= 2, top 50 by weighted degree with an id tie-break, orphans dropped, a weight-1 fallback. Nodes for the request's named entities get `is_anchor`.
  - Intervention-type charts leave out unnamed interventions but keep the trial through its named ones; the "unnamed intervention" count discloses it.
  - Tests were written first from a hand-computed five-trial fixture (`tests/factories.py`). They passed on the first run, so red was shown by mutation instead: eight injected bugs (canonical order, zero-fill, bin edges, fallback, top-N, gap exclusions, comparison zero-fill, anchors) were each caught.
  - Live check (melanoma, 2,000 of 3,769 trials): the drug-drug network keeps 50 nodes and 174 edges in 50 ms. Its top edges are real regimens: ipilimumab + nivolumab (67), cyclophosphamide + fludarabine (48), dabrafenib + trametinib (28), encorafenib + binimetinib (16). Exclusions: 14 missing start dates, 119 without locations, 57 missing enrollment; 67 countries cut to 20.
  - `Registry.keys()` was renamed to `registered()` (ruff took it for a dict).
- **2.3 Entities** (2026-10-04): `app/entities.py` applies the §6 drug rule. DRUG, BIOLOGICAL and COMBINATION_PRODUCT count as drugs; a whole-word placebo/sham/vehicle/saline name does not. `select_drugs` returns one mention per drug key per trial and per-trial counts for `placebo`, `non-drug intervention` and `no drug intervention`.
- A drug key is the name with case and whitespace folded and trailing brackets, doses and salt words stripped, repeatedly, never down to nothing. Sponsors and conditions only fold case and whitespace. The node label is the most common *cleaned* spelling with case kept (so "Pembrolizumab", not "Pembrolizumab (MK-3475)"), with ties broken alphabetically. A mention keeps the raw name as the excerpt.
- Live check (1,000 trials each, 2026-10-04): pembrolizumab's 14 registered spellings merge into one node (689 trials), and the top 12 drugs for pembrolizumab and for melanoma are clean names. Unmerged long tail: leading doses ("200 mg pembrolizumab"), combination names ("X + pembrolizumab") and form words ("pembrolizumab injection"). These are mostly single-trial nodes that weight >= 2 pruning removes; a further rule waits for an eval failure.
- Melanoma: 202 of 1,000 trials have no drug intervention (non-drug only), which is why that count is disclosed.
- Tests were seen red (38 assertion failures) against placeholders.
- **2.2 Registry** (2026-10-04): `app/aggregators/registry.py` defines `Intent`, `Dimension` and `RowShape`, the `Aggregator` protocol (intent, dimension, shape, columns, excerpt fields, `aggregate`) and the output types (`AggRow` with per-trial `Evidence`; `Aggregation`; `GraphAggregation` with pruning).
- `Registry` dispatches on (intent, dimension). An unknown pair raises `UnknownAggregatorError`, and a duplicate pair raises `DuplicateAggregatorError`. `keys()` is sorted, because the Phase 3 planner schema is generated from it.
- Registration rejects declaration bugs: a shape outside the §1 matrix for its intent, no columns or excerpt fields, or a column that would shadow `trial_count`, `nct_ids` or `citations`.
- Aggregators carry per-trial evidence because only they know which value placed a trial in a row (e.g. which intervention name normalized to a node). `citations.py` orders and caps that evidence, and the excerpt check verifies it against the raw record.
- Tests were seen red against a no-op registry.
- **2.1 Response models** (2026-10-04): `app/schemas.py` implements the locked SCHEMAS.md. Responses form a union keyed on `status`, so an `ok` response must carry a spec and a non-`ok` one must carry `visualization: null` and empty `trials`. Each status has its own `meta` model, and nullable `ok` keys are still required.
- Models check structure only. Rules that compare values (encoding fields exist, `trial_count == len(nct_ids)`, excerpts) stay in `checks.py`, so each rule has one home.
- The request and the plan filters share one base model, so the year-order rule and the field names cannot drift apart. `meta.filters` keys are a `Literal` that a test keeps equal to the plan's filter fields.
- `tests/test_contract.py` validates every SCHEMAS.md JSON example, requires an example for each of the six types and four statuses, and rejects malformed variants. It was seen red against placeholder models; two of its rejection tests were mutation-checked.

### Phase 1: Foundation (done locally 2026-10-04; CI pending on push)

- **1.8 Normalize** (2026-10-04): `app/normalize.py` maps a record to a frozen `NormalizedTrial` (§6 fields); multi-phase records get one category via `vocab.phase_label`; countries are deduped and sorted.
- It never drops a record: `normalize_records` returns every trial plus a count per `Gap` (missing start date or enrollment, no locations, no interventions, unnamed intervention). Phase 2 aggregators choose which gaps exclude a record from a chart.
- Enrollment 0 is data, not missing. A missing always-present field, an unknown enum value or an unexpected date format raises `RecordShapeError`, naming the NCT ID.
- Unreadable records (user decision): set aside, logged and counted as `unreadable record` in `meta.excluded`; if more than 5% of a batch is unreadable, the batch raises `RecordShapeError`, because the API format has probably changed.
- Live check: 6,000 records (pembrolizumab, diabetes, COVID-19) normalize with no shape errors, and the gap counts match an independent probe. The live test now normalizes its sample too.
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
- **Frontend layout, styling and loading (2026-10-04).** A two-column answer view keeps the sources visible next to the chart, so clicking a datum shows its citations without scrolling; deep citations are the bonus being shown off. Plain CSS with tokens, because styling polish is out of scope and a component library would add weight and a borrowed look. Spinner plus elapsed time rather than server-sent progress stages, which would change the backend contract for cosmetic gain.
- **Frontend type-drift check, raw JSON tab, HTTP error views (2026-10-04).** The drift check keeps `schemas.py` the single source for the TypeScript types. The JSON tab lets a reviewer verify the contract directly. The 422 and 502 views mean a backend failure never shows a blank page.
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
- **Phase 1 review fixes** (user approval, 2026-10-04). Unreadable records are set aside up to 5% of a batch, because one odd record shouldn't cost the user 1,999 good ones, while more than 5% signals an API format change. Rules for no locations and no or unnamed interventions, because live data shows 1-15% of trials have these gaps and silent drops would undercount bars. `enrollment_type` is fetched, because estimated and actual counts must not be mixed unseen. Text filters are capped at 200 characters. `Retry-After`, timeout retries and multi-value filters are deferred with triggers (§13.4), since no failure has been observed.
- **Phase 1 retrieval policy** (user approval, 2026-10-04). httpx sync, because requests are sequential and FastAPI threads sync routes. `FETCH_CAP` 2000. A 30 s timeout with 2 retries on 5xx/429, because a transient upstream error should not fail a request. Counting rules: a multi-phase record is its own category so phase sums reconcile; missing values get disclosed buckets or counted exclusions, never silent drops.
- **Phase 2-6 decisions** (user approval, 2026-10-04):
  - Viz type is Python, a fixed shape -> type table. Each shape maps to one type, so an LLM pick adds a failure mode and no choice; the LLM keeps only the plan and the title and notes.
  - Drug = DRUG, BIOLOGICAL or COMBINATION_PRODUCT, minus placebo, sham, vehicle and saline; type alone splits pembrolizumab (617 DRUG, 243 BIOLOGICAL). Fixed name rules (case, dose, bracketed alias, salt) keep variants of one drug on one node; brand <-> generic merging is deferred until an eval failure.
  - Pruning: weight >= 2 and the top 50 nodes, falling back to weight 1 if that empties the graph, because an empty graph is useless to the user. The queried entity is flagged `is_anchor`, since it sits in every trial.
  - Every row carries all its `nct_ids`, so `trial_count == len(nct_ids)` is checkable; 25 cited trials per row keeps responses small. Absent values are cited as `excerpt: null` and verified absent, rather than with an invented excerpt. Excerpts are checked against the value at their `field`, so short values like `120` cannot match by accident.
  - Enrollment: fixed log-like bins and a log-scale scatter, split by Actual / Estimated, because enrollment is heavily skewed and the two kinds must not mix unseen.
  - SCHEMAS.md locked with `meta.interpretation` (the assignment requires the query interpretation in `meta`), a `trials` lookup for the sources panel, typed encoding channels, and top-N bar charts (20 categories) for cheap coverage.
  - Phase 3: `gpt-5.4-mini` at low reasoning effort (planning is enum classification; latency matters more than depth). Two calls (the plan; title and notes); an invalid plan is retried once with its error. Anchor = drug, condition or sponsor, since a time period alone charts a capped slice of the whole registry. `POST /api/visualize`, 200 for all statuses. Stated filter = from a field or verbatim in the query. Zero results trigger a probe of each entity alone, to tell "not found" from "over-filtered".
  - Phase 4: a search-first UI following the cited-answer search pattern under its own branding; npm and `openapi-typescript`, so `schemas.py` stays the single source.
  - Phase 5-6: a 2-3 min demo video, and a README that leads with deep citations and condition-anchored networks. No deploy. The zip includes `.git` history, built from a copy without the interview notes. A model comparison was planned, then dropped by the user the same day: the eval stays one model, baseline and after.
- **Phase 3 decide-first** (user approval, 2026-10-04):
  - Plan `analysis` is one enum of registered keys, generated from the registry: the schema makes an unregistered (intent, dimension) unrepresentable, which separate intent and dimension enums would not, and strict structured outputs handle a flat enum more simply than a union per intent.
  - Python, not the LLM, labels filters stated or inferred, applying the §7.3 verbatim test; the LLM could mislabel, and the definition is mechanical.
  - A request field beats a conflicting query value and the override is noted: a structured field is the more deliberate input.
  - A failed title falls back to `default_title` and stays `ok`: the rows are already verified, so prose should not cost the user the chart.
  - Comparisons take 2-4 cohorts, each overriding one entity: covers "A vs B" and "A, B, C" while capping latency at 8 pages and keeping grouped bars readable.
  - Errors split by cause: plan invalid twice or spec failing after repair -> 200 `degraded`; LLM or ClinicalTrials.gov down -> 502, so a frontend can tell "try again" from "rephrase".
  - Date basis closed as start date by year, which Phase 2 already implements; `query` capped at 1,000 characters to bound prompt size.
  - The eval question set moves to Phase 3 step 0, so expected plans exist before the planner prompt and act as its red-first acceptance tests.
- **Product reference pass (2026-10-04).** Taken from the cited-answer product: a right panel with References and Viewer tabs; numbered source cards with metadata chips; an answer element that, when activated, filters its sources; a viewer that opens the source record with the cited passage highlighted plus an "open original" link; export. Adapted: our answer is a chart, so a datum replaces the inline citation marker, and we add reverse highlight (card -> rows), which a text answer cannot offer. Not copied: palette, highlight colour, dotted underlines, floating section pills, typeface, source-icon row, DOCX export. The Viewer is backed by a cached-record endpoint rather than a browser fetch to ClinicalTrials.gov, so it shows the exact record the excerpt check ran against; rows are upserted, so the Viewer re-checks each excerpt and flags a changed record. `sponsor_name` and `conditions` join the trial summary so cards answer "who runs this, and what does it study" (~100 KB on a 2,000-trial response).
- **Copy the reference visual design (user, 2026-10-04).** Supersedes "Not copied: palette, highlight colour, dotted underlines, floating section pills, typeface" above: the frontend now follows the reference product's palette, typeface (Pretendard), card, chip and tab shapes, and its yellow excerpt highlight. Still no Cheiron name or logo. Dark mode dropped (light only) because the reference has none to follow. Tokens sampled from the screenshots are in CLAUDE.md §14 Phase 4.
