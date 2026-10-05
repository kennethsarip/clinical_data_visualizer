"""FastAPI app and routes only; no per-intent branching (CLAUDE.md §4).

`POST /api/visualize` calls the pipeline. Every status is a 200 (each is an answer the frontend
renders), a request that fails `VisualizeRequest` validation is a 422 before any LLM or API call,
and a `DependencyError` is a 502 (§8.1). Mapping errors to outcomes happens in `pipeline.py`; this
module only translates the one exception the pipeline raises into its HTTP code.

`GET /api/trials/{nct_id}` reads one cached record for the frontend's record viewer.
"""

import logging
from collections.abc import Iterator
from functools import cache
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path
from fastapi.openapi.utils import get_openapi

from app import aggregators  # noqa: F401  (registers every aggregator)
from app.cache import TrialCache
from app.checks import CHECK_RULES, CHECKS
from app.config import Settings, load_settings
from app.ctgov import CtgovClient
from app.llm import LLMClient
from app.pipeline import DependencyError, Pipeline
from app.schemas import (
    NCT_ID_PATTERN,
    AnyResponse,
    ErrorDetail,
    StoredTrial,
    VisualizeRequest,
    VisualizeResponse,
)
from app.vocab import PHASE_LABELS, STATUS_LABELS, Phase, Status

# uvicorn configures only its own loggers; without this, the app's INFO logs (cache hits and
# misses, retries, repairs) are dropped.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="ClinicalTrials.gov Query-to-Visualization Agent")


def _openapi() -> dict[str, Any]:
    """FastAPI's schema plus display labels from `vocab.py` as `x-labels`, so the frontend reads
    labels from the drift-checked schema instead of keeping a second copy. `Status` appears only
    as a value in `meta.filters`, so it is added as a component of its own."""
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        components = schema["components"]["schemas"]
        components.setdefault("Status", {"type": "string", "title": "Status"})
        for enum, labels in ((Phase, PHASE_LABELS), (Status, STATUS_LABELS)):
            components[enum.__name__]["enum"] = [member.value for member in enum]
            components[enum.__name__]["x-labels"] = {m.value: labels[m] for m in enum}
        # The checks every `ok` response passed, for the frontend's "How this was answered" drawer.
        schema["x-checks"] = [{"name": name, "rule": CHECK_RULES[name]} for name, _ in CHECKS]
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _openapi  # type: ignore[method-assign]


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


def get_cache() -> Iterator[TrialCache]:
    """A cache with its own DB connection per request: a psycopg connection is not thread-safe,
    and FastAPI runs sync routes in a threadpool."""
    settings = _settings()
    url = settings.database_url.get_secret_value()
    with psycopg.connect(url, autocommit=True) as conn:
        yield TrialCache(conn, _ctgov(), settings.cache_ttl_hours)


def get_pipeline(cache: Annotated[TrialCache, Depends(get_cache)]) -> Pipeline:
    return Pipeline(_llm(), cache)


@app.post(
    "/api/visualize",
    response_model=VisualizeResponse,
    responses={502: {"model": ErrorDetail, "description": "ClinicalTrials.gov or the LLM failed"}},
)
def visualize(
    request: VisualizeRequest, pipeline: Annotated[Pipeline, Depends(get_pipeline)]
) -> AnyResponse:
    try:
        return pipeline.run(request)
    except DependencyError as exc:
        logger.error("dependency failure for %r: %s", request.query, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/trials/{nct_id}",
    response_model=StoredTrial,
    responses={404: {"model": ErrorDetail, "description": "The trial is not in the cache"}},
)
def stored_trial(
    nct_id: Annotated[str, Path(pattern=NCT_ID_PATTERN)],
    cache: Annotated[TrialCache, Depends(get_cache)],
) -> StoredTrial:
    """The cached record behind a citation, for the frontend's record viewer. Read-only: it never
    calls ClinicalTrials.gov, so it shows the record the excerpt check ran against."""
    trial = cache.stored_trial(nct_id)
    if trial is None:
        raise HTTPException(status_code=404, detail=f"{nct_id} is not in the cache.")
    return trial
