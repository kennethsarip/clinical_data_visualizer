from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from app.cache import TrialCache
from app.ctgov import UpstreamError, params_key
from app.migrate import apply_migrations
from app.schemas import RetrievalFilters
from tests.ctgov_fakes import fake_client, page, paged, record

PEMBRO = RetrievalFilters(drug_name="pembrolizumab")


@pytest.fixture
def conn(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    apply_migrations(db)
    yield db


def _count(conn: psycopg.Connection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def _three_pages_of_600() -> dict[str | None, dict[str, Any]]:
    return {
        None: page(list(range(1, 601)), "t1", total=1800),
        "t1": page(list(range(601, 1201)), "t2"),
        "t2": page(list(range(1201, 1801)), None),
    }


# --- hits and misses ---


def test_identical_second_fetch_makes_no_http_request(conn: psycopg.Connection) -> None:
    pages = {None: page([1, 2], "t1", total=3), "t1": page([3], None)}
    api, requests, _ = fake_client(paged(pages))
    cache = TrialCache(conn, api, ttl_hours=168)
    first = cache.fetch(PEMBRO)
    assert len(requests) == 2
    second = cache.fetch(PEMBRO)
    assert len(requests) == 2
    assert second.records == first.records
    assert (second.fetched, second.total, second.params_key) == (3, 3, first.params_key)
    assert [p.body for p in second.pages] == [pages[None], pages["t1"]]  # stored verbatim


def test_different_filters_miss(conn: psycopg.Connection) -> None:
    api, requests, _ = fake_client(paged({None: page([1], None, total=1)}))
    cache = TrialCache(conn, api, ttl_hours=168)
    cache.fetch(PEMBRO)
    cache.fetch(RetrievalFilters(drug_name="nivolumab"))
    assert len(requests) == 2


def test_pages_older_than_the_ttl_are_refetched(conn: psycopg.Connection) -> None:
    api, requests, _ = fake_client(paged({None: page([1], None, total=1)}))
    cache = TrialCache(conn, api, ttl_hours=1)
    cache.fetch(PEMBRO)
    conn.execute("UPDATE api_pages SET fetched_at = now() - interval '61 minutes'")
    cache.fetch(PEMBRO)
    assert len(requests) == 2


def test_pages_cached_under_a_smaller_cap_are_not_served_to_a_larger_one(
    conn: psycopg.Connection,
) -> None:
    small_api, small_requests, _ = fake_client(paged(_three_pages_of_600()), cap=1000)
    large_api, large_requests, _ = fake_client(paged(_three_pages_of_600()), cap=2000)
    # Both caps request pageSize 1000, so they share a cache key.
    assert params_key(small_api.params_for(PEMBRO)) == params_key(large_api.params_for(PEMBRO))

    assert TrialCache(conn, small_api, 168).fetch(PEMBRO).fetched == 1000
    assert len(small_requests) == 2

    assert TrialCache(conn, large_api, 168).fetch(PEMBRO).fetched == 1800
    assert len(large_requests) == 3

    # The complete copy now covers the smaller cap without a request.
    result = TrialCache(conn, small_api, 168).fetch(PEMBRO)
    assert (result.fetched, result.total, result.capped) == (1000, 1800, True)
    assert len(small_requests) == 2


# --- writes ---


def test_refetch_drops_pages_past_the_new_last_page(conn: psycopg.Connection) -> None:
    old, _, _ = fake_client(paged({None: page([1], "t1", total=2), "t1": page([2], None)}))
    TrialCache(conn, old, ttl_hours=1).fetch(PEMBRO)
    conn.execute("UPDATE api_pages SET fetched_at = now() - interval '2 hours'")
    new, _, _ = fake_client(paged({None: page([1], None, total=1)}))
    result = TrialCache(conn, new, ttl_hours=1).fetch(PEMBRO)
    assert result.total == 1
    assert _count(conn, "api_pages") == 1


def test_a_failed_write_leaves_both_tables_empty(conn: psycopg.Connection) -> None:
    bad = page([1], None, total=2)
    bad["studies"].append({"protocolSection": {"identificationModule": {"nctId": "BAD"}}})
    api, _, _ = fake_client(paged({None: bad}))
    with pytest.raises(psycopg.errors.CheckViolation):
        TrialCache(conn, api, 168).fetch(PEMBRO)
    assert _count(conn, "api_pages") == _count(conn, "trials") == 0


def test_a_record_without_an_nct_id_is_an_upstream_error(conn: psycopg.Connection) -> None:
    bad = page([1], None, total=2)
    bad["studies"].append({"protocolSection": {}})
    api, _, _ = fake_client(paged({None: bad}))
    with pytest.raises(UpstreamError, match="nctId"):
        TrialCache(conn, api, 168).fetch(PEMBRO)
    assert _count(conn, "api_pages") == 0


def test_a_trial_seen_by_two_queries_is_one_row_with_the_newer_record(
    conn: psycopg.Connection,
) -> None:
    older, newer = record(1), record(1)
    older["protocolSection"]["identificationModule"]["briefTitle"] = "Old title"
    newer["protocolSection"]["identificationModule"]["briefTitle"] = "New title"
    first, _, _ = fake_client(paged({None: {"studies": [older], "totalCount": 1}}))
    second, _, _ = fake_client(paged({None: {"studies": [newer], "totalCount": 1}}))
    TrialCache(conn, first, 168).fetch(PEMBRO)
    cache = TrialCache(conn, second, 168)
    cache.fetch(RetrievalFilters(condition="melanoma"))
    assert _count(conn, "trials") == 1
    assert cache.records_by_id(["NCT00000001"]) == {"NCT00000001": newer}


# --- lookup by NCT ID (CLAUDE.md §8.2: exact match only) ---


def test_records_by_id_matches_exactly(conn: psycopg.Connection) -> None:
    api, _, _ = fake_client(paged({None: page([1, 2], None, total=2)}))
    cache = TrialCache(conn, api, 168)
    cache.fetch(PEMBRO)
    found = cache.records_by_id(["NCT00000002", "nct00000001", "NCT00000003"])
    assert found == {"NCT00000002": record(2)}


def test_count_goes_to_the_api_and_writes_nothing(conn: psycopg.Connection) -> None:
    api, requests, _ = fake_client(paged({None: page([1], "next", total=57)}))
    cache = TrialCache(conn, api, ttl_hours=168)
    assert cache.count(PEMBRO) == 57
    assert len(requests) == 1
    assert _count(conn, "api_pages") == 0 and _count(conn, "trials") == 0
