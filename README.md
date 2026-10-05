# ClinicalTrials.gov Query-to-Visualization Agent

A backend service that turns a natural-language clinical-trials question into a structured,
frontend-renderable visualization spec built from ClinicalTrials.gov Data API records. Every bar,
time bucket, point, network node and network edge cites the trials that produced it. A React
frontend renders the specs, with a sources panel and a record viewer for the citations.

**The one design idea:** the LLM never produces a number, count, date, NCT ID, excerpt or data row.
It does two things: it classifies the question into a schema-validated plan, and it writes the
title. Retrieval, aggregation, the choice of chart type, citations and verification are
deterministic Python, so every datum traces back to a cached API record by NCT ID.

- Request and response contract: [SCHEMAS.md](SCHEMAS.md) (one example per viz type)
- Real outputs: [`examples/`](examples/) and the eval runs in [`eval/results/`](eval/results/)
- Build log with the reasoning behind every decision: [BUILD_HISTORY.md](BUILD_HISTORY.md)
- Demo video: [Loom walkthrough](https://www.loom.com/share/fd2ac9d61ddc41d1b0b3a27423f0b2f4)

## Contents

1. [Run it](#run-it)
2. [How it works](#how-it-works)
3. [Decisions I made deliberately](#decisions-i-made-deliberately)
4. [What was intended vs what was adapted](#what-was-intended-vs-what-was-adapted)
5. [How correctness was validated](#how-correctness-was-validated)
6. [AI tools used, and what was designed vs generated](#ai-tools-used-and-what-was-designed-vs-generated)
7. [Example runs](#example-runs)
8. [Limitations and what more time would improve](#limitations-and-what-more-time-would-improve)

## Run it

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.12), Docker with Compose, and
Node.js 24+ with npm. You need an OpenAI API key; ClinicalTrials.gov needs none.

```bash
uv sync
cp .env.example .env   # fill in OPENAI_API_KEY and DATABASE_URL (Compose value below)
docker compose up -d   # local Postgres on 127.0.0.1:5432
uv run --env-file .env python -m app.migrate   # create the cache tables; safe to rerun
uv run --env-file .env uvicorn app.main:app --reload   # API docs: http://127.0.0.1:8000/docs
```

`DATABASE_URL` for the Compose database is `postgresql://cheiron:cheiron@127.0.0.1:5432/cheiron`.

Frontend, in a second terminal (it proxies `/api` to port 8000):

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Or call the API directly:

```bash
curl -s -X POST http://127.0.0.1:8000/api/visualize -H 'content-type: application/json' \
  -d '{"query": "Which drugs frequently co-occur in combination studies for melanoma?"}'
```

**Quality checks** (CI runs exactly these):

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm test && npm run check:types
```

Live tests (real OpenAI and ClinicalTrials.gov) are excluded by default:
`uv run --env-file .env pytest -m live`. The eval: `uv run --env-file .env python -m eval.run eval/results/<name>.json`.

## How it works

```
request ─► validate ─► LLM plan (strict JSON schema) ─► Python guards ─► API params
        ─► ClinicalTrials.gov (paged, Postgres cache) ─► conformance filter
        ─► registered aggregator ─► rows + nct_ids ─► viz type from row shape
        ─► citations ─► 15 checks ─► (repair once) ─► response
                         ▲
        LLM title runs in parallel with the fetch; it sees the plan, never the rows
```

| Step | Module | LLM? |
|---|---|---|
| Request validation (e.g. `end_year < start_year` -> 422) | `schemas.py` | no |
| Plan: one `analysis` enum key, filters, cohorts, verbatim constraint quotes | `planner.py`, `llm.py` | **yes** |
| Anchor rule, constraint guards, stated vs inferred filters | `planner.py` | no |
| Retrieval, pagination to a 10,000 cap, rate limit, cache | `ctgov.py`, `cache.py` | no |
| Normalization and counting rules for messy values | `normalize.py`, `entities.py` | no |
| Aggregation, dispatched by `(intent, dimension)` | `aggregators/registry.py` | no |
| Viz type and encoding, read off the row shape | `viz.py` | no |
| Citations `{nct_id, excerpt, field}` | `citations.py` | no |
| Checks, repair, status selection | `checks.py`, `pipeline.py` | no |
| Verification ledger (`meta.verification`, every status) | `verification.py` | no |
| Title and notes | `viz.py`, `llm.py` | **yes** (no row values) |

Four statuses, all HTTP 200: `ok`, `clarification_needed`, `no_results` and `degraded`. A dependency
outage is a 502. Asking for clarification is a correct answer, not a fallback.

## Decisions I made deliberately

These are the choices I set the direction on. The full reasoning, with dates and evidence, is in
[BUILD_HISTORY.md → Decisions](BUILD_HISTORY.md#decisions).

### 1. One pipeline: categorize every question, never add a code path per question

The assignment rewards coverage "without one-off hacks". So before writing code I sorted the
appendix questions into six classes, and made each class a combination of an **intent** and a
**dimension** rather than a special case:

| Class | Example | Row shape | Viz type |
|---|---|---|---|
| Time trend | Trials per year for pembrolizumab since 2015 | temporal | `time_series` |
| Distribution | Breast cancer trials across phases; top sponsors | categorical | `bar_chart` |
| Comparison | Phases for pembrolizumab vs nivolumab | two-categorical | `grouped_bar_chart` |
| Geographic | Countries with the most recruiting cystic fibrosis trials | categorical | `bar_chart` |
| Network | Drug-drug co-occurrence for melanoma; sponsor-drug; condition-drug | graph | `network_graph` |
| Numeric | Enrollment sizes for adalimumab; enrollment over time | binned / per-trial numeric | `histogram` / `scatter_plot` |

- Each `(intent, dimension)` pair is one registered aggregator in `app/aggregators/registry.py`.
  The route handler never branches on question type; new coverage means registering an aggregator.
- The LLM's plan schema is **generated from the registry**: `analysis` is one enum of registered
  keys (`"distribution.phase"`, `"network.drug_drug"`, ...), and OpenAI strict structured outputs
  enforce it. An unsupported analysis is unrepresentable, not something to catch later.
- The **viz type is not chosen by the LLM**. Each aggregator declares its row shape, and a fixed
  table maps each shape to exactly one chart. An LLM pick would add a failure mode and no choice.
- All three network types are one generic co-occurrence aggregator registered per entity pair.

### 2. Tools, database and tech stack

| Choice | Why | Rejected |
|---|---|---|
| **Python + FastAPI + Pydantic** | Every boundary (request, plan, LLM output, response) is a typed, validated model; FastAPI's OpenAPI output feeds the frontend types | — |
| **ClinicalTrials.gov API v2, structured params** | Typed fields (phase, status, dates, country) answer exactly | Vector/semantic search: it blurs NCT IDs and categorical labels and adds latency |
| **Postgres response cache (Docker Compose)**, two tables, verbatim JSON | Identical requests reuse identical records, so evals and examples are reproducible; excerpts are verified against the stored record | A local pre-cached corpus: fast, but stale. No ORM: two tables do not justify one |
| **OpenAI `gpt-5.4-mini`** | The company supplied the key. Planning is enum classification, so a mini model is enough | Model benchmarking (out of time box) |
| **Hand-rolled orchestration** | The design decisions are what is graded; a framework hides them | LangChain, LlamaIndex, CrewAI, multi-agent loops |
| **httpx (sync)** | Requests are sequential and FastAPI threads sync routes; `MockTransport` serves test fixtures | async: complexity without need |
| **uv, ruff, mypy strict, pytest, GitHub Actions** | One-command reproducible setup from a lockfile; CI runs the same definition of done as local | — |
| **Vite + React + TS, Vega-Lite, Cytoscape.js** | Vega-Lite covers five chart types declaratively; Cytoscape handles graphs. Types are generated from `/openapi.json`, so `schemas.py` stays the single source and CI fails on drift | A component library: weight and a borrowed look |

### 3. Deep citations, and verification at every step

**What every datum carries.** Every bar, time bucket, scatter point, histogram bin, network node and
network edge has `trial_count`, all its `nct_ids` (so `trial_count == len(nct_ids)` by
construction) and up to 25 citations `{nct_id, excerpt, field}`. The excerpt is the verbatim record
value that put the trial in that datum (`"PHASE3"`, an intervention name as registered, a start
date), and `field` is its record path. An edge cites both of its ends for every cited trial. A trial
in an "absent" bucket (no phase) is cited with `excerpt: null`, and a check confirms the field really
is absent. Every trial card shows the record's own title, official title, status, phase, sponsor and
conditions, verbatim.

**Fifteen deterministic checks**, grouped by the pipeline step they verify. None of them reads LLM
output. A failure rebuilds the spec once from the same rows without LLM prose, then returns
`degraded`; the API is never re-queried to fix a spec.

| Step | Checks | What they prove |
|---|---|---|
| retrieval | `conformance` | every charted trial meets each exact filter (re-read from its raw record), and the filters shown are exactly the API params sent |
| aggregation | `membership`, `recount`, `reconciliation`, `accounting` | each trial's own record puts it in its datum; every row, node, edge, point, bin and exclusion is rebuilt from the raw records and matches; counts reconcile; every retrieved trial is charted or listed under the reason it is not |
| citations | `citation ids`, `excerpts`, `coverage`, `summaries` | every cited ID is in its datum and was retrieved; every excerpt is the value at its field; every datum cites `min(trial_count, 25)` trials; every card field equals its record |
| prose | `title` | the one LLM text on the chart contains no number outside the filters |
| response | `schema`, `encoding`, `shape`, `assumptions`, `disclosures` | the contract holds and every cap, cutoff, pruning and inferred filter is disclosed |

**Accounting by trial ID.** `meta.excluded` lists every trial it leaves out by NCT ID, under its
reason: a counting rule (`missing start date`, `placebo`, ...), `outside the country filter`,
`not in the top 20`, `pruned from the network`. `accounting` then proves every retrieved trial is
either on the chart or listed, so nothing disappears silently.

**The verification ledger.** `meta.verification`, on every status, lists the eight pipeline steps
(request, plan, retrieval, records, aggregation, citations, prose, response) with the checks each
ran, items verified of total, and a one-line result written by Python from counts. A refusal shows
where it stopped: "Beijing, Japan" stops at `plan` ("Beijing" cannot be applied), and every later
step is `not_reached`. Under the chart, a badge ("3,770 trials accounted for · 3,387 citations
verified") opens the ledger.

**Seeded faults** (`tests/test_fault_injection.py`): each corrupts one thing in a valid answer, and
the named check must catch it. The clean answers pass every check, so each catch is real.

| Fault | Caught by |
|---|---|
| an invented NCT ID | `citation ids` |
| a Phase 2 trial on the Phase 3 bar, cited with its real value `PHASE2` | `membership` (and `summaries`); the excerpt check alone passes it |
| an excerpt not in its record | `excerpts` |
| a miscounted row | `reconciliation` |
| a retrieved trial on no datum and under no reason | `membership`, `accounting` |
| an exclusion whose count is not its IDs | `accounting` |
| a trial with no site in the filtered country | `conformance` |
| a datum citing fewer trials than it holds | `coverage` |
| a card whose official title is another trial's | `summaries` |
| a network node cited with another drug's name | `membership` |
| an edge cited for one end only | `membership` |
| a node given a trial that never names its drug | `recount` |
| a stray number in the title | `title` |
| an undisclosed inferred filter | `assumptions` |
| a false "capped" disclosure | `disclosures` |
| an encoding field no row has | `encoding` |

Two of these were found by the new checks themselves. `recount` caught the SCHEMAS.md network
example listing its nodes out of the contract's own documented order, and a test fixture marking the
searched drug as not the anchor.

**Eval citation metrics** (`eval/results/phase7_final.json`): 34/34 answers; 4,208 of 4,208 data
fully cited; 30,896 of 30,896 excerpts hold against their records; 0 of 95,265 charted trials
outside a filter; every check passed on every answer, with no repairs. The checks cost about 1.6 s
on the largest answer (a 20,000-trial comparison); warm median latency is 3.9 s.

![The sources panel filtered to one network edge: Ipilimumab – Nivolumab, 115 trials, each card
citing both drug names verbatim](assets/sources-panel-edge.png)

Clicking the Ipilimumab – Nivolumab edge filters the sources to its 115 trials. The numbered
markers jump to their cards, and each card quotes both drug names exactly as registered, at their
field.

### 4. A frontend that feels like the company's product

No frontend was required. I built one because the user's perspective is graded, and because
rendering only from `SCHEMAS.md` proves the contract needs no guessing.

- **I used the company's cited-answer product hands-on** to learn how a user moves from an answer
  to its evidence, and took screenshots as a reference.
- **I scraped the company website's CSS** for its type scale, palette and card styling. Those
  values are the `:root` design tokens in `frontend/src/index.css`; components use only tokens,
  and `src/charts/theme.ts` mirrors them for the charts.
- **Interaction patterns taken from the product:** a right panel with Sources | Viewer tabs,
  numbered source cards with metadata chips, an answer element that filters its sources when
  clicked, a viewer with the cited passage highlighted and an "open original" link, and export.
- **Adapted, because our answer is a chart, not text:** a datum replaces the inline citation
  marker, and hovering a source card highlights the bars it supports (reverse highlight, which a
  text answer cannot offer). No company name or logo is used, and nothing claims to be their product.

### 5. Other judgment calls

- **Ask, don't guess.** A question with no drug, condition or sponsor gets `clarification_needed`:
  a time period alone would chart a capped slice of the whole registry. This includes the
  appendix's unanchored "Which drugs frequently co-occur in combination studies?".
- **Never chart a different question.** If part of the question cannot be expressed as a filter
  ("pediatric", a city) or one filter gets two values ("Japan and Korea"), the answer is a
  clarification with a one-click rephrase, not a chart that silently ignores it.
- **Not found is not "similar".** On zero results, each entity is probed alone: zero means
  "not found" (no similar drug is substituted); more than zero means the filters together match
  nothing. The search is never silently widened.
- **Messy data gets written counting rules**, each disclosed in `meta`, based on measured
  evidence from 6,000 live records: multi-phase trials are their own category ("Phase 1/Phase 2")
  so sums reconcile; countries are deduped per trial; missing values are excluded *and counted*.
- **What counts as a drug** is DRUG, BIOLOGICAL or COMBINATION_PRODUCT, minus placebo, sham,
  vehicle and saline: type alone splits pembrolizumab (617 DRUG, 243 BIOLOGICAL). Name rules
  (case, dose, bracketed alias, salt) keep one drug on one network node.
- **Networks are pruned and the anchor is marked.** Edges with weight < 2 are dropped and the
  top 50 nodes by weighted degree kept, with a fallback to weight 1 if that empties the graph. The
  queried drug sits in every trial, so it is flagged `is_anchor` for a renderer to de-emphasize.
- **Estimated and actual enrollment are never mixed unseen**: numeric charts split them as series.
- **Hallucination probes in the eval**: 13 questions built to fail on purpose (drop one of two
  places, ignore "pediatric", substitute a similar drug, widen a zero-result search). Each refusal
  must be guaranteed by a Python guard, not by prompt luck, and is never rerun until it passes.

## What was intended vs what was adapted

The plan changed a lot once it met real data. Each change below was forced by a measured failure.

| Intended | What happened | Adapted to |
|---|---|---|
| Fetch cap of 2,000 records | Baseline eval: 19 of 23 charted answers were capped samples. Shapes held (per-year shares within 0.9 pp), but absolute counts were badly low (pembrolizumab 2022: 197 charted vs 299 real) | Cap 10,000, so capped answers fell to 4 of 23; those that still hit it say "(capped sample)" on the axis and in a caption |
| Country filter via `query.locn` | It is a text search. "Japan" matched *China-Japan Friendship Hospital* in Beijing (9 of 336 breast cancer trials had no site in Japan). Every check passed | `filter.advanced=AREA[LocationCountry]`, the registry's 226 canonical country names as an enum, and a new `conformance` check plus an off-filter eval metric (1,262 off-filter trials before -> 0 after) |
| Trust the LLM to list every constraint | "Beijing, Japan" charted Japan, because the LLM dropped "Beijing" (~4% of runs) | Python guards: every capitalized name, country name and age or sex word must appear in a constraint quote, else retry once, then ask. "Beijing, Japan" asked 70/70 times after |
| Age words caught by the name guard | "pediatric asthma" was quoted as the condition while the search used "asthma", and passed | An age or sex word counts only if quoted as *not* applied; 20/20 after |
| LLM at `low` reasoning effort | Misrouted 3 of 15 enrollment questions | `medium` for the plan (0 of 15); the title call at `none` (1.06 s vs 2.0 s, equivalent titles) |
| Excerpt check = enough citation verification | A wrong-bar trial cited with its real value passed every check | `membership` check re-derives every charted trial's category |
| Exclusions reported as counts | Nothing proved every retrieved trial was either charted or deliberately left out | Exclusions list their NCT IDs (plus "not in the top N" and "pruned from the network"); the `accounting` check proves every trial is accounted for |
| Trust the aggregation once its unit tests pass | Nothing compared the shipped answer with what the records actually give, for networks and numeric charts | `recount` rebuilds every datum from the raw records and must match; it caught the contract's own network example breaking its documented sort |
| "15 checks passed" as the only signal | A reader could not see what was verified, or where a refusal stopped | A per-step verification ledger on every status, with a badge under the chart |
| Sequential pipeline | The two LLM calls were 80-99% of warm latency | The title call runs while trials are fetched; cohorts download concurrently. Warm median 4.9 s -> 3.1 s |
| Concurrent downloads | Three 429s in a row failed a comparison: the API allows a ~10-request burst then ~1 request/s, and a 429 takes ~8 s to clear | A token-bucket rate limiter (burst 8, then 1/s) and an 8 s retry after a 429 |
| Large responses | The `trials` map made a capped comparison 6.9 MB of JSON | gzip middleware (1.4 MB on the wire), sources panel paged 25 at a time |
| A filter panel in the UI | The reference product filters from the question alone | The question box is the only input; read-only chips show the filters applied (inferred ones marked). The request fields stay in the API |
| Original styling, with dark mode | Decided to match the company's product instead | Company palette and type scale; light theme only, since the reference has none |
| Compare several LLMs | Not worth the time box | One model, baseline and after runs only |
| Planner checked by eye | A comparison was occasionally planned with its own cohort kind as the dimension | The planner rejects that shape and retries (20/20 live after) |

## How correctness was validated

**1. Tests written red-first.** Every fix and feature started with a failing test (seen failing for
the expected reason), then the code. 974 offline backend tests (unit, contract, checks, fault
injection; no network or LLM needed), 139 live tests against the real APIs, and 143 frontend tests.
Expected outputs are computed by hand from the source of truth (the API docs, the counting rules,
the assignment), never copied from current output.

**2. Contract tests.** Every JSON example in `SCHEMAS.md` validates against `schemas.py`; the
frontend's TypeScript types are regenerated from the OpenAPI schema and CI fails on drift;
`.env.example` and `config.py` are checked for parity.

**3. Live tests.** The real planner against every eval question; the real pipeline end to end; every
aggregator plus citations on real records; OpenAI accepting the strict plan schema.

**4. An eval with a baseline and after runs, all kept** in `eval/results/`. 34 questions cover every
question class, plus ambiguous input, a zero-result combination, a nonexistent drug, contradictory
dates, multi-phase records, a very broad condition, country variants and unexpressible constraints.
Per question it records status, analysis, viz type, records, check results, latency, failure mode,
citation coverage and off-filter trials (re-read from raw records outside `checks.py`).

| Run | Passed | Probes | Off-filter trials | Excerpts verified | Median latency |
|---|---|---|---|---|---|
| `baseline.json` (cap 2,000) | 30/30 | — | not measured | 22,326 / 22,326 | 5.6 s |
| `pre_phase6.json` (4 new retrieval questions) | 29/34 | — | 1,262 of 88,382 | — | — |
| `after_phase6_guards.json` | 34/34 | 13/13 | 0 of 95,265 | 30,896 / 30,896 | 3.5 s |
| `phase7_membership.json` | 34/34 | 13/13 | 0 of 95,265 | 30,896 / 30,896 | 3.8 s |
| `phase7_final.json` (15 checks, ledger) | 34/34 | 13/13 | 0 of 95,265 | 30,896 / 30,896 | 3.9 s |

Honest caveat: the original pass/fail set is in-sample. The planner prompt was tuned against these
questions, so 34/34 shows the system meets the spec it was built to, not how it generalizes. The
retrieval questions added later had expectations written before the fix and a pre-fix run saved.

**5. Looking at it.** Every charted eval answer was rendered in the frontend and screenshotted
(headless Chrome); fixes from those screenshots (tick density, axis titles, legend size, series
colours) were each made red-first.

**6. Measuring before optimizing.** Latency was timed per stage before any change, and the API's
rate limit was probed before the limiter was written.

## AI tools used, and what was designed vs generated

**Tools.** Claude Code (Claude Opus) wrote most of the code, tests and docs. OpenAI `gpt-5.4-mini`
runs inside the product for planning and titles only.

**How I worked with it.** I wrote and maintained `CLAUDE.md` as the spec Claude Code works from:
the objectives, the grading weights, the pipeline, the LLM boundary, the counting rules, a "don't
do" list and a phased build plan with a "Done when" per phase. Each phase began with the open
decisions settled by me (recorded in `BUILD_HISTORY.md` → Decisions, with the date and who
decided), then the code was written test-first, then the eval was rerun. Each phase was a branch,
merged on green CI and tagged (`phase-0` … `phase-6`).

**Designed by me (deliberate):**
- The core split: LLM plans and writes prose only; all data is deterministic Python.
- The question categorization and the `(intent, dimension)` registry, so coverage needs no hacks.
- The tech stack, database, cache design and the rejected alternatives (no vector search, no agent
  framework, no knowledge graph).
- Citation-based verification as the bonus to invest in, and what each check must prove.
- The status model, and the rule to ask rather than guess or substitute.
- The frontend direction: match the company's product, from using it, its screenshots and its
  site's CSS.
- The eval: which questions to ask, the hallucination probes, and that a probe's refusal must be
  guaranteed in Python rather than by rerunning until clean.
- The calls at each fork: raise the cap to 10,000, keep it uniform, clarification-only constraint
  accounting, remove the filter panel, drop the model comparison.

**Generated by Claude Code and adapted under review:**
- Most implementation: the API client, cache, normalizer, aggregators, checks, pipeline, frontend
  components and the test suites.
- The investigations behind the adaptations above (latency profiling, rate-limit probing, the
  messy-value counts). Their findings were brought to me, and I chose the fix.
- Prompt wording for the planner, tuned against the eval.
- Documentation drafts, including this README, edited by me.

Where generated work was wrong, it was caught by the checks, tests and eval rather than trusted:
for example, seven older test fixtures that broke the very filter they claimed were found and
fixed when the `conformance` check was added, and a contract test that mutated shared example data
in place was found while building the eval runner.

## Example runs

Captured from the running system (`examples/`, request and response per file pair; responses are
large because the `trials` map holds every charted trial):

| Example | Status | Viz | What it shows |
|---|---|---|---|
| `1_time_series_pembrolizumab` | ok | `time_series` | 2,904 trials since 2015, zero-filled years, start-date basis disclosed |
| `2_grouped_bar_pembrolizumab_vs_nivolumab` | ok | `grouped_bar_chart` | Two cohorts, one fetch each, per-cohort sample disclosure |
| `3_network_melanoma_drug_drug` | ok | `network_graph` | Condition-anchored drug-drug network, 50 nodes and 238 edges after pruning; all 3,770 trials accounted for (1,163 charted, the rest listed by ID under 5 reasons, e.g. 105 placebo, 1,611 pruned); 3,387 citations verified |
| `4_bar_breast_cancer_japan` | ok | `bar_chart` | Exact country filter: 327 trials, every one with a site in Japan |
| `5_clarification_beijing_japan` | clarification_needed | — | "Beijing" cannot be applied; offers "How are lung cancer trials in Japan distributed across phases?"; the ledger stops at `plan` |
| `6_not_found_zorblaxumab` | no_results | — | "No trial on ClinicalTrials.gov lists Zorblaxumab. No similar name was substituted."; the ledger stops at `retrieval` |

### Excerpts from those outputs

**A network edge with its deep citations** (`3_network_melanoma_drug_drug.response.json`, trimmed:
one of 238 edges, 3 of its 115 `nct_ids`, 4 of its citations). Weight is the number of trials in
which both drugs appear, and each citation quotes the registered intervention name for one endpoint:

```json
{
  "source": "drug:ipilimumab",
  "target": "drug:nivolumab",
  "trial_count": 115,
  "nct_ids": ["NCT07838974", "NCT07504796", "NCT07422779", "…"],
  "citations": [
    {"nct_id": "NCT07838974", "excerpt": "Ipilimumab", "field": "armsInterventionsModule.interventions.name"},
    {"nct_id": "NCT07838974", "excerpt": "Nivolumab", "field": "armsInterventionsModule.interventions.name"},
    {"nct_id": "NCT07504796", "excerpt": "Ipilimumab", "field": "armsInterventionsModule.interventions.name"},
    {"nct_id": "NCT07504796", "excerpt": "Nivolumab", "field": "armsInterventionsModule.interventions.name"}
  ]
}
```

The same response discloses its pruning in `meta.pruning`
(`{"min_edge_weight": 2, "top_n_nodes": 50, "fallback_used": false, "nodes_removed": 2471, "edges_removed": 4445}`),
lists the 1,611 trials whose drugs were all pruned by ID under `pruned from the network`, and its
ledger reads: "All 3770 trials accounted for: 1163 charted in 288 data, the rest listed under 5
reasons; each datum recounted from its records." and "3387 citations verified".

**A clarification** (`5_clarification_beijing_japan.response.json`, trimmed: the ledger's last six
steps are all `not_reached`). The question names a city, which no filter can express, so the system
asks instead of charting Japan alone, and the ledger shows where it stopped:

```json
{
  "status": "clarification_needed",
  "visualization": null,
  "trials": {},
  "meta": {
    "source": "clinicaltrials.gov",
    "filters": {"stated": {"condition": "lung cancer", "country": "Japan"}, "inferred": {}},
    "assumptions": [],
    "notes": ["\"Beijing\" cannot be applied: no filter for city."],
    "verification": [
      {"step": "request", "status": "passed", "checks": ["request schema", "year range"],
       "verified": 1, "total": 1, "result": "The request fields are valid."},
      {"step": "plan", "status": "stopped",
       "checks": ["plan schema", "registered analysis", "constraint quotes", "name coverage", "anchor"],
       "verified": 0, "total": 1, "result": "Stopped: \"Beijing\" cannot be applied: no filter for city."},
      {"step": "retrieval", "status": "not_reached", "checks": ["conformance"],
       "verified": 0, "total": 0, "result": "Not reached."},
      "…"
    ],
    "missing": [],
    "unapplied": [{"quote": "Beijing", "reason": "no filter for city"}],
    "conflicts": [],
    "suggested_query": "How are lung cancer trials in Japan distributed across phases?"
  }
}
```

**Not found** (`6_not_found_zorblaxumab.response.json`). A made-up drug is reported as not found; no
similar name is substituted, and the ledger stops at `retrieval` with "Stopped: No trial on
ClinicalTrials.gov lists Zorblaxumab. No similar name was substituted." The `not_found` list names
it: `["Zorblaxumab"]`.

## Limitations and what more time would improve

- **Brand, generic and code names are not merged** in networks: the Novartis network shows RAD001
  and everolimus as two nodes. A synonym table is the next step; the API already expands drug
  synonyms at search time.
- **Capped broad queries understate absolute counts** (e.g. "cancer": 10,000 of 123,793). Shapes
  hold, and the cap is disclosed. Exact per-bucket totals via `countTotal` queries would fix it,
  at the cost of one request per bucket against a ~1 request/s rate limit.
- **The constraint guard misses lowercase city names** ("trials in beijing"); the prompt still
  asks the LLM to quote them.
- **No regions** ("Europe"), multi-value phase or status filters ("Phase 2 or 3"), or non-English
  questions. Each is deferred with a trigger in `CLAUDE.md` §13.4.
- **Investigator and site networks** are not built; site names are messy free text.
- **The eval is small and partly in-sample.** A held-out question set would measure generalization.
- **Runs locally only.** No deploy, auth or monitoring.
- **Latency is bounded by the API's ~1 request/s limit** for questions that fetch many pages
  (a 20-page comparison takes ~11 s cold); warm answers are ~3-4 s.
