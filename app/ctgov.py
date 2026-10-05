"""ClinicalTrials.gov Data API v2 client: params from filters, pagination, cap (CLAUDE.md §7.3).

The only module that speaks the API's vocabulary ("study", `studies`); everything else says
"trial" and "record". Params are built only from validated `RetrievalFilters`, never from raw LLM
text. Behaviour verified against the live API on 2026-10-04: dotted `fields=` paths trim records;
`filter.advanced` terms join with AND; `RANGE[MIN,...]` works; `totalCount` is only on the first
page; invalid params return HTTP 400 with a plain-text reason.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.schemas import RetrievalFilters

logger = logging.getLogger(__name__)

# The API clamps larger page sizes to 1000 (§7.3).
MAX_PAGE_SIZE = 1000
TIMEOUT_SECONDS = 30.0
RETRY_DELAYS_SECONDS = (1.0, 2.0)  # two retries, on 5xx and 429 only
# A longer Retry-After fails the request now: a 502 is a faster answer than a minute's stall.
MAX_RETRY_AFTER_SECONDS = 10.0

# The §6 source paths. Trimming keeps cached records small; excerpts are still verbatim values.
RECORD_FIELDS = (
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.designModule.phases",
    "protocolSection.designModule.studyType",
    "protocolSection.designModule.enrollmentInfo.count",
    "protocolSection.designModule.enrollmentInfo.type",
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.startDateStruct.date",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "protocolSection.armsInterventionsModule.interventions.type",
    "protocolSection.armsInterventionsModule.interventions.name",
    "protocolSection.conditionsModule.conditions",
    "protocolSection.contactsLocationsModule.locations.country",
)


# The API publishes no rate limit and sends no rate-limit headers. Measured 2026-10-05: a burst of
# ~10 requests, then 429s; 1.0 request/s for 50 requests drew none, 1.5/s drew 3 in 40; a 429
# cleared after ~8 s. So requests are paced below that, and a 429 waits out the recovery.
RATE_PER_SECOND = 1.0
BURST = 8
RATE_LIMIT_RECOVERY_SECONDS = 8.0


class RateLimiter:
    """A token bucket shared by every request of one client (the limit is per IP). A caller
    over the burst reserves the next free slot and sleeps outside the lock, so concurrent
    cohort downloads queue for distinct slots instead of tripping the limit together."""

    def __init__(
        self,
        rate: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rate = rate
        self._burst = burst
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = float(burst)
        self._updated = clock()

    def acquire(self) -> None:
        with self._lock:
            self._refill()
            self._tokens -= 1  # may go negative: a reservation of a future slot
            wait = -self._tokens / self._rate
        if wait > 0:
            self._sleep(wait)

    def drain(self) -> None:
        """After a 429: whatever burst we thought was left, the server disagreed."""
        with self._lock:
            self._refill()
            self._tokens = min(self._tokens, 0.0)

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
        self._updated = now


class UpstreamError(RuntimeError):
    """The API failed, timed out, rejected our params or returned an unreadable body."""


@dataclass(frozen=True)
class Page:
    index: int
    body: dict[str, Any]  # verbatim response JSON, as the cache stores it


@dataclass(frozen=True)
class FetchResult:
    params_key: str
    pages: list[Page]
    records: list[dict[str, Any]]
    total: int  # trials matching the filters, from the first page's totalCount

    @property
    def fetched(self) -> int:
        return len(self.records)

    @property
    def capped(self) -> bool:
        return self.fetched < self.total


def build_params(filters: RetrievalFilters, page_size: int) -> dict[str, str]:
    """Map filters to verified API params (§8.4). Excludes `pageToken`, which varies per page."""
    params = {
        "fields": ",".join(RECORD_FIELDS),
        "pageSize": str(page_size),
        "countTotal": "true",
    }
    searches = {
        "query.intr": filters.drug_name,
        "query.cond": filters.condition,
        "query.spons": filters.sponsor,
    }
    params.update({key: value for key, value in searches.items() if value is not None})
    if filters.overall_status is not None:
        params["filter.overallStatus"] = filters.overall_status.value
    advanced = _advanced_filter(filters)
    if advanced:
        params["filter.advanced"] = advanced
    return params


def _advanced_filter(filters: RetrievalFilters) -> str:
    terms = []
    if filters.trial_phase is not None:
        terms.append(f"AREA[Phase]{filters.trial_phase.value}")
    if filters.start_year is not None or filters.end_year is not None:
        start = f"{filters.start_year}-01-01" if filters.start_year is not None else "MIN"
        end = f"{filters.end_year}-12-31" if filters.end_year is not None else "MAX"
        terms.append(f"AREA[StartDate]RANGE[{start},{end}]")
    if filters.country is not None:
        # The country field, not `query.locn`: a text search over locations matched "Japan" in a
        # Beijing hospital's name (§8.4). Quoted so spaces, commas and parentheses stay one term.
        terms.append(f'AREA[LocationCountry]"{filters.country}"')
    return " AND ".join(terms)


def params_key(params: dict[str, str]) -> str:
    """Canonical cache key: the params sorted by name and URL-encoded."""
    return urlencode(sorted(params.items()))


def covers_cap(pages: list[Page], fetch_cap: int) -> bool:
    """True when the pages hold every matching record, or at least `fetch_cap` of them.

    The cache uses this too: its key does not include the cap, so pages cached under a smaller
    cap must not be served to a request with a larger one.
    """
    fetched = sum(len(_studies(page.body)) for page in pages)
    return pages[-1].body.get("nextPageToken") is None or fetched >= fetch_cap


def assemble_result(key: str, pages: list[Page], fetch_cap: int) -> FetchResult:
    """Records from the pages in order, cut to the cap, with the first page's total."""
    records = [record for page in pages for record in _studies(page.body)]
    # Cutting only happens when the cap is not a multiple of the page size; `capped` discloses it.
    return FetchResult(key, pages, records[:fetch_cap], _total_count(pages[0].body))


def record_nct_id(record: dict[str, Any]) -> str:
    """The NCT ID of one study record; a record without one is an upstream fault."""
    try:
        nct_id = record["protocolSection"]["identificationModule"]["nctId"]
    except (KeyError, TypeError) as exc:
        raise UpstreamError("ClinicalTrials.gov record has no nctId") from exc
    if not isinstance(nct_id, str):
        raise UpstreamError(f"ClinicalTrials.gov record has a non-string nctId: {nct_id!r}")
    return nct_id


class CtgovClient:
    """Fetches records page by page up to `fetch_cap`, retrying transient upstream errors."""

    def __init__(
        self,
        http: httpx.Client,
        fetch_cap: int,
        limiter: RateLimiter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.limiter = limiter
        self._http = http
        self._fetch_cap = fetch_cap
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> "CtgovClient":
        http = httpx.Client(base_url=settings.ctgov_base_url, timeout=TIMEOUT_SECONDS)
        return cls(http, settings.fetch_cap, RateLimiter(RATE_PER_SECOND, BURST))

    @property
    def fetch_cap(self) -> int:
        return self._fetch_cap

    def params_for(self, filters: RetrievalFilters) -> dict[str, str]:
        return build_params(filters, page_size=min(MAX_PAGE_SIZE, self._fetch_cap))

    def count(self, filters: RetrievalFilters) -> int:
        """Trials matching `filters`, from one single-ID page: the §7.8 not-found probe needs
        only `totalCount`, so it never downloads records. Not cached (one small request)."""
        params = {**build_params(filters, page_size=1), "fields": "NCTId"}
        return _total_count(self._get_studies(params))

    def fetch(self, filters: RetrievalFilters) -> FetchResult:
        params = self.params_for(filters)
        pages: list[Page] = []
        while not pages or not covers_cap(pages, self._fetch_cap):
            token = pages[-1].body.get("nextPageToken") if pages else None
            page_params = params if token is None else {**params, "pageToken": token}
            pages.append(Page(index=len(pages), body=self._get_studies(page_params)))
        return assemble_result(params_key(params), pages, self._fetch_cap)

    def _get_studies(self, params: dict[str, str]) -> dict[str, Any]:
        for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
            self.limiter.acquire()
            try:
                response = self._http.get("/studies", params=params)
            except httpx.HTTPError as exc:
                raise UpstreamError(f"ClinicalTrials.gov request failed: {exc!r}") from exc
            retryable = response.status_code == 429 or response.status_code >= 500
            if response.status_code == 429:
                self.limiter.drain()
            if retryable and attempt < len(RETRY_DELAYS_SECONDS):
                delay = _retry_delay(response, RETRY_DELAYS_SECONDS[attempt])
                logger.warning(
                    "ClinicalTrials.gov HTTP %d; retry in %.0fs", response.status_code, delay
                )
                self._sleep(delay)
                continue
            if response.status_code != 200:
                raise UpstreamError(
                    f"ClinicalTrials.gov HTTP {response.status_code}: {response.text[:300]}"
                )
            return _json_object(response)
        raise AssertionError("unreachable: the last attempt returns or raises")


def _retry_delay(response: httpx.Response, backoff: float) -> float:
    """The backoff, or longer if the API's Retry-After (seconds or an HTTP-date) asks for it.
    A 429 without a readable Retry-After waits out the measured recovery instead."""
    asked = _retry_after_seconds(response.headers.get("Retry-After"))
    if asked is None:
        return RATE_LIMIT_RECOVERY_SECONDS if response.status_code == 429 else backoff
    if asked > MAX_RETRY_AFTER_SECONDS:
        raise UpstreamError(
            f"ClinicalTrials.gov HTTP {response.status_code}: retry after {asked:.0f} s"
        )
    return max(backoff, asked)


def _retry_after_seconds(header: str | None) -> float | None:
    if header is None:
        return None
    if header.strip().isdigit():
        return float(header)
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None  # unreadable: the backoff applies
    if when.tzinfo is None:  # a "-0000" zone parses naive; HTTP-dates are always UTC
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise UpstreamError("ClinicalTrials.gov returned a non-JSON body") from exc
    if not isinstance(body, dict):
        raise UpstreamError("ClinicalTrials.gov returned JSON that is not an object")
    return body


def _studies(body: dict[str, Any]) -> list[dict[str, Any]]:
    studies = body.get("studies")
    if not isinstance(studies, list):
        raise UpstreamError("ClinicalTrials.gov response has no `studies` list")
    return studies


def _total_count(first_page: dict[str, Any]) -> int:
    total = first_page.get("totalCount")
    if not isinstance(total, int):
        raise UpstreamError("ClinicalTrials.gov first page has no integer `totalCount`")
    return total
