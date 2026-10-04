"""Live checks against the real API (`uv run pytest -m live`); excluded from the default run."""

import os

import httpx
import psycopg
import pytest

from app.cache import TrialCache
from app.ctgov import TIMEOUT_SECONDS, CtgovClient
from app.migrate import apply_migrations
from app.schemas import RetrievalFilters

pytestmark = pytest.mark.live


class _CountingTransport(httpx.HTTPTransport):
    def __init__(self) -> None:
        super().__init__()
        self.requests = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        return super().handle_request(request)


def test_pembrolizumab_is_fetched_once_then_served_from_the_cache(db: psycopg.Connection) -> None:
    apply_migrations(db)
    transport = _CountingTransport()
    base_url = os.environ.get("CTGOV_BASE_URL") or "https://clinicaltrials.gov/api/v2"
    http = httpx.Client(base_url=base_url, timeout=TIMEOUT_SECONDS, transport=transport)
    cache = TrialCache(db, CtgovClient(http, fetch_cap=2000), ttl_hours=168)
    filters = RetrievalFilters(drug_name="pembrolizumab")

    first = cache.fetch(filters)
    assert transport.requests > 0
    assert first.fetched > 0
    assert first.total >= first.fetched

    requests_after_first = transport.requests
    second = cache.fetch(filters)
    assert transport.requests == requests_after_first
    assert second.records == first.records
    assert second.total == first.total
