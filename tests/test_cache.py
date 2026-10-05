import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import psycopg
import pytest

from app.cache import TrialCache
from app.ctgov import FetchResult, Page, UpstreamError, params_key
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


def test_stored_trial_is_the_verbatim_record_with_its_fetch_time(conn: psycopg.Connection) -> None:
    api, _, _ = fake_client(paged({None: page([1, 2], None, total=2)}))
    cache = TrialCache(conn, api, 168)
    cache.fetch(PEMBRO)
    stored = cache.stored_trial("NCT00000002")
    assert stored is not None
    assert (stored.nct_id, stored.record) == ("NCT00000002", record(2))
    assert stored.fetched_at.tzinfo is not None


def test_stored_trial_ignores_the_ttl(conn: psycopg.Connection) -> None:
    # The viewer shows the record an answer was checked against, however old (CLAUDE.md §14).
    api, requests, _ = fake_client(paged({None: page([1], None, total=1)}))
    cache = TrialCache(conn, api, ttl_hours=1)
    cache.fetch(PEMBRO)
    conn.execute("UPDATE trials SET fetched_at = now() - interval '30 days'")
    stored = cache.stored_trial("NCT00000001")
    assert stored is not None and stored.record == record(1)
    assert len(requests) == 1  # never refetched


def test_stored_trial_is_none_when_not_cached(conn: psycopg.Connection) -> None:
    api, requests, _ = fake_client(paged({None: page([1], None, total=1)}))
    cache = TrialCache(conn, api, 168)
    cache.fetch(PEMBRO)
    assert cache.stored_trial("NCT00000009") is None
    assert cache.stored_trial("nct00000001") is None  # exact match only (§8.2)
    assert len(requests) == 1


def test_count_goes_to_the_api_and_writes_nothing(conn: psycopg.Connection) -> None:
    api, requests, _ = fake_client(paged({None: page([1], "next", total=57)}))
    cache = TrialCache(conn, api, ttl_hours=168)
    assert cache.count(PEMBRO) == 57
    assert len(requests) == 1
    assert _count(conn, "api_pages") == 0 and _count(conn, "trials") == 0


# --- several cohorts at once (CLAUDE.md §7.3; Phase 5.3 latency) ---

NIVO = RetrievalFilters(drug_name="nivolumab")
WAIT = 5.0  # seconds; a test that would hang fails with an assertion instead


def _by_drug(
    pages: dict[str, dict[str, Any]], gates: dict[str, threading.Event]
) -> Callable[[httpx.Request], httpx.Response]:
    """Serves one page per drug; a drug's request first waits for its gate, if it has one."""

    def handler(request: httpx.Request) -> httpx.Response:
        drug = request.url.params["query.intr"]
        if drug in gates and not gates[drug].wait(WAIT):
            raise AssertionError(f"{drug} was never released")
        return httpx.Response(200, json=pages[drug])

    return handler


class ThreadRecordingCache(TrialCache):
    """Records which thread touches Postgres: a psycopg connection must stay on one thread."""

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.db_threads: set[int] = set()

    def _read_pages(self, key: str) -> list[Page]:
        self.db_threads.add(threading.get_ident())
        return super()._read_pages(key)

    def _write(self, result: FetchResult) -> None:
        self.db_threads.add(threading.get_ident())
        super()._write(result)


def test_cohorts_download_concurrently_and_return_in_cohort_order(
    conn: psycopg.Connection,
) -> None:
    # Pembrolizumab's page is held until nivolumab's is served: one at a time, this deadlocks.
    nivo_served = threading.Event()
    pages = {"pembrolizumab": page([1], None, total=1), "nivolumab": page([2], None, total=1)}
    handler = _by_drug(pages, {"pembrolizumab": nivo_served})

    def signalling(request: httpx.Request) -> httpx.Response:
        response = handler(request)
        if request.url.params["query.intr"] == "nivolumab":
            nivo_served.set()
        return response

    api, _, _ = fake_client(signalling)
    cache = ThreadRecordingCache(conn, api, 168)
    pembro, nivo = cache.fetch_many([PEMBRO, NIVO])
    assert [r.records for r in (pembro, nivo)] == [[record(1)], [record(2)]]
    assert cache.db_threads == {threading.get_ident()}
    assert _count(conn, "trials") == 2


def test_only_the_cohorts_not_cached_are_downloaded(conn: psycopg.Connection) -> None:
    pages = {"pembrolizumab": page([1], None, total=1), "nivolumab": page([2], None, total=1)}
    api, requests, _ = fake_client(_by_drug(pages, {}))
    cache = TrialCache(conn, api, 168)
    cache.fetch(PEMBRO)
    results = cache.fetch_many([PEMBRO, NIVO])
    assert [r.records for r in results] == [[record(1)], [record(2)]]
    assert [r.url.params["query.intr"] for r in requests] == ["pembrolizumab", "nivolumab"]


@pytest.mark.parametrize("failing", ["pembrolizumab", "nivolumab"])
def test_one_cohort_failing_fails_at_once_without_waiting_for_the_others(
    conn: psycopg.Connection, failing: str
) -> None:
    release = threading.Event()
    before = set(threading.enumerate())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query.intr"] != failing:
            release.wait(WAIT)
            return httpx.Response(200, json=page([2], None, total=1))
        return httpx.Response(400, text="bad param")

    api, _, _ = fake_client(handler)
    cache = TrialCache(conn, api, 168)
    start = time.monotonic()
    with pytest.raises(UpstreamError, match="HTTP 400"):
        cache.fetch_many([PEMBRO, NIVO])
    assert time.monotonic() - start < WAIT / 2  # did not wait on the stalled cohort
    release.set()
    _assert_threads_return_to(before)
    assert _count(conn, "api_pages") == 0  # the stalled cohort's late result is not written


def test_one_cohort_uses_no_extra_thread(conn: psycopg.Connection) -> None:
    threads: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        threads.append(threading.get_ident())
        return httpx.Response(200, json=page([1], None, total=1))

    api, _, _ = fake_client(handler)
    TrialCache(conn, api, 168).fetch_many([PEMBRO])
    assert threads == [threading.get_ident()]


def _assert_threads_return_to(before: set[threading.Thread]) -> None:
    """Waits for the threads started since `before`: a global count would also see threads
    another test left finishing in the background, and flake."""
    deadline = time.monotonic() + WAIT
    while (started := set(threading.enumerate()) - before) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not started, "a worker thread outlived its request"
