# SCHEMAS.md: Request and response contract

The renderer contract: a frontend engineer should be able to implement a renderer from this file without guessing (CLAUDE.md Objectives). `app/schemas.py` implements it, and a contract test validates every JSON example here against those models (CLAUDE.md §9), so the two cannot drift silently.

**Status: draft.** Values tagged **PROPOSED** are candidates for open decisions in CLAUDE.md §13.1 (response contract, request fields, networks, citations); they are not decided yet. Untagged items come from the assignment. All NCT IDs and counts below are illustrative, not system output; real runs live in `examples/`.

## 1. Request

`POST` to an endpoint path that is still OPEN (CLAUDE.md §8.1). JSON body:

| Field | Type | Required | Validation | Maps to API param |
|---|---|---|---|---|
| query | string | yes | Non-empty; max length OPEN | - (the planner reads it) |
| drug_name | string | no | | `query.intr` |
| condition | string | no | | `query.cond` |
| trial_phase | Phase enum | no | One of NA, EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4 | `filter.advanced=AREA[Phase]...` |
| sponsor | string | no | | `query.spons` |
| country | string | no | | `query.locn` |
| start_year | int | no | `start_year <= end_year` | `filter.advanced=AREA[StartDate]RANGE[...]` |
| end_year | int | no | `start_year <= end_year` | same |

Any validation failure returns HTTP 422 before any LLM or API call; contradictory inputs are rejected and never turned into an empty chart.

```json
{"query": "How has the number of trials for this drug changed over time?",
 "drug_name": "Pembrolizumab"}
```

## 2. Response envelope

```json
{"status": "ok", "visualization": {}, "meta": {}}
```

| Field | Type | Notes |
|---|---|---|
| status | `ok` \| `clarification_needed` \| `no_results` \| `degraded` | Always present |
| visualization | object \| null | **PROPOSED:** `null` whenever `status != ok` (§5) |
| meta | object | Always present (§4) |

`visualization`:

| Field | Type | Notes |
|---|---|---|
| type | string | One of the six types in §3 |
| title | string | Human-readable; written by the LLM, never containing data values it computed |
| encoding | object | Channel -> `{"field": <row field name>}`; every named field exists in every row |
| data | array of rows (network: object, §3.6) | Every row carries `citations` |

**Citation** (on every row, node and edge):

| Field | Type | Notes |
|---|---|---|
| nct_id | string | `^NCT\d{8}$`; always in the retrieved record set |
| excerpt | string | Verbatim substring of that trial's API record |
| field | string | **PROPOSED:** the record path the excerpt came from, e.g. `designModule.phases` |

`trial_count` is always the number of distinct NCT IDs behind the row. The per-row citation cap is OPEN; if it is set below `trial_count`, `meta` must say so.

## 3. Visualization types

Rows sort as `meta.sort` states. Units are in `meta.units`.

### 3.1 `bar_chart` (distribution, geographic)

```json
{"type": "bar_chart",
 "title": "Trials by Phase for Pembrolizumab",
 "encoding": {"x": {"field": "phase"}, "y": {"field": "trial_count"}},
 "data": [
   {"phase": "Phase 3", "trial_count": 2,
    "citations": [{"nct_id": "NCT00000001", "excerpt": "PHASE3", "field": "designModule.phases"},
                  {"nct_id": "NCT00000002", "excerpt": "PHASE3", "field": "designModule.phases"}]}]}
```

### 3.2 `grouped_bar_chart` (comparison; type string **PROPOSED**)

`series` names the cohort; each (x, series) pair is one row.

```json
{"type": "grouped_bar_chart",
 "title": "Phases: Pembrolizumab vs Nivolumab",
 "encoding": {"x": {"field": "phase"}, "y": {"field": "trial_count"}, "series": {"field": "cohort"}},
 "data": [
   {"phase": "Phase 3", "cohort": "Pembrolizumab", "trial_count": 1,
    "citations": [{"nct_id": "NCT00000001", "excerpt": "PHASE3", "field": "designModule.phases"}]},
   {"phase": "Phase 3", "cohort": "Nivolumab", "trial_count": 1,
    "citations": [{"nct_id": "NCT00000003", "excerpt": "PHASE3", "field": "designModule.phases"}]}]}
```

### 3.3 `time_series` (time trend)

`x` is ordered and gap years are zero-filled (a zero row has `citations: []`).

```json
{"type": "time_series",
 "title": "Pembrolizumab Trials Started per Year since 2015",
 "encoding": {"x": {"field": "start_year"}, "y": {"field": "trial_count"}},
 "data": [
   {"start_year": 2015, "trial_count": 1,
    "citations": [{"nct_id": "NCT00000001", "excerpt": "2015-03", "field": "statusModule.startDateStruct.date"}]},
   {"start_year": 2016, "trial_count": 0, "citations": []}]}
```

### 3.4 `scatter_plot` (numeric; type string and fields **PROPOSED**, CLAUDE.md §13.1)

One row per trial, so each row has exactly one citation per plotted value.

```json
{"type": "scatter_plot",
 "title": "Enrollment by Start Year for Pembrolizumab Trials",
 "encoding": {"x": {"field": "start_year"}, "y": {"field": "enrollment"}},
 "data": [
   {"nct_id": "NCT00000001", "start_year": 2015, "enrollment": 120,
    "citations": [{"nct_id": "NCT00000001", "excerpt": "120", "field": "designModule.enrollmentInfo.count"}]}]}
```

### 3.5 `histogram` (numeric; type string and binning **PROPOSED**)

Bins are half-open `[bin_start, bin_end)`.

```json
{"type": "histogram",
 "title": "Enrollment Distribution for Pembrolizumab Trials",
 "encoding": {"x": {"field": "bin_start"}, "x2": {"field": "bin_end"}, "y": {"field": "trial_count"}},
 "data": [
   {"bin_start": 0, "bin_end": 100, "trial_count": 1,
    "citations": [{"nct_id": "NCT00000002", "excerpt": "48", "field": "designModule.enrollmentInfo.count"}]}]}
```

### 3.6 `network_graph` (network; shape **PROPOSED**)

`data` is `{nodes, edges}` instead of an array. An edge's `trial_count` is the number of trials containing both endpoints. Edge citations give one entry per endpoint per trial, so every edge is traceable to both ends.

```json
{"type": "network_graph",
 "title": "Drug Co-occurrence in Melanoma Combination Trials",
 "encoding": {
   "nodes": {"id": {"field": "id"}, "label": {"field": "label"}, "group": {"field": "entity_type"}, "size": {"field": "trial_count"}},
   "edges": {"source": {"field": "source"}, "target": {"field": "target"}, "weight": {"field": "trial_count"}}},
 "data": {
   "nodes": [
     {"id": "drug:pembrolizumab", "label": "Pembrolizumab", "entity_type": "drug", "trial_count": 1,
      "citations": [{"nct_id": "NCT00000004", "excerpt": "Pembrolizumab", "field": "armsInterventionsModule.interventions.name"}]},
     {"id": "drug:ipilimumab", "label": "Ipilimumab", "entity_type": "drug", "trial_count": 1,
      "citations": [{"nct_id": "NCT00000004", "excerpt": "Ipilimumab", "field": "armsInterventionsModule.interventions.name"}]}],
   "edges": [
     {"source": "drug:pembrolizumab", "target": "drug:ipilimumab", "trial_count": 1,
      "citations": [{"nct_id": "NCT00000004", "excerpt": "Pembrolizumab", "field": "armsInterventionsModule.interventions.name"},
                    {"nct_id": "NCT00000004", "excerpt": "Ipilimumab", "field": "armsInterventionsModule.interventions.name"}]}]}}
```

`entity_type` values: `drug`, `sponsor`, `condition` (investigator and site are OPEN).

## 4. `meta` (keys **PROPOSED**)

```json
{"source": "clinicaltrials.gov",
 "filters": {"stated": {"drug_name": "Pembrolizumab", "start_year": 2015}, "inferred": {}},
 "assumptions": ["Trials are counted by start date (statusModule.startDateStruct.date)."],
 "units": {"trial_count": "trials", "enrollment": "participants"},
 "sort": {"field": "start_year", "order": "asc"},
 "time_granularity": "year",
 "grouping": {"dimension": "start_year", "series": null},
 "sample": {"fetched": 1000, "total": 2968, "capped": true},
 "excluded": [{"rule": "missing start date", "count": 2}],
 "pruning": null,
 "notes": []}
```

| Key | Always present | Meaning |
|---|---|---|
| source | yes | Always `clinicaltrials.gov` |
| filters | yes | `stated` came from a request field or verbatim wording; `inferred` came from ambiguous wording |
| assumptions | yes | Non-empty whenever `filters.inferred` is non-empty |
| units, sort, grouping | when `ok` | Render hints |
| time_granularity | time series only | `year` for now |
| sample | when `ok` | `capped: true` means the chart covers `fetched` of `total` trials |
| excluded | when `ok` | Records dropped by a counting rule, with counts |
| pruning | network only | e.g. `{"min_edge_weight": 2, "top_n_nodes": 50, "nodes_removed": 12, "edges_removed": 40}` |
| notes | yes | LLM-written prose about the interpretation |

## 5. Non-`ok` statuses (**PROPOSED**)

```json
{"status": "clarification_needed", "visualization": null,
 "meta": {"source": "clinicaltrials.gov", "filters": {"stated": {}, "inferred": {}}, "assumptions": [],
          "missing": ["drug_name", "condition", "time period"],
          "notes": ["Name a drug, condition or time period to chart."]}}
```

```json
{"status": "no_results", "visualization": null,
 "meta": {"source": "clinicaltrials.gov", "filters": {"stated": {"condition": "Melanoma", "trial_phase": "PHASE4", "country": "Iceland"}, "inferred": {}},
          "assumptions": [], "notes": ["No trials match all applied filters. The search was not widened."]}}
```

```json
{"status": "degraded", "visualization": null,
 "meta": {"source": "clinicaltrials.gov", "filters": {"stated": {"drug_name": "Pembrolizumab"}, "inferred": {}}, "assumptions": [],
          "errors": [{"check": "encoding", "message": "Field 'phase' is missing from row 3."}]}}
```

The HTTP status code for each `status` is OPEN (CLAUDE.md §8.1).
