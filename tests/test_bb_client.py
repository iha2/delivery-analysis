import base64

import httpx
import pytest

from delivery_analysis.connectors.bitbucket import client as c

TOKEN = "tok-bb-secret-1"


def make(handler, **kwargs):
    sleeps = []
    client = c.BitbucketClient(
        kwargs.pop("token", TOKEN),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        jitter=lambda: 0.0,
        **kwargs,
    )
    return client, sleeps


def test_bearer_for_a_plain_token_and_basic_for_email_colon_token():
    assert c.auth_header("abc") == {"Authorization": "Bearer abc"}
    basic = base64.b64encode(b"ann@corp.example:abc").decode("ascii")
    assert c.auth_header("ann@corp.example:abc") == {"Authorization": f"Basic {basic}"}


def test_get_sends_the_header_and_returns_json():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True})

    client, _ = make(handler)
    assert client.get("/repositories/ws", {"pagelen": 1}) == {"ok": True}
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert seen["url"] == "https://api.bitbucket.org/2.0/repositories/ws?pagelen=1"
    assert client.requests_made == 1


def test_repeated_query_parameters_are_sent_for_list_values():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={})

    client, _ = make(handler)
    client.get("/x", {"state": ["OPEN", "MERGED"], "pagelen": 100})
    assert "state=OPEN&state=MERGED" in seen["url"]


def test_pages_follow_next_links_verbatim():
    def handler(request):
        page = int(request.url.params.get("page", "1"))
        body = {"values": [page]}
        if page < 3:
            body["next"] = f"https://api.bitbucket.org/2.0/things?page={page + 1}"
        return httpx.Response(200, json=body)

    client, _ = make(handler)
    assert [p["values"] for p in client.pages("/things")] == [[1], [2], [3]]
    assert client.requests_made == 3


def test_a_repeated_next_link_stops_the_walk():
    def handler(request):
        return httpx.Response(200, json={"values": [], "next": "https://api.bitbucket.org/2.0/loop?page=2"})

    client, _ = make(handler)
    assert len(list(client.pages("/loop"))) == 2


def test_rate_limit_retries_with_exponential_waits_then_succeeds():
    answers = [429, 429, 200]

    def handler(request):
        status = answers.pop(0)
        return httpx.Response(status, json={"done": status == 200})

    client, sleeps = make(handler)
    assert client.get("/x") == {"done": True}
    assert sleeps == [2.0, 4.0]


def test_retry_after_header_is_honoured():
    answers = [(429, {"Retry-After": "7"}), (200, {})]

    def handler(request):
        status, headers = answers.pop(0)
        return httpx.Response(status, headers=headers, json={})

    client, sleeps = make(handler)
    client.get("/x")
    assert sleeps == [7.0]


def test_retries_that_run_out_raise_a_rate_limited_error():
    def handler(request):
        return httpx.Response(503, json={})

    client, sleeps = make(handler, max_retries=2)
    with pytest.raises(c.RateLimitedError, match="retry later"):
        client.get("/x")
    assert len(sleeps) == 2 and client.requests_made == 3


@pytest.mark.parametrize(
    "status, error, words",
    [
        (401, c.AuthError, "rejected the token"),
        (403, c.ForbiddenError, "lacks permission"),
        (404, c.NotFoundError, "did not find"),
        (500, c.BitbucketError, "HTTP 500"),
    ],
)
def test_error_statuses_become_typed_errors_without_the_token(status, error, words):
    def handler(request):
        return httpx.Response(status, json={"error": "x"})

    client, _ = make(handler)
    with pytest.raises(error) as info:
        client.get("/x")
    assert words in str(info.value)
    assert TOKEN not in str(info.value)


def test_the_request_budget_is_enforced_before_the_request_is_made():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={})

    client, _ = make(handler, budget=2)
    client.get("/a")
    client.get("/b")
    assert client.budget_left == 0
    with pytest.raises(c.BudgetExhausted):
        client.get("/c")
    assert len(calls) == 2 and client.requests_made == 2


def test_a_near_limit_header_slows_the_next_request():
    def handler(request):
        return httpx.Response(200, headers={"X-RateLimit-NearLimit": "true"}, json={})

    client, sleeps = make(handler)
    client.get("/x")
    assert sleeps == [2.0]


def test_redirects_are_followed_and_the_header_survives_on_the_same_host():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("Authorization")))
        if request.url.path.endswith("/diffstat"):
            return httpx.Response(302, headers={"Location": "https://api.bitbucket.org/2.0/real"})
        return httpx.Response(200, json={"values": []})

    client, _ = make(handler)
    client.get("/diffstat")
    assert seen == [("/2.0/diffstat", f"Bearer {TOKEN}"), ("/2.0/real", f"Bearer {TOKEN}")]


def test_network_failures_are_retried_then_reported_without_details():
    def handler(request):
        raise httpx.ConnectError("boom with https://secret-host.example")

    client, sleeps = make(handler, max_retries=2)
    with pytest.raises(c.BitbucketError) as info:
        client.get("/x")
    assert "Could not reach Bitbucket (ConnectError)" in str(info.value)
    assert "secret-host" not in str(info.value)
    assert len(sleeps) == 2
