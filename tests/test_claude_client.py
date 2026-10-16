import pytest

from claude_fakes import KEY, PAGE_1, PAGE_2, transport
from delivery_analysis.connectors.claude_code.client import (
    AuthError, ClaudeCodeClient, ClaudeUsageError, ForbiddenError, NotFoundError, RateLimitedError, usage_key,
)


class Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds

    def __call__(self):
        return self.now


def client(tx, clock=None, **kwargs):
    clock = clock or Clock()
    return ClaudeCodeClient(KEY, transport=tx, sleep=clock.sleep, clock=clock, jitter=lambda: 0.5, **kwargs)


def test_usage_key_prefers_the_admin_variable():
    assert usage_key({"ANTHROPIC_ADMIN": " a ", "ANTHROPIC": "b"}) == "a"
    assert usage_key({"ANTHROPIC_ADMIN": "  ", "ANTHROPIC": "b"}) == "b"
    assert usage_key({}) == ""


def test_pages_follow_the_cursor_with_headers_and_one_request_per_second():
    calls, clock = [], Clock()
    pages = list(client(transport({"2026-03-17": [PAGE_1, PAGE_2]}, calls=calls), clock).day_pages("2026-03-17"))
    assert [len(p["data"]) for p in pages] == [2, 3]
    first, second = calls
    assert first.headers["x-api-key"] == KEY and first.headers["anthropic-version"] == "2023-06-01"
    assert first.headers["user-agent"].startswith("delivery-analysis/")
    assert dict(first.url.params) == {"starting_at": "2026-03-17", "limit": "1000"}
    assert dict(second.url.params) == {"starting_at": "2026-03-17", "limit": "1000", "page": "page-2"}
    assert clock.slept == [1.0]


def test_retry_after_is_honoured_then_the_request_succeeds():
    state = {"n": 0}
    import httpx

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "3"})
        return httpx.Response(200, json={"data": [], "has_more": False, "next_page": None})

    clock = Clock()
    pages = list(client(httpx.MockTransport(handler), clock).day_pages("2026-03-17"))
    assert pages[0]["data"] == [] and 3.0 in clock.slept


def test_errors_are_plain_and_never_contain_the_key():
    for status, error, words in (
        (401, AuthError, "rejected"),
        (403, ForbiddenError, "Admin key"),
        (404, NotFoundError, "Enterprise"),
    ):
        with pytest.raises(error) as caught:
            client(transport({}, status=status)).probe("2026-03-17")
        assert words in str(caught.value) and KEY not in str(caught.value)
    with pytest.raises(RateLimitedError):
        list(client(transport({}, status=503), max_retries=2).day_pages("2026-03-17"))


def test_a_repeated_page_cursor_stops_the_day():
    looping = dict(PAGE_1, next_page="page-1")
    with pytest.raises(ClaudeUsageError, match="cursor"):
        list(client(transport({"2026-03-17": [looping]})).day_pages("2026-03-17"))
