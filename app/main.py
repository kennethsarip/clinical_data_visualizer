"""FastAPI app and routes only; no per-intent branching (CLAUDE.md §4)."""

from fastapi import FastAPI

app = FastAPI(title="ClinicalTrials.gov Query-to-Visualization Agent")
