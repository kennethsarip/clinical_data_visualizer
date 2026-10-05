"""FastAPI app and routes only; no per-intent branching (CLAUDE.md §4).

One route calls the pipeline. Every status is a 200 (each is an answer the frontend renders), a
request that fails `VisualizeRequest` validation is a 422 before any LLM or API call, and a
`DependencyError` is a 502 (§8.1). Mapping errors to outcomes happens in `pipeline.py`; this
module only translates the one exception the pipeline raises into its HTTP code.
"""

import logging
from collections.abc import Iterator
from functools import cache
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException

from app import aggregators  # noqa: F401  (registers every aggregator)
from app.cache import TrialCache
from app.config import Settings, load_settings
from app.ctgov import CtgovClient
from app.llm import LLMClient
from app.pipeline import DependencyError, Pipeline
from app.schemas import AnyResponse, VisualizeRequest, VisualizeResponse

# uvicorn configures only its own loggers; without this, the app's INFO logs (cache hits and
# misses, retries, repairs) are dropped.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="ClinicalTrials.gov Query-to-Visualization Agent")


# Settings and the HTTP-backed clients are built once and shared: both clients are thread-safe.
@cache
def _settings() -> Settings:
    return load_settings()


@cache
def _llm() -> LLMClient:
    return LLMClient.from_settings(_settings())


@cache
def _ctgov() -> CtgovClient:
    return CtgovClient.from_settings(_settings())


def get_pipeline() -> Iterator[Pipeline]:
    """A pipeline with its own DB connection per request: a psycopg connection is not
    thread-safe, and FastAPI runs sync routes in a threadpool."""
    settings = _settings()
    url = settings.database_url.get_secret_value()
    with psycopg.connect(url, autocommit=True) as conn:
        yield Pipeline(_llm(), TrialCache(conn, _ctgov(), settings.cache_ttl_hours))


@app.post("/api/visualize", response_model=VisualizeResponse)
def visualize(
    request: VisualizeRequest, pipeline: Annotated[Pipeline, Depends(get_pipeline)]
) -> AnyResponse:
    try:
        return pipeline.run(request)
    except DependencyError as exc:
        logger.error("dependency failure for %r: %s", request.query, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
