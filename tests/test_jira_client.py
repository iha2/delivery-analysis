import base64
import json

import httpx
import pytest

from delivery_analysis.connectors.jira import client as jc
from jira_fakes import FakeJira

TOKEN = "tok-jira-LEAK-1"
EMAIL = "me@corp.example"


def make(handler, **kwargs):
    kwargs.setdefault("sleep", lambda seconds: None)
    kwargs.setdefault("jitter", lambda: 0.5)
    return jc.JiraClient(EMAIL, TOKEN, transport=httpx.MockTransport(handler), **kwargs)


def test_credentials_come_from_two_variables_or_one_email_token_pair():
    assert jc.jira_credentials({"ATLASSIAN": " tok ", "ATLASSIAN_EMAIL": " me@corp.example "}) == (
        "me@corp.example", "tok"
    )
    assert jc.jira_credentials({"ATLASSIAN": "who@corp.example:tok", "ATLASSIAN_EMAIL": "other@corp.example"}) == (
        "who@corp.example", "tok"
    )
    assert jc.jira_credentials({"ATLASSIAN": "tok"}) == ("", "tok")
    assert jc.jira_credentials({}) == ("", "")


def test_base_url_defaults_and_can_be_overridden():
    assert jc.base_url_from({}) == "https://keyjira.atlassian.net"
    assert jc.base_url_from({"JIRA_BASE_URL": " https://api.atlassian.com/ex/jira/abc "}) == (
        "https://api.atlassian.com/ex/jira/abc"
    )


def test_requests_use_basic_auth_json_and_the_v3_prefix():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"accountId": "a"})

    client = make(handler)
    assert client.myself() == {"accountId": "a"}
    assert seen["auth"] == "Basic " + base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
    assert seen["url"] == "https://keyjira.atlassian.net/rest/api/3/myself"
    gateway = jc.JiraClient(
        EMAIL, TOKEN, base_url="https://api.atlassian.com/ex/jira/abc/",
        transport=httpx.MockTransport(handler),
    )
    gateway.myself()
    assert seen["url"] == "https://api.atlassian.com/ex/jira/abc/rest/api/3/myself"


@pytest.mark.parametrize(
    "status, error, text",
    [
        (401, jc.AuthError, "rejected the email or token"),
        (403, jc.ForbiddenError, "permission"),
        (404, jc.NotFoundError, "did not find"),
        (500, jc.JiraError, "HTTP 500"),
    ],
)
def test_error_statuses_become_plain_messages_without_the_token_or_email(status, error, text):
    client = make(lambda request: httpx.Response(status, json={}))
    with pytest.raises(error) as caught:
        client.get("/myself")
    assert text in str(caught.value)
    assert TOKEN not in str(caught.value) and EMAIL not in str(caught.value)


def test_a_400_carries_jiras_own_message():
    client = make(lambda request: httpx.Response(400, json={"errorMessages": ["The JQL is bad"]}))
    with pytest.raises(jc.JiraError, match="The JQL is bad"):
        client.post("/search/jql", {"jql": "x"})


def test_an_empty_body_is_a_configuration_hint():
    client = make(lambda request: httpx.Response(200, content=b""))
    with pytest.raises(jc.JiraError, match="api.atlassian.com/ex/jira"):
        client.myself()


def test_backoff_doubles_on_429_and_5xx_then_succeeds():
    calls = []
    waits = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429 if len(calls) == 1 else 503 if len(calls) == 2 else 200, json={"ok": True})

    client = make(handler, sleep=waits.append)
    assert client.get("/field") == {"ok": True}
    assert waits == [2.0, 4.0]


def test_retry_after_is_honoured_and_retries_run_out_with_a_plain_error():
    waits = []
    client = make(lambda request: httpx.Response(429, headers={"Retry-After": "7"}), sleep=waits.append, max_retries=2)
    with pytest.raises(jc.RateLimitedError, match="retry later"):
        client.get("/field")
    assert waits == [7.0, 7.0]


def test_a_quota_429_stops_at_once_and_names_the_reset():
    waits = []
    headers = {"RateLimit-Reason": "jira-quota-tenant-based", "X-RateLimit-Reset": "2026-10-15T13:00:00Z"}
    client = make(lambda request: httpx.Response(429, headers=headers), sleep=waits.append)
    with pytest.raises(jc.RateLimitedError, match="quota.*2026-10-15T13:00:00Z"):
        client.get("/field")
    assert waits == [] and client.requests_made == 1


def test_a_near_limit_header_slows_the_next_call():
    waits = []
    client = make(lambda request: httpx.Response(200, json={}, headers={"X-RateLimit-NearLimit": "true"}), sleep=waits.append)
    client.get("/field")
    assert waits == [2.0]


def test_the_request_budget_ends_a_run():
    client = make(lambda request: httpx.Response(200, json={}), budget=2)
    client.get("/field")
    client.get("/field")
    with pytest.raises(jc.BudgetExhausted):
        client.get("/field")
    assert client.budget_left == 0


def test_search_posts_the_jql_page_size_and_token():
    fake = FakeJira(email=EMAIL, token=TOKEN)
    fake.add_project("MD", 1, "Move Docs", ["To Do"])
    client = jc.JiraClient(EMAIL, TOKEN, transport=fake.transport())
    client.search('project = "MD"', ["*all", "-description"], "t5")
    method, path, body = fake.requests[-1]
    assert (method, path) == ("POST", "/rest/api/3/search/jql")
    assert body == {"jql": 'project = "MD"', "maxResults": 100, "fields": ["*all", "-description"], "nextPageToken": "t5"}


def test_changelog_pages_resend_the_body_with_the_token_and_stop_on_a_repeat():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        token = body.get("nextPageToken")
        if token is None:
            return httpx.Response(200, json={"issueChangeLogs": [], "nextPageToken": "a"})
        if token == "a":
            return httpx.Response(200, json={"issueChangeLogs": [], "nextPageToken": "b"})
        return httpx.Response(200, json={"issueChangeLogs": [], "nextPageToken": "b"})

    pages = list(make(handler).changelog_pages(["1", "2"], ["status"]))
    assert len(pages) == 3
    assert [b.get("nextPageToken") for b in bodies] == [None, "a", "b"]
    assert all(b["issueIdsOrKeys"] == ["1", "2"] and b["fieldIds"] == ["status"] for b in bodies)


def test_project_helpers_quote_the_key():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=[])

    client = make(handler)
    client.project("MD")
    client.project_statuses("MD")
    assert seen == ["/rest/api/3/project/MD", "/rest/api/3/project/MD/statuses"]
