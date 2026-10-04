import httpx
import pytest

from app.ctgov import UpstreamError, build_params, params_key
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


# --- retries and upstream errors (CLAUDE.md §14 Phase 1 decision) ---


def test_retries_5xx_and_429_with_backoff_then_succeeds() -> None:
    ok = httpx.Response(200, json=page([1], None, total=1))
    api, requests, sleeps = fake_client(scripted([httpx.Response(503), httpx.Response(429), ok]))
    assert api.fetch(RetrievalFilters()).fetched == 1
    assert len(requests) == 3
    assert sleeps == [1.0, 2.0]


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
