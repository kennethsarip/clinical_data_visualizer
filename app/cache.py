"""Postgres read/write of API responses (CLAUDE.md §6).

Identical filters within the TTL are served from `api_pages` with no HTTP request, so example and
eval runs see identical records. Pages and the `trials` rows they contain are written in one
transaction, so the two tables never disagree.
"""

import logging
from collections.abc import Iterable, Sequence
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.ctgov import (
    CtgovClient,
    FetchResult,
    Page,
    assemble_result,
    covers_cap,
    params_key,
    record_nct_id,
)
from app.schemas import RetrievalFilters, StoredTrial

logger = logging.getLogger(__name__)


class TrialCache:
    def __init__(self, conn: psycopg.Connection, client: CtgovClient, ttl_hours: int) -> None:
        self._conn = conn
        self._client = client
        self._ttl_hours = ttl_hours

    def fetch(self, filters: RetrievalFilters) -> FetchResult:
        """Cached pages for these filters if fresh and complete for the cap, else a live fetch."""
        return self.fetch_many([filters])[0]

    def fetch_many(self, filters: Sequence[RetrievalFilters]) -> list[FetchResult]:
        """One result per filter set, in order. Misses download concurrently: pages within one
        search must follow each other's tokens, but separate cohorts need not wait in line.
        Postgres is read and written on this thread only, as a psycopg connection requires."""
        results = [self._cached(f) for f in filters]
        misses = [i for i, result in enumerate(results) if result is None]
        downloaded = self._download([filters[i] for i in misses])
        for i, result in zip(misses, downloaded, strict=True):
            self._write(result)
            results[i] = result
        return [r for r in results if r is not None]

    def _cached(self, filters: RetrievalFilters) -> FetchResult | None:
        key = params_key(self._client.params_for(filters))
        pages = self._read_pages(key)
        if pages and covers_cap(pages, self._client.fetch_cap):
            logger.info("cache hit: %s", key)
            return assemble_result(key, pages, self._client.fetch_cap)
        logger.info("cache miss: %s", key)
        return None

    def _download(self, filters: list[RetrievalFilters]) -> list[FetchResult]:
        if len(filters) <= 1:
            return [self._client.fetch(f) for f in filters]
        pool = ThreadPoolExecutor(len(filters), thread_name_prefix="ctgov")
        try:
            futures = [pool.submit(self._client.fetch, f) for f in filters]
            # Whichever cohort fails first ends the wait and is raised; collecting results in
            # cohort order instead would first wait out a slow cohort ahead of the failed one.
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            for future in done:
                if (error := future.exception()) is not None:
                    raise error
            return [future.result() for future in futures]
        finally:
            # On a failure, return at once: the other downloads finish in the background and
            # are discarded, never written, so a failed request leaves no partial cache entry.
            pool.shutdown(wait=False, cancel_futures=True)

    def count(self, filters: RetrievalFilters) -> int:
        """Uncached: a count is one tiny request, and caching it would need a second key space."""
        return self._client.count(filters)

    def records_by_id(self, nct_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Cached records for the given NCT IDs, matched exactly; unknown IDs are absent."""
        rows = self._conn.execute(
            "SELECT nct_id, record FROM trials WHERE nct_id = ANY(%s)", (list(nct_ids),)
        )
        return {nct_id: record for nct_id, record in rows}

    def stored_trial(self, nct_id: str) -> StoredTrial | None:
        """The cached record whatever its age: a viewer must show the record an answer was checked
        against, not a refetch. Rows are upserted, so a later query may have replaced it."""
        row = self._conn.execute(
            "SELECT record, fetched_at FROM trials WHERE nct_id = %s", (nct_id,)
        ).fetchone()
        if row is None:
            return None
        record, fetched_at = row
        return StoredTrial(nct_id=nct_id, record=record, fetched_at=fetched_at)

    def _read_pages(self, key: str) -> list[Page]:
        rows = self._conn.execute(
            "SELECT page_index, body FROM api_pages"
            " WHERE params_key = %s AND fetched_at > now() - make_interval(hours => %s)"
            " ORDER BY page_index",
            (key, self._ttl_hours),
        ).fetchall()
        return [Page(index=index, body=body) for index, body in rows]

    def _write(self, result: FetchResult) -> None:
        trials = {record_nct_id(record): record for record in result.records}
        with self._conn.transaction(), self._conn.cursor() as cur:
            # Upserts rather than delete-then-insert, so two concurrent misses on the same
            # key cannot collide on the primary key.
            cur.executemany(
                "INSERT INTO api_pages (params_key, page_index, total_count, body)"
                " VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (params_key, page_index) DO UPDATE SET"
                " total_count = EXCLUDED.total_count, body = EXCLUDED.body, fetched_at = now()",
                [(result.params_key, p.index, result.total, Jsonb(p.body)) for p in result.pages],
            )
            # A refetch can return fewer pages than the stale copy had.
            cur.execute(
                "DELETE FROM api_pages WHERE params_key = %s AND page_index >= %s",
                (result.params_key, len(result.pages)),
            )
            cur.executemany(
                "INSERT INTO trials (nct_id, record) VALUES (%s, %s)"
                " ON CONFLICT (nct_id) DO UPDATE SET record = EXCLUDED.record, fetched_at = now()",
                [(nct_id, Jsonb(record)) for nct_id, record in trials.items()],
            )
