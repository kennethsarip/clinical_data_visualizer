import threading

import httpx
import pytest

from app.config import load_settings
from app.ctgov import (
    RATE_LIMIT_RECOVERY_SECONDS,
    CtgovClient,
    RateLimiter,
    UpstreamError,
    build_params,
    params_key,
)
from app.schemas import RetrievalFilters
from app.vocab import Phase, Status
from tests.ctgov_fakes import fake_client, page, paged, scripted

FIXED = {"fields", "pageSize", "countTotal"}


# --- params (CLAUDE.md §8.4 verified params) ---


def test_no_filters_sends_only_the_fixed_params() -> None:
    assert set(build_params(RetrievalFilters(), page_size=1000)) == FIXED


def test_each_filter_maps_to_its_verified_param() -> None:
    filters = RetrievalFilters(
        drug_name="Pembrolizumab",
        condition="Melanoma",
        sponsor="Merck",
        country="Germany",
        trial_phase=Phase.PHASE3,
        overall_status=Status.RECRUITING,
        start_year=2015,
        end_year=2020,
    )
    params = build_params(filters, page_size=1000)
    assert {k: v for k, v in params.items() if k not in FIXED} == {
        "query.intr": "Pembrolizumab",
        "query.cond": "Melanoma",
        "query.spons": "Merck",
        "query.locn": "Germany",
        "filter.overallStatus": "RECRUITING",
        "filter.advanced": "AREA[Phase]PHASE3 AND AREA[StartDate]RANGE[2015-01-01,2020-12-31]",
    }
    assert params["pageSize"] == "1000"
    assert params["countTotal"] == "true"


@pytest.mark.parametrize(
    ("years", "expected"),
    [
        ({"start_year": 2015}, "AREA[StartDate]RANGE[2015-01-01,MAX]"),
        ({"end_year": 2020}, "AREA[StartDate]RANGE[MIN,2020-12-31]"),
    ],
)
def test_open_ended_year_ranges(years: dict[str, int], expected: str) -> None:
    assert build_params(RetrievalFilters.model_validate(years), 1000)["filter.advanced"] == expected


def test_fields_trim_to_record_paths() -> None:
    fields = build_params(RetrievalFilters(), 1000)["fields"].split(",")
    assert "protocolSection.identificationModule.nctId" in fields
    assert all(path.startswith("protocolSection.") for path in fields)


# --- params_key ---


def test_params_key_ignores_insertion_order() -> None:
    assert params_key({"b": "2", "a": "1"}) == params_key({"a": "1", "b": "2"}) == "a=1&b=2"


def test_params_key_url_encodes_values() -> None:
    assert params_key({"filter.advanced": "AREA[Phase]PHASE3 AND x"}) == (
        "filter.advanced=AREA%5BPhase%5DPHASE3+AND+x"
    )


def test_params_key_differs_per_filter_and_is_stable_per_filter() -> None:
    api, _, _ = fake_client(paged({}))
    a = RetrievalFilters(drug_name="Pembrolizumab")
    b = RetrievalFilters(drug_name="Nivolumab")
    assert params_key(api.params_for(a)) == params_key(api.params_for(a.model_copy()))
    assert params_key(api.params_for(a)) != params_key(api.params_for(b))


# --- pagination and the cap (CLAUDE.md §7.3) ---


def test_follows_next_page_tokens_until_the_lastpage() -> None:
    pages = {None: page([1, 2], "t1", total=5), "t1": page([3, 4], "t2"), "t2": page([5], None)}
    api, requests, _ = fake_client(paged(pages))
    result = api.fetch(RetrievalFilters(drug_name="x"))
    assert [r["protocolSection"]["identificationModule"]["nctId"] for r in result.records] == [
        f"NCT{n:08d}" for n in [1, 2, 3, 4, 5]
    ]
    assert (result.fetched, result.total, result.capped) == (5, 5, False)
    assert [page.index for page in result.pages] == [0, 1, 2]
    assert [r.url.params.get("pageToken") for r in requests] == [None, "t1", "t2"]
    # Every page repeats the same base params; only pageToken changes.
    assert all(r.url.params.get("query.intr") == "x" for r in requests)


def test_stops_at_the_cap_and_discloses_the_total() -> None:
    pages = {
        None: page([1, 2], "t1", total=6),
        "t1": page([3, 4], "t2"),
        "t2": page([5, 6], None),
    }
    api, requests, _ = fake_client(paged(pages), cap=3)
    result = api.fetch(RetrievalFilters())
    assert len(requests) == 2  # the third page is never requested
    assert (result.fetched, result.total, result.capped) == (3, 6, True)
    assert requests[0].url.params["pageSize"] == "3"


def test_page_size_never_exceeds_the_api_maximum() -> None:
    api, _, _ = fake_client(paged({}), cap=5000)
    assert api.params_for(RetrievalFilters())["pageSize"] == "1000"


def test_zero_results_is_one_emptypage() -> None:
    api, requests, _ = fake_client(paged({None: page([], None, total=0)}))
    result = api.fetch(RetrievalFilters(drug_name="zzqqxx"))
    assert (len(requests), result.fetched, result.total, result.capped) == (1, 0, 0, False)


def test_result_carries_the_params_key_and_verbatim_pages() -> None:
    body = page([1], None, total=1)
    api, _, _ = fake_client(paged({None: body}))
    filters = RetrievalFilters(drug_name="x")
    result = api.fetch(filters)
    assert result.params_key == params_key(api.params_for(filters))
    assert result.pages[0].body == body


# --- retries and upstream errors (CLAUDE.md §7.3) ---


def test_retries_5xx_and_429_with_backoff_then_succeeds() -> None:
    ok = httpx.Response(200, json=page([1], None, total=1))
    api, requests, sleeps = fake_client(scripted([httpx.Response(503), httpx.Response(429), ok]))
    assert api.fetch(RetrievalFilters()).fetched == 1
    assert len(requests) == 3
    assert sleeps == [1.0, RATE_LIMIT_RECOVERY_SECONDS]  # a 429 waits out the measured recovery


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("3", [3.0]),  # longer than the backoff: wait as asked
        ("0", [1.0]),  # shorter: the backoff still applies
        ("soon", [RATE_LIMIT_RECOVERY_SECONDS]),  # unreadable: the measured recovery
        ("Wed, 21 Oct 2015 07:28:00 GMT", [1.0]),  # an HTTP-date already past
        ("Wed, 21 Oct 2015 07:28:00 -0000", [1.0]),  # parses without a zone
    ],
)
def test_429_waits_at_least_as_long_as_retry_after_asks(header: str, expected: list[float]) -> None:
    ok = httpx.Response(200, json=page([1], None, total=1))
    limited = httpx.Response(429, headers={"Retry-After": header})
    api, _, sleeps = fake_client(scripted([limited, ok]))
    assert api.fetch(RetrievalFilters()).fetched == 1
    assert sleeps == expected


def test_retry_after_beyond_the_wait_limit_fails_now_instead_of_stalling() -> None:
    # A user would wait a minute for nothing; a 502 saying so is the faster answer.
    limited = httpx.Response(429, headers={"Retry-After": "60"})
    api, requests, sleeps = fake_client(scripted([limited]))
    with pytest.raises(UpstreamError, match="HTTP 429.*retry after 60 s"):
        api.fetch(RetrievalFilters())
    assert (len(requests), sleeps) == (1, [])


def test_gives_up_after_two_retries() -> None:
    api, requests, _ = fake_client(scripted([httpx.Response(502)] * 3))
    with pytest.raises(UpstreamError, match="HTTP 502"):
        api.fetch(RetrievalFilters())
    assert len(requests) == 3


def test_client_error_is_not_retried_and_keeps_the_api_reason() -> None:
    reason = "Invalid value in parameter `overallStatus`: `OPEN`"
    api, requests, _ = fake_client(scripted([httpx.Response(400, text=reason)]))
    with pytest.raises(UpstreamError, match="HTTP 400.*overallStatus"):
        api.fetch(RetrievalFilters())
    assert len(requests) == 1


def test_timeout_is_an_upstream_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    api, _, _ = fake_client(timeout)
    with pytest.raises(UpstreamError, match="ReadTimeout"):
        api.fetch(RetrievalFilters())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"totalCount": 1}),
        httpx.Response(200, json={"studies": []}),
    ],
    ids=["non-json", "non-object", "no-studies", "no-total"],
)
def test_malformed_body_is_an_upstream_error(response: httpx.Response) -> None:
    api, _, _ = fake_client(scripted([response]))
    with pytest.raises(UpstreamError):
        api.fetch(RetrievalFilters())


# --- count (the §7.8 not-found probe) ---


def test_count_asks_for_one_id_only_and_returns_the_total() -> None:
    client, requests, _ = fake_client(scripted([httpx.Response(200, json=page([1], "t", 4321))]))
    assert client.count(RetrievalFilters(drug_name="Zorblaxumab")) == 4321
    params = requests[0].url.params
    assert params["pageSize"] == "1" and params["fields"] == "NCTId"
    assert params["countTotal"] == "true" and params["query.intr"] == "Zorblaxumab"
    assert len(requests) == 1


def test_count_of_zero() -> None:
    client, _, _ = fake_client(scripted([httpx.Response(200, json=page([], None, 0))]))
    assert client.count(RetrievalFilters(condition="nothing")) == 0


def test_count_retries_and_raises_like_fetch() -> None:
    client, _, _ = fake_client(scripted([httpx.Response(503)] * 3))
    with pytest.raises(UpstreamError):
        client.count(RetrievalFilters(condition="x"))


# --- client-side rate limit (measured 2026-10-05: ~10-request burst, then ~1 request/s) ---


class FakeClock:
    """Time that moves only when told to, so waits are exact and tests never sleep."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)


def _limiter(rate: float = 1.0, burst: int = 3) -> tuple[RateLimiter, FakeClock]:
    clock = FakeClock()
    return RateLimiter(rate, burst, clock=clock, sleep=clock.sleep), clock


def test_a_burst_goes_out_at_once_then_requests_are_spaced_at_the_rate() -> None:
    limiter, clock = _limiter(rate=1.0, burst=3)
    for _ in range(5):
        limiter.acquire()
    assert clock.waits == [1.0, 2.0]  # the 4th and 5th each reserve the next free second


def test_idle_time_refills_the_burst_up_to_its_size() -> None:
    limiter, clock = _limiter(rate=1.0, burst=3)
    for _ in range(3):
        limiter.acquire()
    clock.now = 100.0
    for _ in range(4):
        limiter.acquire()
    assert clock.waits == [1.0]  # 3 refilled, not 100


def test_a_429_drains_the_burst_so_every_thread_slows_down() -> None:
    limiter, clock = _limiter(rate=1.0, burst=3)
    limiter.drain()
    limiter.acquire()
    assert clock.waits == [1.0]


def test_threads_sharing_a_limiter_each_get_a_distinct_slot() -> None:
    limiter, clock = _limiter(rate=2.0, burst=2)
    threads = [threading.Thread(target=limiter.acquire) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 2 free, then 8 reserved slots 0.5 s apart: no two threads were given the same slot.
    assert sorted(clock.waits) == [0.5 * k for k in range(1, 9)]


def test_every_request_waits_for_the_limiter() -> None:
    pages = {None: page([1], "t1", total=3), "t1": page([2], "t2"), "t2": page([3], None)}
    limiter, clock = _limiter(rate=1.0, burst=1)
    api, _, _ = fake_client(paged(pages), limiter=limiter)
    api.fetch(RetrievalFilters())
    assert clock.waits == [1.0, 2.0]


def test_429_without_retry_after_waits_out_the_measured_recovery() -> None:
    # Measured: a 429 cleared after ~8 s; the 1 s and 2 s backoffs failed a live request.
    ok = httpx.Response(200, json=page([1], None, total=1))
    api, _, sleeps = fake_client(scripted([httpx.Response(429), ok]))
    assert api.fetch(RetrievalFilters()).fetched == 1
    assert sleeps == [RATE_LIMIT_RECOVERY_SECONDS]


def test_one_client_per_settings_has_its_own_limiter_shared_by_its_requests() -> None:
    settings = load_settings(
        {"OPENAI_API_KEY": "k", "OPENAI_MODEL": "m", "DATABASE_URL": "postgresql://x/y"}
    )
    client = CtgovClient.from_settings(settings)
    assert client.limiter is client.limiter and isinstance(client.limiter, RateLimiter)
