# CLAUDE.md: ClinicalTrials.gov Query-to-Visualization Agent

> **What it does:** a Python/FastAPI backend. It takes a natural-language clinical-trials question plus optional structured filters and returns a visualization spec (`type`, `title`, `encoding`, `data`, `meta`) that a frontend can render. The spec is computed from ClinicalTrials.gov Data API records, and every row cites the trials that produced it. This is a take-home for the PhnyX Lab (Cheiron) agent-engineering internship, with a ~24 h time box, delivered as a zip (§2).
>
> **The one thing to understand first:** the LLM never produces a number, count, date, NCT ID, excerpt or data row. It does exactly three things: plan the query, choose the visualization, and write prose. Retrieval, aggregation, citations and checks are deterministic Python, so every row traces back to cached API records by NCT ID (§7.2).
>
> **Design goal (from the assignment):** cover as many query types as possible with one coherent approach that supports multiple visualization types. Broader coverage and richer visualizations, especially meaningful network graphs, score higher than support for a single chart type. Here the coherent approach is one pipeline for every question: plan (intent, dimension, filters) -> registered aggregator -> row shape -> compatible viz type. New coverage means registering an aggregator, never adding a code path (§1 coverage matrix, §7.4).
>
> **Status:** Phase 1 is next (§14). Phase 0 shipped the skeleton, toolchain and CI. The repo is `github.com/kennethsarip/cheiron_task` (private, §12). Not in production, and no deploy is planned (§15).
>
> **Read before coding:** §6 Data model, §7 How things work, §11 Don't do, §14 Roadmap.
>
> **Definition of done:** `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`, all green. CI (`.github/workflows/ci.yml`) runs exactly these. `main` stays runnable.

## Glossary

| Term | In code | Meaning |
|---|---|---|
| query | `query` | The user's natural-language question. It is the only required request field. |
| trial | `trial` | One registered clinical study. The API calls it a "study"; that word appears only inside the API client (§4). |
| record | `record` | One study JSON object as returned by the API and cached. It is the unit of provenance. |
| NCT ID | `nct_id` | Trial identifier (§8.2). Always matched exactly. |
| intervention | `intervention` | One entry in a record's interventions list, which has a `type` and a free-text `name`. |
| drug | `drug` | An intervention that counts as a drug for drug questions and networks. The definition is OPEN (§13.1): the same drug is registered under several types (§6). |
| filter | `filters` | A constraint sent to the API. It is **stated** (from a request field or explicit wording) or **inferred** (from ambiguous wording); see §7.3. |
| assumption | `assumptions` | A disclosed interpretation choice: an inferred filter, the date basis, or a counting rule. |
| plan | `QueryPlan` | The LLM's structured interpretation of a request. It is schema-validated before use. |
| intent | `intent` | Question class: time trend, distribution, comparison, geographic or network (§1). |
| dimension | `group_by` | The record field that rows are grouped on (phase, start year, country, ...). |
| aggregator | `aggregator` | A deterministic function registered per (intent, dimension) that turns records into rows (§7.4). |
| row | `row` | One element of `visualization.data`: a bar, time bucket, node or edge. The assignment calls this a "datum". |
| spec | `visualization` | The `{type, title, encoding, data}` object. |
| encoding | `encoding` | The mapping from row fields to visual channels (`x`, `y`, `series`, nodes/edges). |
| citation | `citations` | `{nct_id, excerpt}` attached to a row (§7.5). |
| excerpt | `excerpt` | A verbatim substring of the cited record. |
| cap | `cap` | The hard limit on records fetched per request. Hitting it is disclosed (§7.3). |
| check | `check` | One deterministic verification rule (§7.6). |
| repair | `repair` | The single regeneration of a spec from the same rows after a failed check (§7.7). |
| status | `status` | The response outcome: `ok`, `clarification_needed`, `no_results` or `degraded` (§7.7). |

## 1. Core loop / inputs

- **In:** `POST` with a required `query` and optional filter fields (§8.3). **Out:** `{status, visualization, meta}` (§8.3).
- **Entity flow:** request -> plan -> API params -> records (cached) -> rows with citations -> spec -> checks -> response.

**Coverage matrix** (the target, one row per question class). Examples come from the assignment appendix, except condition-drug, which comes from the project brief. Intent and dimension names stay descriptive until the plan schema is fixed (§13.1). The LLM picks the viz type from the types compatible with the row shape (§7.2), so the last column is the expected pick, not a hardcoded branch.

| Class | Example question | Dimension | Row shape | Expected viz |
|---|---|---|---|---|
| Time trend | Trials per year for [drug] since 2015; trials started each year for [condition] | start year | temporal | `time_series` |
| Distribution | [condition] trials across phases; most common intervention types | phase; intervention type | categorical | `bar_chart` |
| Comparison | Phases for drug A vs drug B; sponsor classes across two conditions | phase or sponsor class, per cohort | two-categorical | grouped bar |
| Geographic | Countries with the most recruiting trials for [condition] | country | categorical | `bar_chart` |
| Network | Sponsor-drug for [condition]; drug-drug in combination studies; condition-drug | entity pairs | graph | `network_graph` |
| Numeric | None in the appendix | OPEN; enrollment is the only numeric field (§6) | numeric | scatter, histogram |

The type strings for grouped bar, scatter and histogram are OPEN (§8.3).

Happy path (LLM steps marked):
1. Validate the request. Reject contradictory inputs such as `end_year < start_year` (§7.6).
2. **LLM:** map the request to a plan, then validate it against the plan schema and vocabularies (§7.2).
3. If the plan lacks an anchor (drug, condition or time period), return `clarification_needed` (§7.8).
4. Build API params deterministically from the plan, fetch pages up to the cap, and cache the records (§7.3).
5. If zero records come back, return `no_results` with the filters that were applied (§7.8).
6. Dispatch to the aggregator registered for (intent, dimension). It emits rows, each carrying its contributing NCT IDs (§7.4).
7. **LLM:** choose `type` and `encoding` from the types compatible with the row shape, and write the `title` and notes (§7.2).
8. Attach citations (§7.5) and run all checks (§7.6). If a check fails, repair once; if it still fails, return `degraded` (§7.7).
9. Return `ok` with the spec and `meta`: filters, assumptions, cap and prune disclosures, and source.

## 2. Scope

**Context**
- The assignment is a generic pharma-domain agent problem, not a Cheiron product feature.
- What the interviewer said they grade: planning over implementation; evidence that alternatives were explored; how hallucination is planned against and accuracy maintained; the user's perspective. If a system constraint makes the result useless to the user, find a workaround.
- Factual boundary: the CTO said the team is *thinking of* building a knowledge graph. Do not present a production knowledge graph or GraphRAG as part of Cheiron's stack.

**Grading weights** (from the assignment; they drive priority)

| Weight | Criterion | Earned here by |
|---|---|---|
| 35% | System design | planner/compute split (§7.2), aggregator registry (§7.4), rejected alternatives (§13.3), real-world data handling (§6, §7.8) |
| 20% | AI / agent design | no hallucination-prone steps, deterministic checks (§7.6), validated planning |
| 20% | Code quality | readability, organization, docs, correctness, robustness |
| 15% | Query & viz coverage | every question class with no one-off hacks (§1 coverage matrix); meaningful network graphs score higher (§7.4) |
| 10% | Input/output design | unambiguous, frontend-friendly schemas (§8.3) |
| Bonus | Deep citations | `{nct_id, excerpt}` on every row, including network edges (§7.5) |

**Admission rule:** every component must answer four questions in the README or §13. (1) What failure does it prevent? (2) What evidence shows that failure occurs? (3) How do we test that it helps? (4) What cost, latency or new failure mode does it add?

**In scope**
- One FastAPI endpoint that turns a natural-language query plus optional filters into a visualization spec (§8.1).
- Documented request and response schemas: field names, types, required/optional, and validation.
- Live ClinicalTrials.gov API retrieval behind a Postgres response cache.
- Deterministic aggregation for every question class (§1). Viz types: bar, grouped bar, time series, scatter, histogram and network graph.
- Deep citations on every row, including network edges.
- Explicit statuses and handling of the edge cases in §7.8.
- An eval set of ~20-25 questions with a baseline run and an after run, both kept (§9).
- The submission zip: code; the README (how to run, schemas, design decisions and tradeoffs, limitations and what more time would improve, AI tools used, how correctness was validated, and what was designed deliberately versus generated and adapted); and 3-5 example runs with the actual JSON outputs.

**Out of scope**
- A frontend renderer (optional bonus, §13.4).
- Every rejected alternative in §13.3: vector or semantic retrieval (embeddings, rerankers, ANN indexes), LLM-generated aggregates, agent frameworks (LangChain, LlamaIndex, Haystack, CrewAI, AutoGen), multi-agent or iterative retrieval, a local pre-cached corpus, and knowledge graphs or GraphRAG.
- Data sources other than ClinicalTrials.gov (PubMed, FDA documents, guidelines, internal documents).
- Synonym or controlled-vocabulary resolution of inputs (deferred, §13.4).
- Cheiron-product-specific features.

## 3. Tech stack

| Layer | Choice | Note |
|---|---|---|
| Language | Python >=3.12 | Dev interpreter pinned to 3.12 in `.python-version`; the floor is set for reviewer compatibility |
| API framework | FastAPI | Request and response models use Pydantic, FastAPI's model layer |
| Database | Postgres | Response cache only. Schema TBD (§6) |
| Data source | ClinicalTrials.gov Data API v2 | The authoritative source. No API key needed (verified 2026-10-04). Facts in §8.4 |
| LLM | OpenAI | The company supplied the key. Model is OPEN (§13.1). Used only for planning, viz selection and prose (§7.2) |
| Orchestration | Hand-rolled Python | No agent frameworks; they abstract away the exact decisions being graded |
| Vector DB | None | Typed API fields answer these questions exactly (§13.3) |
| HTTP client, DB driver, migrations | TBD | Chosen in Phase 1 (§13.1) |
| Package manager | uv | `uv.lock` is committed; reviewers run `uv sync` |
| Lint / format / typecheck / test | ruff / ruff format / mypy (strict, pydantic plugin) / pytest | All configured in `pyproject.toml` |
| CI | GitHub Actions | Runs the Definition of done on every push to `main` and every PR |

**Architecture:** client -> FastAPI app -> {LLM API (plan, viz choice, prose); ClinicalTrials.gov API through the Postgres cache}. Secrets (`OPENAI_API_KEY`, `DATABASE_URL`) live only in `.env` and are read through `app/config.py`. Auth model: TBD (§13.1).

**Hard rules:** no agent frameworks; no embeddings for record retrieval; every LLM output is parsed and schema-validated before any code uses it.

## 4. Repository structure

Created in Phase 0. Every module except `main.py` and `config.py` holds only a docstring until its phase. Keep this tree in sync.

```
CLAUDE.md            # spec + working context (this file)
README.md            # human run guide; doubles as the submission README (§2)
BUILD_HISTORY.md     # shipped log + reasoning behind §13.2 decisions
.env.example         # every env var, blank; parity with config.py is tested
pyproject.toml       # SINGLE SOURCE: dependencies + ruff, mypy, pytest config
uv.lock              # locked dependency versions (committed)
.python-version      # dev interpreter pin (3.12)
.github/workflows/   # ci.yml: runs the Definition of done
.vscode/             # shared editor settings: .venv interpreter, ruff on save, pytest
app/
  main.py            # FastAPI app + route only; no per-intent branching
  config.py          # SINGLE SOURCE: every setting, read from env vars
  schemas.py         # SINGLE SOURCE: request, plan, LLM-output and response models (§8)
  vocab.py           # SINGLE SOURCE: API enums + display labels (§8.4)
  llm.py             # the only module that calls the LLM; returns validated models
  planner.py         # request -> plan (prompt + validation)
  viz.py             # row shape -> allowed viz types; LLM viz choice + prose; spec assembly
  ctgov.py           # API client: params from plan, pagination, cap
  cache.py           # Postgres read/write of API responses
  normalize.py       # record -> normalized fields; applies counting rules (§6)
  aggregators/       # one module per aggregator; registry.py = SINGLE SOURCE of dispatch
  citations.py       # {nct_id, excerpt} per row, from cached records only
  checks.py          # every §7.6 check
  pipeline.py        # §1 steps, repair-once, status selection, error -> status mapping
migrations/          # SINGLE SOURCE of DB schema truth
tests/               # unit + contract tests; small synthetic fixtures (§9)
eval/                # eval questions, runner, baseline + after results (§9)
examples/            # 3-5 real request/response JSON pairs from the running system
```

## 5. Commands

| Task | Command |
|---|---|
| Setup | `uv sync`, then `cp .env.example .env` and fill it in |
| Run API | `uv run --env-file .env uvicorn app.main:app --reload` (docs at `http://127.0.0.1:8000/docs`) |
| Lint | `uv run ruff check . && uv run ruff format --check .` (auto-fix: `uv run ruff check --fix . && uv run ruff format .`) |
| Typecheck | `uv run mypy` |
| Test | `uv run pytest` |
| Add a dependency | `uv add <pkg>` (dev only: `uv add --dev <pkg>`); state why in the commit (§11) |
| Migrate | TBD with the cache schema (§13.1) |
| Eval run | TBD (Phase 4) |
| Deploy | n/a (§15) |

API probe (works now): `curl -s 'https://clinicaltrials.gov/api/v2/studies?query.intr=pembrolizumab&pageSize=1&countTotal=true&fields=NCTId'`

## 6. Data model

**Schema truth:** `migrations/`, once it exists. The cache tables are OPEN, because the data model is hard to reverse (§13.1). Any cache schema must meet these requirements:
- Store each API response verbatim, because excerpts are checked as substrings of their record (§7.6).
- Key the cache on the exact API params, so an identical request reuses identical records. Example runs and eval runs depend on this.
- Keep `nct_id` per record for exact lookup.
- Record the fetch time, so staleness is visible (TTL is OPEN).

**Normalized record** (in memory, produced by `normalize.py`). Source paths sit under `protocolSection`; all were verified against the live API on 2026-10-04.

| Field | Type | Unit | Source | Notes |
|---|---|---|---|---|
| nct_id | str | - | identificationModule.nctId | Exact match only |
| brief_title | str | - | identificationModule.briefTitle | |
| phases | list[Phase] | - | designModule.phases | A list: may hold 2 values or be absent. Counting rule OPEN |
| overall_status | Status | - | statusModule.overallStatus | |
| start_date | str | day or month | statusModule.startDateStruct.date | `YYYY-MM-DD` or `YYYY-MM`; may be absent |
| start_year | int | year | derived from start_date | |
| sponsor_name | str | - | sponsorCollaboratorsModule.leadSponsor.name | Free text |
| sponsor_class | AgencyClass | - | sponsorCollaboratorsModule.leadSponsor.class | |
| interventions | list[{type, name}] | - | armsInterventionsModule.interventions | `name` is free text as registered |
| conditions | list[str] | - | conditionsModule.conditions | Free text |
| countries | set[str] | - | contactsLocationsModule.locations[].country | One entry per site; dedupe per trial |
| enrollment | int or None | participants | designModule.enrollmentInfo.count | May be absent |
| study_type | StudyType | - | designModule.studyType | |

**Messy-value evidence.** These counts come from 1,000 records for `query.intr=pembrolizumab` (2,968 total), fetched 2026-10-04:
- Phases: 155 PHASE1+PHASE2, 17 PHASE2+PHASE3, 50 with no phase, 14 NA.
- Start dates: 83 at month precision, 2 missing. Enrollment: 2 missing.
- Countries: 541 trials repeat a country across sites; 242 trials span several countries.
- Interventions: interventions named pembrolizumab are typed DRUG 617 times, BIOLOGICAL 243 times, plus 5 other types. 168 of the records have no intervention name containing "pembrolizumab". Placebo appears 50 times, and non-drug items such as "laboratory biomarker analysis" (37) also show up.

**IDs:** `nct_id` (§8.2) is the only trial ID. Internal IDs (request, eval run) are OPEN.
**Timestamps:** OPEN (§13.1).
**Numeric precision:** every value is an integer count or integer enrollment, so floats never appear. Specify rounding in §8.5 before adding any ratio.
**JSON shapes:** see §8.3.

## 7. How things work

### 7.1 Pipeline
The steps are in §1. Only steps 2 and 7 touch the LLM; everything else is deterministic and unit-testable without it.

### 7.2 LLM boundary
| The LLM may output | The LLM never outputs |
|---|---|
| Plan fields restricted to enums and `vocab.py` values | Counts, sums or any number in `data` |
| Entity strings and filter values taken from the request | Dates or years as data values |
| A viz type from the set allowed for the row shape | NCT IDs or excerpts |
| Encoding field names from the aggregator's declared columns | Rows |
| Title, notes and assumption wording | Anything a check cannot validate |

Why: in a visualization agent, the hallucination-prone step is letting the model emit data. Keeping the model in a schema-validated planning role makes numeric hallucination structurally impossible, rather than something to detect afterwards. Two things are OPEN (§13.1): whether planning and viz selection are one LLM call or two, and what happens when planner output fails validation.

### 7.3 Retrieval
- API params come only from the validated plan, never from raw LLM text.
- `query.*` params are searches, not exact filters, and the API expands drug synonyms. `query.intr` returns 2,968 trials for pembrolizumab, Keytruda and MK-3475 alike. Consequences: a matched record may not contain the user's wording, so excerpts quote the record's own values (§7.5); network nodes need name normalization (§13.1); and synonym resolution has a lower priority (§13.4).
- Unambiguous filters (dates, status, phase, country) are applied hard. A filter inferred from ambiguous wording is disclosed as an assumption, because a wrong silent filter removes the correct answer. The rule for classifying a filter as stated or inferred is OPEN (§13.1).
- Paginate with `nextPageToken` at `pageSize` 1000 (the API clamps larger values to 1000) and stop at the cap (value OPEN). Send `countTotal=true` so `meta` can report "fetched N of total M" when capped.
- Cache by API params (§6). Upstream error policy (timeouts, 5xx, rate limits) is OPEN.

### 7.4 Aggregation
- A registry maps (intent, dimension) to an aggregator. Route handlers never branch on question type, so a new question class means a new registered aggregator plus its tests.
- Each aggregator declares its output columns and row shape (categorical, two-categorical, temporal, numeric or graph). Viz selection and checks read that declaration.
- Every row carries the set of contributing NCT IDs, by construction. A count is the size of that set (§8.5).
- Time series zero-fill gap years, because a missing year is information, not missing data. Granularity is OPEN.
- Networks are co-occurrence aggregations over records, not graph retrieval. A node is an entity; an edge's weight is the number of trials in which both endpoints appear, and the edge carries those NCT IDs. Dense graphs are pruned by minimum edge weight and top-N degree (thresholds OPEN), and `meta` records what was pruned.
- A network is meaningful only if each node is one real entity and each edge stands for shared trials. That depends on two OPEN items (§13.1). Without node name normalization, synonyms split one drug into several nodes. Without a `drug` definition, placebo and non-drug items such as lab tests become nodes (§6 evidence).
- Messy values are data, not errors. Each one gets a documented counting rule (OPEN, §13.1), and records excluded by a rule are counted in `meta`.

### 7.5 Citations
- Every row gets `citations: [{nct_id, excerpt}]`, built from cached records and never from LLM output.
- `excerpt` is the verbatim record value that placed the trial in this row, such as `"PHASE3"` or an intervention name. Which field supplies the excerpt per dimension, and the citation cap per row, are OPEN.
- Network edges carry citations as well as nodes.

### 7.6 Validation: BLOCK vs WARN
**BLOCK, at the request** (before any LLM or API call): schema errors, and contradictory inputs such as `end_year < start_year`. Reject with a clear message; never return an empty chart.

**BLOCK, at the spec** (a failure triggers repair, then `degraded`):

| Check | Rule |
|---|---|
| schema | The response round-trips through the response model |
| encoding | Every field named in `encoding` exists in every row |
| shape | The viz type fits the row shape. A network needs nodes + edges, a time series needs an ordered temporal dimension, and a grouped bar needs two categorical dimensions |
| citation ids | Every cited `nct_id` is in the retrieved record set |
| excerpts | Every excerpt is a verbatim substring of its record |
| reconciliation | Row counts reconcile with record counts per §8.5. No invented sums |
| assumptions | `assumptions` is non-empty whenever any filter was inferred |

**WARN** (disclosed in `meta`; the response stays `ok`): cap hit, records excluded by a counting rule, network pruned.

### 7.7 Failure policy and statuses
- If a spec check fails, regenerate the spec once from the same rows. Never re-query the API to fix a spec problem. If it still fails, return `degraded` with an explicit error. The other statuses are set in §1 steps 3, 5 and 9.
- Abstaining and asking for clarification are correct outputs, not fallbacks. A system that always produces a fluent answer has no observable failure mode.

### 7.8 User-facing edge cases
| Case | Behavior |
|---|---|
| Underspecified ("show me trials") | `clarification_needed`, naming the missing drug, condition or time period. Never guess. The anchor rule is OPEN |
| Zero results | `no_results`, listing the filters applied. Never silently widen the search |
| Nonexistent drug or condition | Report it as not found. Never answer about a similar entity. The API returns HTTP 200 with `totalCount` 0 both for unknown terms and for over-filtered queries, so telling the two apart is OPEN |
| Very broad query ("cancer") | Paginate to the cap and disclose a capped sample with the total |
| Messy values, dense network, contradictory inputs | Handled by §7.4 (counting rules, pruning) and §7.6 (request rejection) |

## 8. Interfaces & contracts

### 8.1 Endpoints
| Method | Path | Purpose | Status codes |
|---|---|---|---|
| POST | TBD | Natural-language query -> visualization spec | 422 for request validation (FastAPI default). The HTTP code for each `status` and for upstream or LLM failures is OPEN |

### 8.2 ID formats
- `nct_id` matches `^NCT\d{8}$` and is matched exactly. A missing ID is reported as not found, never replaced by the nearest match.
- Internal IDs: OPEN.

### 8.3 Request and response
**Request.** The optional fields are the assignment's candidate examples; the final set is OPEN. The API params are verified to work (§8.4), but each mapping is still a candidate.

| Field | Type | Required | Candidate API param | Validation |
|---|---|---|---|---|
| query | string | yes | - | Non-empty; max length OPEN |
| drug_name | string | no | `query.intr` | |
| condition | string | no | `query.cond` | |
| trial_phase | Phase | no | `filter.advanced=AREA[Phase]...` | Must be a §8.4 value |
| sponsor | string | no | `query.spons` | |
| country | string | no | `query.locn` | |
| start_year, end_year | int | no | `filter.advanced=AREA[StartDate]RANGE[...]` | `start_year <= end_year` |

**Response.** The shape comes from the assignment, plus `status` and `citations`:
```json
{"status": "ok",
 "visualization": {"type": "bar_chart", "title": "Trials by Phase for Pembrolizumab",
   "encoding": {"x": {"field": "phase"}, "y": {"field": "trial_count"}},
   "data": [{"phase": "Phase 3", "trial_count": 41,
             "citations": [{"nct_id": "NCT01234567", "excerpt": "PHASE3"}]}]},
 "meta": {"filters": {"drug_name": "Pembrolizumab"}, "source": "clinicaltrials.gov", "assumptions": []}}
```
- `type` values from the assignment: `bar_chart`, `time_series`, `network_graph`. The strings for grouped bar, scatter and histogram are OPEN.
- `encoding` channels: `x`, `y`, `series`. The node/edge shape for networks is OPEN.
- `meta` must carry: filters (stated vs inferred), source, assumptions, units, sorting, time granularity, grouping, cap disclosure (fetched vs total), excluded-record counts and pruning. Exact keys are OPEN.
- The contents of `visualization` when `status != ok` are OPEN.
- Frontend: none is built (§2), so there are no routes, state model or UX rules. This section is the renderer contract.

### 8.4 ClinicalTrials.gov API facts (verified 2026-10-04, apiVersion 2.0.5)
- Base URL `https://clinicaltrials.gov/api/v2`. `GET /studies` returns `{totalCount, studies, nextPageToken}`; `fields=` trims the payload.
- Verified params: `query.intr`, `query.cond`, `query.spons`, `query.locn`, `filter.overallStatus`, and `filter.advanced` with `AREA[Phase]PHASE3` and `AREA[StartDate]RANGE[2015-01-01,MAX]`.
- Enums (`GET /studies/enums`). `vocab.py` mirrors them, and display labels (e.g. `PHASE1` -> "Phase 1") live only there:
  - Phase: NA, EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4
  - Status: ACTIVE_NOT_RECRUITING, COMPLETED, ENROLLING_BY_INVITATION, NOT_YET_RECRUITING, RECRUITING, SUSPENDED, TERMINATED, WITHDRAWN, AVAILABLE, NO_LONGER_AVAILABLE, TEMPORARILY_NOT_AVAILABLE, APPROVED_FOR_MARKETING, WITHHELD, UNKNOWN
  - InterventionType: BEHAVIORAL, BIOLOGICAL, COMBINATION_PRODUCT, DEVICE, DIAGNOSTIC_TEST, DIETARY_SUPPLEMENT, DRUG, GENETIC, PROCEDURE, RADIATION, OTHER
  - AgencyClass (sponsor class): NIH, FED, OTHER_GOV, INDIV, INDUSTRY, NETWORK, AMBIG, OTHER, UNKNOWN
  - StudyType: EXPANDED_ACCESS, INTERVENTIONAL, OBSERVATIONAL
- Rate limits: not verified.

### 8.5 Formulas
- A row's `trial_count` is the number of distinct NCT IDs in its provenance set.
- **Single-valued dimension** (e.g. status): the row counts sum to records retrieved minus records excluded, and every exclusion is disclosed.
- **Multi-valued dimension** (countries, interventions, phases if split): sums may exceed the record count, but each row still equals its own distinct NCT ID count.
- A network edge's weight is the number of distinct NCT IDs in which both endpoints appear.

## 9. Testing

**Safety net:** the unit and contract tests make up the Definition of done and must not need the network or the LLM. The eval harness is separate and runs live.

| Layer | Covers |
|---|---|
| Contract | Request validation (including contradictory years), response round-trip, `.env.example` <-> `config.py` parity in both directions |
| Normalize | Each counting rule, on synthetic records shaped like the §6 evidence |
| Aggregators | Each registered aggregator. Expected rows are computed by hand from the fixture, never copied from output |
| Checks | Each §7.6 check, with one passing and one failing fixture |
| API client | Param building, pagination and the cap, against small recorded fixtures |
| Planner / viz | Parsing and validation of LLM output with a stubbed LLM, including malformed output |
| Eval | 20-25 questions: every §1 class plus ambiguous input, a zero-result combination, a nonexistent entity, a contradictory date range, multi-phase or missing-field records, and a very broad condition. For each question, record the intent, viz type, record count, check pass/fail, latency and failure mode |

**Eval protocol:** run the baseline, fix the largest failure class, rerun, and keep both result sets in `eval/`.

**Adding a test:** put the fixture in `tests/` and keep it small and synthetic. Derive the expected output from the source of truth (the API docs, §6 or the assignment), not from current behavior.

## 10. Conventions

- **Naming:** snake_case JSON keys (`trial_count`, `nct_id`), matching the assignment examples. Use glossary words only.
- **Typing:** full type hints. Every boundary (request, plan, LLM output, response) is a Pydantic model in `schemas.py`.
- **Errors:** typed exceptions, mapped to statuses in exactly one place (`pipeline.py`). Log with context through `logging`.
- **Size:** functions stay at ~50 lines or fewer, with one responsibility per module (§4).
- **Comments:** only the non-obvious WHY.
- **Components:** every new component passes the admission rule (§2).

## 11. Don't do

**Security and config**
- Don't commit secrets. Keys live only in a gitignored `.env`; rotate any key that leaks.
- No secret in a client-exposed env var (`VITE_*`, `NEXT_PUBLIC_*`); those ship to the browser.
- Don't hardcode configuration. Every setting comes from env vars through one config module.

**Repo hygiene**
- Don't commit build output, dependencies, caches (`node_modules/`, `.venv/`, `dist/`, `__pycache__/`) or real/large data files. Test fixtures stay small and synthetic.
- Don't force-push `main`. Don't merge with red lint, types or tests.

**Code**
- Don't invent APIs, fields or dependencies not in this doc. If one is missing, add it to §13 and ask.
- Don't add a dependency without stating why. Prefer the standard library or what is already installed.
- Don't duplicate logic. Keep one source of truth, because a second copy drifts silently.
- Don't swallow errors. Fail loudly or log with context. No `print` for logging.
- Don't use floats where exactness matters (money, measurements). Use a decimal type end to end.
- Don't write functions over ~50 lines or clever one-liners that hurt readability.
- Don't add comments that restate the code. Comment only the non-obvious WHY.
- Don't expand scope beyond the task. Note follow-ups in §13 instead.
- Don't run destructive or irreversible operations (data deletes, prod migrations, force operations) without explicit confirmation. Prefer reversible changes.

**Testing and honesty**
- Don't skip, disable or weaken a failing test to move on. If something is knowingly broken, mark it strict-xfail with the reason.
- Author expected outputs from the source of truth, never from current behaviour. A test generated from current output certifies its bugs.
- Don't mark work done if a step was skipped or a test failed. Report what and why.

**Docs and token efficiency**
- Keep docs concise. Don't paste large code blocks, file dumps or logs into docs; reference `file:line` instead.
- Update CLAUDE.md in the same commit as the change it describes.
- Read only the file sections you need, and don't re-read files already in context.

**Project-specific**
- Don't let any number, count, date, NCT ID, excerpt or row pass through the LLM (§7.2); numeric hallucination is structurally impossible only if no data value comes from the model.
- Don't add an agent framework; it hides the orchestration decisions being graded.
- Don't add embeddings, vector search or rerankers over trial records; typed API filters are exact, and embeddings blur IDs and labels.
- Don't branch on question type in route handlers; register an aggregator (§7.4), or coverage turns into one-off hacks.
- Don't substitute a similar entity or NCT ID for one that wasn't found; a near match answers a different question.
- Don't silently widen a search, apply an inferred filter or truncate results; each one hides why the answer looks the way it does (§7.8).
- Don't drop records with missing or multi-valued fields without a documented rule and a count in `meta`; they are data, not errors.
- Don't re-query the API to repair a spec; a repair must reuse the same rows (§7.7) so the data never shifts mid-request.
- Don't build synonym resolution, multi-agent or iterative retrieval without a logged eval failure that justifies it (§13.4).
- Don't write `examples/` or eval results by hand; they must be actual system output.
- Don't claim in the README that an approach was evaluated unless the comparison was actually run.
- Don't say the interviewer requested RAG, Supabase, GraphRAG or multi-agent, or that Cheiron runs a production knowledge graph; neither was said (§2).

## 12. Repo & GitHub practices

- Required files:
  - `README.md`: human setup and run guide, separate from CLAUDE.md.
  - `BUILD_HISTORY.md`: the shipped log.
  - `.env.example`: every env var, blank. Ideally a test enforces that it matches what the config module reads, in both directions.
  - `.gitignore`.
- Commit lockfiles.
- `main` is always runnable. Use one short branch per milestone and merge only when its "Done when" passes and CI is green.
- CI runs exactly the Definition-of-done commands, so local green means CI green.
- Commits are small, present tense and scoped (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), referencing the milestone. Tag `main` at each finished milestone.
- PR descriptions cover what changed, why, and how it was tested.
- If pushing to `main` auto-deploys, code review and the quality gate run BEFORE the push, never after.

Project additions:
- Remote `origin` is `github.com/kennethsarip/cheiron_task`. It is private because this file holds interview and company notes (§2 Context); keep it private unless those notes move out.
- The submission zip excludes `.env`, caches and dependencies. Whether it includes `.git` history is OPEN (§13.1).

## 13. Open decisions / TODO

### 13.1 Needs a spec
Items marked **ask first** are hard to reverse; ask the user before choosing them.

| Item | What needs deciding |
|---|---|
| Cache schema (**ask first**) | Tables, JSON storage type, TTL, timestamp type, how Postgres runs locally (§6) |
| Internal ID scheme (**ask first**) | IDs for requests and eval runs (§8.2) |
| Auth model (**ask first**) | Who may call the endpoint |
| Hosting (**ask first**) | Whether to host at all (§15) |
| LLM model (**ask first**) | The provider is OpenAI (§3); the model name goes in `OPENAI_MODEL` |
| Phase 1 libraries | HTTP client, Postgres driver, migrations tool. Add each with `uv add` and a stated reason (§11) |
| Response contract | Endpoint path, HTTP code per `status`, `visualization` when `status != ok`, `meta` keys, viz type strings, network node/edge shape (§8.3) |
| Request fields | Final set and max lengths (§8.3) |
| Source documents | Save the assignment prompt and project brief in the repo; they are the source of truth for tests and README claims |
| Plan schema | Intent and dimension enums; how a comparison (A vs B) encodes multiple cohorts, e.g. one API query per cohort |
| LLM calls | One call or two (plan; viz + prose); policy when planner output fails validation |
| Clarification rule | Which anchors a query must have (§7.8) |
| Stated vs inferred filters | Proposal: stated if and only if the value comes from a request field or appears verbatim in `query` (§7.3) |
| Not-found vs zero results | Proposal: probe the entity alone, without the other filters (§7.8) |
| Date basis and granularity | Start date vs first-posted date for "trials per year"; year vs finer buckets |
| Counting rules | Multi-phase, missing or NA phase, missing start date, missing enrollment, multi-country (§6 evidence) |
| `drug` definition | Type alone fails: pembrolizumab is registered as both DRUG and BIOLOGICAL. Also decide placebo and non-drug interventions (§6) |
| Networks | Name normalization, since synonyms and code names (e.g. MK-3475) would split one drug into several nodes (§7.3); pruning thresholds (§7.4); whether to add investigator or site networks (the assignment lists both as entities; their source fields are not yet verified) |
| Scatter and histogram | Which fields they use; enrollment is the only numeric field in §6 |
| Citations | Excerpt field per dimension; citation cap per row (§7.5) |
| Cap value | Alternative to evaluate: exact per-bucket totals via `countTotal=true` queries, with citations from the sample |
| Upstream errors | Timeouts, retries, rate limits (§7.3) |
| Zip contents | Whether to include `.git` history as evidence of iteration (§12) |

### 13.2 Decided
The reasoning lives in `BUILD_HISTORY.md` under Decisions.
- Toolchain: uv, ruff, mypy (strict), pytest, Python >=3.12, GitHub Actions CI.
- LLM provider: OpenAI (company-supplied key).
- The GitHub repo is private (§12).
- Stack: Python, FastAPI, Postgres; hand-rolled orchestration.
- The LLM is limited to planning, viz selection and prose (§7.2).
- Retrieval uses structured API queries, not semantic search.
- Data comes from the live API through a Postgres response cache, not from a local corpus.
- Aggregation dispatches through an (intent, dimension) registry.
- Networks are co-occurrence aggregations, with citations on edges.
- Statuses: `ok`, `clarification_needed`, `no_results`, `degraded`.
- A spec gets one repair from the same rows, then `degraded`.
- Gap years are zero-filled; capped samples and pruning are disclosed; contradictory inputs are rejected.

### 13.3 Descoped deliberately
| Alternative | Why rejected |
|---|---|
| Vector / semantic retrieval over records | Typed API filters are exact; embeddings blur IDs and categorical labels and add latency plus a new failure mode |
| LLM-generated aggregates | Numeric hallucination, which §7.2 removes structurally |
| Agent framework | Hides the orchestration decisions being graded |
| Multi-agent / iterative retrieval | No measured failure justifies the latency and debugging surface |
| Locally pre-cached corpus | Fast and reproducible, but goes stale; live API + cache is the middle ground |
| Knowledge graph / GraphRAG | Not an assignment requirement; the networks here are co-occurrence aggregations |

### 13.4 Deferred
- Synonym resolution of inputs. Trigger: an eval run logs a zero-result query that a synonym would have fixed. The API already expands drug synonyms (§7.3).
- Frontend demo, deployed endpoint or demo video (optional bonus).

### 13.5 Decided by assumption
| Assumption | Falsified if |
|---|---|
| The API needs no key and tolerates our request rate | Responses come back 401, 403 or 429 |
| Listing "vector databases" in the stack does not require using one; a documented rejection shows judgment | The assignment or interviewer says one is required |
| A capped sample with a disclosed total is useful for broad queries | Eval shows the sample's distribution differs materially from per-bucket totals |

## 14. Roadmap (what is left to build)

**Ship-then-prune rule:** when a phase's "Done when" passes, delete the phase from here and add a 1-2 line entry to `BUILD_HISTORY.md` in the SAME commit.

**Phase 1: Retrieval and cache.** Goal: a hand-written plan (no LLM yet) produces cached, normalized records.
- First decide, asking the user: the cache schema, local Postgres setup and Phase 1 libraries (§13.1).
- `ctgov.py` (params, pagination, cap, `countTotal`), the cache migration, `cache.py`, and `normalize.py` with the counting rules.
- Done when: fixture tests for params, pagination, cap and normalization pass; a live pembrolizumab fetch returns records; and an identical second call is served from the cache.

**Phase 2: Aggregation, citations, checks.** Goal: deterministic, verified rows for every question class.
- The registry; aggregators for time trend, distribution, comparison, geographic, and networks (sponsor-drug, drug-drug, condition-drug); `citations.py`; `checks.py`; spec assembly with a fixed viz choice.
- Done when: every §1 coverage-matrix row has a registered aggregator (Numeric once its field is decided); every aggregator test passes against hand-computed rows; and every §7.6 check has a passing and a failing fixture.

**Phase 3: LLM planning and endpoint.** Goal: an end-to-end natural-language request returns a response with the right status.
- First decide, asking the user: the OpenAI model (§13.1).
- `llm.py`, `planner.py`, the LLM half of `viz.py`, repair-once, status selection, the endpoint.
- Done when: one query per §1 class returns `ok` with all checks passing, and each §7.8 case returns its specified behavior.

**Phase 4: Eval and iteration.** Goal: measured evidence of iteration.
- The 20-25 question set and runner (§9); a baseline run; a fix for the largest failure class; a rerun.
- Done when: both result sets are saved in `eval/` with per-question metrics, and the README cites only comparisons that were actually run.

**Phase 5: Submission.** Goal: the zip.
- README sections (§2 In scope), 3-5 example runs captured from the live system into `examples/`, a zip built from a clean checkout.
- Done when: the zip, unpacked fresh, installs and runs per the README and contains the code, README and examples.

## 15. Production & ops

Not deployed; the service runs locally only. A deployed endpoint is an optional bonus (§13.4). Monitoring, backups, secret rotation and a runbook are placeholders until a deploy exists. The secret rules in §11 apply now.
