"""ClinicalTrials.gov Data API v2 client: params from filters, pagination, cap (CLAUDE.md §7.3).

The only module that speaks the API's vocabulary ("study", `studies`); everything else says
"trial" and "record". Params are built only from validated `RetrievalFilters`, never from raw LLM
text. Behaviour verified against the live API on 2026-10-04: dotted `fields=` paths trim records;
`filter.advanced` terms join with AND; `RANGE[MIN,...]` works; `totalCount` is only on the first
page; invalid params return HTTP 400 with a plain-text reason.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
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

# The §6 source paths. Trimming keeps cached records small; excerpts are still verbatim values.
RECORD_FIELDS = (
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.designModule.phases",
    "protocolSection.designModule.studyType",
    "protocolSection.designModule.enrollmentInfo.count",
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.startDateStruct.date",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "protocolSection.armsInterventionsModule.interventions.type",
    "protocolSection.armsInterventionsModule.interventions.name",
    "protocolSection.conditionsModule.conditions",
    "protocolSection.contactsLocationsModule.locations.country",
)


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
        "query.locn": filters.country,
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
    return " AND ".join(terms)


def params_key(params: dict[str, str]) -> str:
    """Canonical cache key: the params sorted by name and URL-encoded."""
    return urlencode(sorted(params.items()))


class CtgovClient:
    """Fetches records page by page up to `fetch_cap`, retrying transient upstream errors."""

    def __init__(
        self,
        http: httpx.Client,
        fetch_cap: int,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = http
        self._fetch_cap = fetch_cap
        self._sleep = sleep

    @classmethod
    def from_settings(cls, settings: Settings) -> "CtgovClient":
        http = httpx.Client(base_url=settings.ctgov_base_url, timeout=TIMEOUT_SECONDS)
        return cls(http, settings.fetch_cap)

    def params_for(self, filters: RetrievalFilters) -> dict[str, str]:
        return build_params(filters, page_size=min(MAX_PAGE_SIZE, self._fetch_cap))

    def fetch(self, filters: RetrievalFilters) -> FetchResult:
        params = self.params_for(filters)
        pages: list[Page] = []
        records: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            page_params = params if token is None else {**params, "pageToken": token}
            body = self._get_studies(page_params)
            pages.append(Page(index=len(pages), body=body))
            records.extend(_studies(body))
            token = body.get("nextPageToken")
            if token is None or len(records) >= self._fetch_cap:
                break
        total = _total_count(pages[0].body)
        # Only reachable when the cap is not a multiple of the page size; disclosed via `capped`.
        records = records[: self._fetch_cap]
        return FetchResult(params_key(params), pages, records, total)

    def _get_studies(self, params: dict[str, str]) -> dict[str, Any]:
        for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
            try:
                response = self._http.get("/studies", params=params)
            except httpx.HTTPError as exc:
                raise UpstreamError(f"ClinicalTrials.gov request failed: {exc!r}") from exc
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < len(RETRY_DELAYS_SECONDS):
                delay = RETRY_DELAYS_SECONDS[attempt]
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
