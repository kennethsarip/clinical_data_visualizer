"""A scripted ClinicalTrials.gov API on httpx.MockTransport, for the client and cache tests."""

from collections.abc import Callable
from typing import Any

import httpx

from app.ctgov import CtgovClient, RateLimiter

BASE_URL = "https://ctgov.test/api/v2"
Handler = Callable[[httpx.Request], httpx.Response]


def record(n: int) -> dict[str, Any]:
    return {"protocolSection": {"identificationModule": {"nctId": f"NCT{n:08d}"}}}


def page(ids: list[int], token: str | None, total: int | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"studies": [record(n) for n in ids]}
    if total is not None:
        body["totalCount"] = total
    if token is not None:
        body["nextPageToken"] = token
    return body


def fake_client(
    handler: Handler, cap: int = 2000, limiter: RateLimiter | None = None
) -> tuple[CtgovClient, list[httpx.Request], list[float]]:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    http = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(recording))
    # By default no rate limit: these tests are about pages and retries, not pacing.
    unlimited = RateLimiter(rate=1e9, burst=10**9)
    client = CtgovClient(http, cap, limiter or unlimited, sleep=sleeps.append)
    return client, requests, sleeps


def paged(pages: dict[str | None, dict[str, Any]]) -> Handler:
    """Serve pages keyed by the request's pageToken (None for the first page)."""
    return lambda request: httpx.Response(200, json=pages[request.url.params.get("pageToken")])


def scripted(responses: list[httpx.Response]) -> Handler:
    queue = iter(responses)
    return lambda request: next(queue)
