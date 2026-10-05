"""Live checks against the real API (`uv run pytest -m live`); excluded from the default run."""

import os

import httpx
import psycopg
import pytest

from app.cache import TrialCache
from app.ctgov import BURST, RATE_PER_SECOND, TIMEOUT_SECONDS, CtgovClient, RateLimiter
from app.migrate import apply_migrations
from app.normalize import normalize_records
from app.schemas import RetrievalFilters
from app.vocab import COUNTRIES

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
    cache = TrialCache(
        db, CtgovClient(http, 2000, RateLimiter(RATE_PER_SECOND, BURST)), ttl_hours=168
    )
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

    # Every live record must parse: a shape error here means the API changed (§6).
    batch = normalize_records(second.records)
    assert len(batch.trials) == second.fetched


def test_countries_match_the_registry_country_list() -> None:
    """vocab.COUNTRIES mirrors the API's LocationCountry values (§8.4); a new name fails here."""
    response = httpx.get(
        "https://clinicaltrials.gov/api/v2/stats/field/values",
        params={"fields": "LocationCountry"},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    [field] = response.json()
    names = {value["value"] for value in field["topValues"]}
    assert field["uniqueValuesCount"] == len(names)  # the listing is complete, not a top slice
    assert names == set(COUNTRIES)
