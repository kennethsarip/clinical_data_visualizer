# Build history

The shipped log, newest first, with 1-2 lines per entry. The Decisions section holds the reasoning behind CLAUDE.md §13.2.

## Shipped

- 2026-10-04, Phase 0: repo skeleton per CLAUDE.md §4; uv + ruff + mypy (strict) + pytest on Python 3.12; GitHub Actions CI running the Definition of done; `app/config.py` with a two-way `.env.example` parity test.

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
