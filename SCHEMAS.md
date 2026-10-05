# SCHEMAS.md: Request and response contract

The renderer contract: a frontend engineer should be able to implement a renderer from this file without guessing (CLAUDE.md Objectives). `app/schemas.py` implements it, and a contract test validates every JSON example here against those models (CLAUDE.md §9), so the two cannot drift silently.

**Status: locked 2026-10-04.** A change here is a contract change: update `app/schemas.py` and this file in the same commit. All NCT IDs, titles and counts below are illustrative, not system output; real runs live in `examples/`.

## 1. Request

`POST /api/visualize`. JSON body:

| Field | Type | Required | Validation | Maps to API param |
|---|---|---|---|---|
| query | string | yes | 1-1000 chars after trimming whitespace | - (the planner reads it) |
| drug_name | string | no | 1-200 chars after trimming whitespace | `query.intr` |
| condition | string | no | 1-200 chars after trimming whitespace | `query.cond` |
| trial_phase | Phase enum | no | One of NA, EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4 | `filter.advanced=AREA[Phase]...` |
| sponsor | string | no | 1-200 chars after trimming whitespace | `query.spons` |
| country | string | no | One of the registry's 226 country names (`app/vocab.py` `COUNTRIES`, the OpenAPI enum), matched ignoring case and stored in the registry spelling; a variant such as `Korea` or `USA` is rejected | `filter.advanced=AREA[LocationCountry]"<name>"` |
| start_year | int | no | `start_year <= end_year` | `filter.advanced=AREA[StartDate]RANGE[...]` |
| end_year | int | no | `start_year <= end_year` | same |

Unknown fields are rejected. The query, or a field, must name a drug, condition or sponsor; otherwise the response is `clarification_needed` (§5). If a field and the query name different values for the same filter, the field wins and `meta.notes` says the query's value was overridden.

```json
{"query": "How has the number of trials for this drug changed over time?",
 "drug_name": "Pembrolizumab"}
```

**HTTP codes:** 200 for every `status` in §2 (each is a valid answer to render); 422 for request validation, before any LLM or API call (contradictory inputs are rejected, never turned into an empty chart); 502 when ClinicalTrials.gov or the LLM is unreachable or errors (body `{"detail": "<message>"}`). The split: a 200 means the system ran but may not have produced a chart; a 502 means a dependency is down and a retry may succeed.

## 2. Response envelope

```text
{status, visualization, trials, meta}
```

| Field | Type | Notes |
|---|---|---|
| status | `ok` \| `clarification_needed` \| `no_results` \| `degraded` | Always present |
| visualization | object \| null | `null` whenever `status != ok` |
| trials | object | `nct_id` -> trial summary for every NCT ID in any row's `nct_ids`; `{}` when `status != ok` |
| meta | object | Always present (§4) |

`visualization`:

| Field | Type | Notes |
|---|---|---|
| type | string | `bar_chart`, `grouped_bar_chart`, `time_series`, `scatter_plot`, `histogram` or `network_graph` (§3) |
| title | string | Written by the LLM from the plan; never contains a number that is not in the filters |
| encoding | object | Channel -> channel object (below); network: `{nodes, edges}` of channels (§3.6) |
| data | array of rows; network: `{nodes, edges}` (§3.6) | Rows are in render order (§4 `sort`); renderers keep that order |

**Channel object:**

| Field | Type | Notes |
|---|---|---|
| field | string | A row field present in every row |
| type | `quantitative` \| `nominal` \| `ordinal` \| `temporal` | How to scale the channel |
| scale | `linear` \| `log` | Optional; default `linear` |

A `temporal` field holds either an integer year (when `meta.time_granularity` is `year`) or the API's date string, `YYYY-MM` or `YYYY-MM-DD`.

**Fields on every row, node and edge:**

| Field | Type | Notes |
|---|---|---|
| trial_count | int | Distinct trials behind the row; always equals `len(nct_ids)` |
| nct_ids | string[] | Every contributing NCT ID (`^NCT\d{8}$`), sorted descending; `[]` for a zero-filled row |
| citations | Citation[] | Evidence for at most `meta.citation_cap` of those trials (the first ones in `nct_ids`); a trial may contribute more than one citation (a multi-phase trial; both ends of an edge) |

**Citation:**

| Field | Type | Notes |
|---|---|---|
| nct_id | string | Always in the row's `nct_ids` |
| excerpt | string \| null | Verbatim substring of the value at `field` in that trial's API record. `null` means the field is absent, which is why the trial is in this row (e.g. "Not specified" phase) |
| field | string | Record path under `protocolSection`; for a list, the path names the element's field |

Excerpt source per dimension:

| Dimension | `field` | Example excerpt |
|---|---|---|
| phase | `designModule.phases` | `PHASE3` |
| overall_status | `statusModule.overallStatus` | `RECRUITING` |
| start_year, start_date | `statusModule.startDateStruct.date` | `2015-03` |
| country | `contactsLocationsModule.locations.country` | `Germany` |
| intervention_type | `armsInterventionsModule.interventions.type` | `DRUG` |
| drug | `armsInterventionsModule.interventions.name` | the registered name, e.g. `Pembrolizumab (MK-3475)` |
| sponsor | `sponsorCollaboratorsModule.leadSponsor.name` | `Merck Sharp & Dohme LLC` |
| sponsor_class | `sponsorCollaboratorsModule.leadSponsor.class` | `INDUSTRY` |
| condition | `conditionsModule.conditions` | `Melanoma` |
| enrollment | `designModule.enrollmentInfo.count` | `120` |
| enrollment_type | `designModule.enrollmentInfo.type` | `ACTUAL` |

**Trial summary** (`trials[nct_id]`): `brief_title` (string), `overall_status` (display label), `phase` (display label, e.g. "Phase 1/Phase 2"), `start_date` (string or null, as registered), `sponsor_name` (lead sponsor, as registered), `conditions` (string[], as registered, possibly empty). Sponsor and condition names are not normalized here: they label a source card, while network nodes and top-N bars use the normalized names. The link to a trial is `https://clinicaltrials.gov/study/<nct_id>`; the cached record is `GET /api/trials/<nct_id>` (§6).

## 3. Visualization types

Python picks the type from the aggregator's row shape (CLAUDE.md §7.4). Units are in `meta.units`.

### 3.1 `bar_chart` (distribution, geographic, top-N)

One row per category. Sort: count descending, ties alphabetical; phase uses its canonical order instead (Early Phase 1 ... Phase 4, Not Applicable, Not specified; `meta.sort.order` = `canonical`). Top-N charts (drug, sponsor, condition, country) keep the 20 largest categories and disclose it in `meta.top_n`.

```json
{"status": "ok",
 "visualization": {
   "type": "bar_chart",
   "title": "Trials by Phase for Pembrolizumab",
   "encoding": {"x": {"field": "phase", "type": "nominal"},
                "y": {"field": "trial_count", "type": "quantitative"}},
   "data": [
     {"phase": "Phase 1/Phase 2", "trial_count": 1, "nct_ids": ["NCT00000003"],
      "citations": [{"nct_id": "NCT00000003", "excerpt": "PHASE1", "field": "designModule.phases"},
                    {"nct_id": "NCT00000003", "excerpt": "PHASE2", "field": "designModule.phases"}]},
     {"phase": "Phase 3", "trial_count": 2, "nct_ids": ["NCT00000002", "NCT00000001"],
      "citations": [{"nct_id": "NCT00000002", "excerpt": "PHASE3", "field": "designModule.phases"},
                    {"nct_id": "NCT00000001", "excerpt": "PHASE3", "field": "designModule.phases"}]},
     {"phase": "Not specified", "trial_count": 1, "nct_ids": ["NCT00000004"],
      "citations": [{"nct_id": "NCT00000004", "excerpt": null, "field": "designModule.phases"}]}]},
 "trials": {
   "NCT00000001": {"brief_title": "Pembrolizumab in Advanced Melanoma", "overall_status": "Completed", "phase": "Phase 3", "start_date": "2015-03",
                   "sponsor_name": "Merck Sharp & Dohme LLC", "conditions": ["Melanoma"]},
   "NCT00000002": {"brief_title": "Pembrolizumab Versus Chemotherapy in NSCLC", "overall_status": "Active, not recruiting", "phase": "Phase 3", "start_date": "2016-07-12",
                   "sponsor_name": "Merck Sharp & Dohme LLC", "conditions": ["Non-small Cell Lung Cancer"]},
   "NCT00000003": {"brief_title": "Pembrolizumab Plus Lenvatinib in Solid Tumors", "overall_status": "Recruiting", "phase": "Phase 1/Phase 2", "start_date": "2019-01",
                   "sponsor_name": "Eisai Inc.", "conditions": ["Solid Tumor", "Endometrial Cancer"]},
   "NCT00000004": {"brief_title": "Real-World Outcomes of Pembrolizumab", "overall_status": "Completed", "phase": "Not specified", "start_date": "2018-05",
                   "sponsor_name": "University of Texas MD Anderson Cancer Center", "conditions": ["Melanoma", "Lung Cancer"]}},
 "meta": {
   "source": "clinicaltrials.gov",
   "interpretation": {"intent": "distribution", "dimension": "phase", "cohorts": null},
   "filters": {"stated": {"drug_name": "Pembrolizumab"}, "inferred": {}},
   "assumptions": ["A trial registered under two phases is its own category, so the bars sum to the trials charted.",
                   "\"Not specified\" phase is mostly observational studies, which have no phase."],
   "units": {"trial_count": "trials"},
   "sort": {"field": "phase", "order": "canonical"},
   "time_granularity": null,
   "grouping": {"dimension": "phase", "series": null},
   "sample": [{"cohort": null, "fetched": 4, "total": 4, "capped": false}],
   "citation_cap": 25,
   "excluded": [],
   "top_n": null,
   "pruning": null,
   "name_merges": [],
   "notes": ["Counts every trial that mentions pembrolizumab as an intervention."]}}
```

### 3.2 `grouped_bar_chart` (comparison)

`series` names the cohort. Every (x, series) pair is present: a category one cohort lacks gets a zero row (`nct_ids: []`, `citations: []`), so bars align. Each cohort's filters are in `meta.interpretation.cohorts`.

```json
{"type": "grouped_bar_chart",
 "title": "Phases: Pembrolizumab vs Nivolumab",
 "encoding": {"x": {"field": "phase", "type": "nominal"},
              "y": {"field": "trial_count", "type": "quantitative"},
              "series": {"field": "cohort", "type": "nominal"}},
 "data": [
   {"phase": "Phase 2", "cohort": "Pembrolizumab", "trial_count": 0, "nct_ids": [], "citations": []},
   {"phase": "Phase 2", "cohort": "Nivolumab", "trial_count": 1, "nct_ids": ["NCT00000005"],
    "citations": [{"nct_id": "NCT00000005", "excerpt": "PHASE2", "field": "designModule.phases"}]},
   {"phase": "Phase 3", "cohort": "Pembrolizumab", "trial_count": 1, "nct_ids": ["NCT00000001"],
    "citations": [{"nct_id": "NCT00000001", "excerpt": "PHASE3", "field": "designModule.phases"}]},
   {"phase": "Phase 3", "cohort": "Nivolumab", "trial_count": 1, "nct_ids": ["NCT00000006"],
    "citations": [{"nct_id": "NCT00000006", "excerpt": "PHASE3", "field": "designModule.phases"}]}]}
```

### 3.3 `time_series` (time trend)

`x` is ascending, and gap years are zero-filled (a zero row has `nct_ids: []` and `citations: []`).

```json
{"type": "time_series",
 "title": "Pembrolizumab Trials Started per Year since 2015",
 "encoding": {"x": {"field": "start_year", "type": "temporal"},
              "y": {"field": "trial_count", "type": "quantitative"}},
 "data": [
   {"start_year": 2015, "trial_count": 1, "nct_ids": ["NCT00000001"],
    "citations": [{"nct_id": "NCT00000001", "excerpt": "2015-03", "field": "statusModule.startDateStruct.date"}]},
   {"start_year": 2016, "trial_count": 0, "nct_ids": [], "citations": []}]}
```

### 3.4 `scatter_plot` (numeric: one point per trial)

`x` is the start date, `y` is enrollment on a log scale, and `series` splits Actual from Estimated enrollment ("Type not reported" when the record omits it). Enrollment 0 is real data (e.g. a withdrawn trial); a log axis cannot show it, so renderers pin it to the axis floor, and `meta.notes` says so. Sort: `start_date` ascending, ties by `nct_id`.

```json
{"type": "scatter_plot",
 "title": "Enrollment by Start Date for Pembrolizumab Trials",
 "encoding": {"x": {"field": "start_date", "type": "temporal"},
              "y": {"field": "enrollment", "type": "quantitative", "scale": "log"},
              "series": {"field": "enrollment_type", "type": "nominal"}},
 "data": [
   {"nct_id": "NCT00000001", "start_date": "2015-03", "enrollment": 120, "enrollment_type": "Actual",
    "trial_count": 1, "nct_ids": ["NCT00000001"],
    "citations": [{"nct_id": "NCT00000001", "excerpt": "120", "field": "designModule.enrollmentInfo.count"},
                  {"nct_id": "NCT00000001", "excerpt": "2015-03", "field": "statusModule.startDateStruct.date"}]}]}
```

### 3.5 `histogram` (numeric: enrollment bins)

Fixed bins, because enrollment is heavily skewed: 0, 1-9, 10-49, 50-99, 100-249, 250-499, 500-999, 1000-4999, 5000+. Bins are half-open `[bin_start, bin_end)`; the last has `bin_end: null`. Bins are unequal, so `x` is the ordinal `bin_label`, not a numeric axis. Every bin appears for every `enrollment_type` (zero rows included). Sort: `bin_start` ascending, then series.

```json
{"type": "histogram",
 "title": "Enrollment Distribution for Pembrolizumab Trials",
 "encoding": {"x": {"field": "bin_label", "type": "ordinal"},
              "y": {"field": "trial_count", "type": "quantitative"},
              "series": {"field": "enrollment_type", "type": "nominal"}},
 "data": [
   {"bin_label": "10-49", "bin_start": 10, "bin_end": 50, "enrollment_type": "Actual",
    "trial_count": 1, "nct_ids": ["NCT00000002"],
    "citations": [{"nct_id": "NCT00000002", "excerpt": "48", "field": "designModule.enrollmentInfo.count"}]},
   {"bin_label": "5000+", "bin_start": 5000, "bin_end": null, "enrollment_type": "Actual",
    "trial_count": 0, "nct_ids": [], "citations": []}]}
```

### 3.6 `network_graph` (network)

`data` is `{nodes, edges}`. Edges are undirected. A node `id` is `<entity_type>:<normalized name>`, an opaque key (the name's words, lowercased, without punctuation, sorted for drugs and conditions; CLAUDE.md §6) that renderers should not display; `label` is the most common registered spelling. In a two-type network (sponsor-drug, condition-drug), `source` is the first-named type; in a one-type network (drug-drug), `source < target` alphabetically. An edge's `trial_count` is the number of trials containing both ends, and its citations give one entry per end per trial. `is_anchor` marks the entity the query named: it is in every trial, so renderers should de-emphasize it. Nodes sort by `trial_count` descending, edges by `trial_count` descending, ties by id.

```json
{"type": "network_graph",
 "title": "Drug Co-occurrence in Melanoma Combination Trials",
 "encoding": {
   "nodes": {"id": {"field": "id", "type": "nominal"}, "label": {"field": "label", "type": "nominal"},
             "group": {"field": "entity_type", "type": "nominal"}, "size": {"field": "trial_count", "type": "quantitative"}},
   "edges": {"source": {"field": "source", "type": "nominal"}, "target": {"field": "target", "type": "nominal"},
             "weight": {"field": "trial_count", "type": "quantitative"}}},
 "data": {
   "nodes": [
     {"id": "drug:pembrolizumab", "label": "Pembrolizumab", "entity_type": "drug", "is_anchor": false,
      "trial_count": 1, "nct_ids": ["NCT00000007"],
      "citations": [{"nct_id": "NCT00000007", "excerpt": "Pembrolizumab (MK-3475)", "field": "armsInterventionsModule.interventions.name"}]},
     {"id": "drug:ipilimumab", "label": "Ipilimumab", "entity_type": "drug", "is_anchor": false,
      "trial_count": 1, "nct_ids": ["NCT00000007"],
      "citations": [{"nct_id": "NCT00000007", "excerpt": "Ipilimumab", "field": "armsInterventionsModule.interventions.name"}]}],
   "edges": [
     {"source": "drug:ipilimumab", "target": "drug:pembrolizumab", "trial_count": 1, "nct_ids": ["NCT00000007"],
      "citations": [{"nct_id": "NCT00000007", "excerpt": "Ipilimumab", "field": "armsInterventionsModule.interventions.name"},
                    {"nct_id": "NCT00000007", "excerpt": "Pembrolizumab (MK-3475)", "field": "armsInterventionsModule.interventions.name"}]}]}}
```

`entity_type` values: `drug`, `sponsor`, `condition`.

## 4. `meta`

The full `meta` of an `ok` response is in §3.1.

| Key | Present | Meaning |
|---|---|---|
| source | always | Always `clinicaltrials.gov` |
| interpretation | when `ok` | How the query was read: `intent` and `dimension` (strings naming a registered aggregator) and `cohorts` (`null`, or `[{label, filters}]` for a comparison) |
| filters | always | `stated`: from a request field or verbatim in `query`. `inferred`: from ambiguous wording. Keys are the §1 field names, plus `overall_status` |
| assumptions | always | Non-empty whenever `filters.inferred` is non-empty |
| units | when `ok` | Row field -> unit (`trials`, `participants`) |
| sort | when `ok` | `{field, order}`, `order` one of `asc`, `desc`, `canonical`. Describes the row order; renderers do not re-sort |
| time_granularity | when `ok` | `year` for time series, otherwise `null` |
| grouping | when `ok` | `{dimension, series}`; `series` is `null` when there is none |
| sample | when `ok` | One entry per cohort (`cohort: null` when there is one): `capped: true` means the chart covers `fetched` of `total` trials |
| citation_cap | when `ok` | Maximum trials cited per row (25); `nct_ids` is never capped |
| excluded | when `ok` | `[{rule, count}]`: trials a counting rule acted on. In a comparison each rule ends with its cohort, `"<rule> (<cohort>)"`. Most rules leave the trial out (`missing start date`, `no drug intervention`, `unreadable record`, and `outside the <filter> filter` for a fetched trial that fails an exact filter sent: phase, status, start year, end year or country); `placebo` and `non-drug intervention` count trials that had such an intervention dropped but may still appear through their other drugs |
| top_n | when `ok` | `null`, or `{limit, categories_total}` for a top-N bar chart |
| pruning | when `ok` | `null` unless network: `{min_edge_weight, top_n_nodes, fallback_used, nodes_removed, edges_removed}` |
| name_merges | when `ok` | `[{entity_type, name, merged_names, evidence}]`: drug names charted as one drug because trials register them as its other names (`interventions[].otherNames`, CLAUDE.md §14 Phase 8 step 5). `name` is the label charted, `merged_names` the registered own names now charted under it, `evidence` up to `citation_cap` citations of the other-name listings (`field` `armsInterventionsModule.interventions.otherNames`). Empty for charts without drugs and when nothing merged |
| notes | always | LLM-written prose about the interpretation |
| missing | `clarification_needed` only | The anchors the request lacks |
| not_found | `no_results` only | Entities that match no trial on their own; empty when the filters together match nothing |
| errors | `degraded` only | `[{check, message}]` |

Network `pruning` example: `{"min_edge_weight": 2, "top_n_nodes": 50, "fallback_used": false, "nodes_removed": 12, "edges_removed": 40}`.

`name_merges` example: `[{"entity_type": "drug", "name": "Everolimus", "merged_names": ["RAD001"], "evidence": [{"nct_id": "NCT00000012", "excerpt": "RAD001", "field": "armsInterventionsModule.interventions.otherNames"}]}]`.

## 5. Non-`ok` statuses

```json
{"status": "clarification_needed", "visualization": null, "trials": {},
 "meta": {"source": "clinicaltrials.gov", "filters": {"stated": {}, "inferred": {}}, "assumptions": [],
          "missing": ["drug_name", "condition", "sponsor"],
          "notes": ["Name a drug, condition or sponsor to chart."]}}
```

`missing` lists absent anchors only. A request that is anchored but cannot be planned, such as a comparison of more than 4 cohorts, returns `clarification_needed` with `missing: []` and the reason in `notes`.

Zero results with every entity found (the filters together match nothing):

```json
{"status": "no_results", "visualization": null, "trials": {},
 "meta": {"source": "clinicaltrials.gov", "filters": {"stated": {"condition": "Melanoma", "trial_phase": "PHASE4", "country": "Iceland"}, "inferred": {}},
          "assumptions": [], "not_found": [],
          "notes": ["No trials match all applied filters. The search was not widened."]}}
```

An entity that matches no trial on its own:

```json
{"status": "no_results", "visualization": null, "trials": {},
 "meta": {"source": "clinicaltrials.gov", "filters": {"stated": {"drug_name": "Zorblaxumab"}, "inferred": {}},
          "assumptions": [], "not_found": ["Zorblaxumab"],
          "notes": ["No trial on ClinicalTrials.gov lists Zorblaxumab. No similar drug was substituted."]}}
```

```json
{"status": "degraded", "visualization": null, "trials": {},
 "meta": {"source": "clinicaltrials.gov", "filters": {"stated": {"drug_name": "Pembrolizumab"}, "inferred": {}}, "assumptions": [],
          "errors": [{"check": "encoding", "message": "Field 'phase' is missing from row 3."}],
          "notes": []}}
```

`degraded` has three causes, named by `errors[].check`: `plan` when the LLM's plan still fails validation after one retry (`visualization` is null and `filters` holds only the request fields); `retrieval` when over 5% of a fetched batch fails an exact filter that was sent, so the chart would show the wrong trials; or a §7.6 check name when the spec still fails after one repair. A failed title is not a cause: the response stays `ok` with a plain generated title and a note.

## 6. Cached trial record

`GET /api/trials/{nct_id}` returns the record behind a citation, for a record viewer that highlights each excerpt in place. It reads the response cache only and never calls ClinicalTrials.gov, so it serves the record as cached, whatever its age: the one the excerpt check ran against, unless a later request replaced it (below).

| Field | Type | Notes |
|---|---|---|
| nct_id | string | `^NCT\d{8}$`, as requested |
| record | object | The verbatim API record; a citation's `field` is a path under `record.protocolSection` |
| fetched_at | string | ISO 8601 timestamp with time zone, when the cache stored this record |

**HTTP codes:** 200 with the body above; 404 `{"detail": "<nct_id> is not in the cache."}` when no request has fetched the trial; 422 when the ID does not match `^NCT\d{8}$` (matched exactly, so `nct00000001` is a 422, never a lookup of the nearest ID).

**Staleness:** the cache keeps one record per trial and a later request that fetches the same trial replaces it. A viewer should check each excerpt against the value at its `field` before highlighting it and, on a mismatch, say the record has changed since the answer rather than highlight other text. Matching excerpts show the cited values still hold, not that the record is the same version: responses carry no record version.
