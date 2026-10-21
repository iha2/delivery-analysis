from datetime import date

import httpx
import pytest

from claude_fakes import KEY, cost_page, cost_row, cost_transport
from delivery_analysis.connectors.claude_code.client import (
    AuthError, ClaudeCodeClient, ClaudeUsageError, ForbiddenError, NotFoundError, RateLimitedError,
)
from delivery_analysis.connectors.claude_code.connector import ClaudeCodeConnector
from delivery_analysis.connectors.claude_code.normalize import NormalizeError, normalize_cost_rows
from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.settings import Settings

TODAY = date(2026, 6, 20)
RANGE = ("2026-03-01", "2026-03-15")
START = "2026-03-01T00:00:00Z"


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


def connector(tx, **kwargs):
    c = ClaudeCodeClient(KEY, transport=tx, sleep=lambda s: None, clock=lambda: 0.0)
    kwargs.setdefault("report", "user_cost")
    return ClaudeCodeConnector(c, today=lambda: TODAY, **kwargs)


# ---- normalize ----

def test_cents_become_exact_dollars_with_lowercase_email():
    result = normalize_cost_rows([cost_row(email="Ada@Corp.Example")])
    (row,) = result.usage
    assert row.cost_usd == 412.8 and row.actor == "ada@corp.example" and row.actor_type == "email"
    assert row.day == "2026-03-17" and row.model == "model-a"
    assert (row.input_tokens, row.output_tokens, row.cache_read_tokens, row.cache_creation_tokens) == (0, 0, 0, 0)
    assert result.activity == [] and result.skipped == 0


def test_duplicates_are_summed_and_missing_model_is_unknown():
    rows = [cost_row(amount="100.5"), cost_row(email="ADA@corp.example", amount="0.25"),
            cost_row(model=None, amount="50"), cost_row(day="2026-03-18", amount="10")]
    result = normalize_cost_rows(rows)
    got = {(r.day, r.model): r.cost_usd for r in result.usage}
    assert got == {("2026-03-17", "model-a"): 1.0075, ("2026-03-17", "unknown"): 0.5, ("2026-03-18", "model-a"): 0.1}


def test_rows_without_an_email_or_start_are_skipped_and_counted():
    deleted = cost_row()
    deleted["actor"] = {"type": "user_actor", "deleted": True, "email_address": None, "user_id": "u"}
    nostart = cost_row()
    del nostart["starting_at"]
    result = normalize_cost_rows([deleted, nostart, cost_row()])
    assert len(result.usage) == 1 and result.skipped == 2


def test_a_non_usd_currency_is_refused():
    with pytest.raises(NormalizeError, match="EUR"):
        normalize_cost_rows([cost_row(currency="EUR")])


def test_the_day_is_the_utc_date_of_starting_at():
    row = cost_row()
    row["starting_at"] = "2026-03-17T23:30:00-05:00"
    assert normalize_cost_rows([row]).usage[0].day == "2026-03-18"


# ---- client ----

def test_request_params_are_exactly_as_specified():
    calls = []
    pages = list(client(cost_transport(calls=calls)).cost_pages(*RANGE))
    assert len(pages) == 1
    (request,) = calls
    params = request.url.params
    assert request.url.path == "/v1/organizations/analytics/user_cost_report"
    assert request.headers["x-api-key"] == KEY and request.headers["anthropic-version"] == "2023-06-01"
    assert params["starting_at"] == START and params["ending_at"] == "2026-03-15T00:00:00Z"
    assert params["bucket_width"] == "1d" and params["limit"] == "1000"
    assert params.get_list("group_by[]") == ["model"] and params.get_list("products[]") == ["claude_code"]
    assert set(params.keys()) == {"starting_at", "ending_at", "bucket_width", "limit", "group_by[]", "products[]"}


def test_paging_follows_the_cursor_with_the_same_query_and_pacing():
    calls, clock = [], Clock()
    tx = cost_transport({START: [
        cost_page([cost_row()], more=True, next_page="page-2"), cost_page([cost_row(email="bo@corp.example")]),
    ]}, calls=calls)
    pages = list(client(tx, clock).cost_pages(*RANGE))
    assert [len(p["data"]) for p in pages] == [1, 1]
    first, second = (dict(c.url.params) for c in calls)
    assert second.pop("page") == "page-2" and first == second
    assert clock.slept == [1.0]


def test_a_repeated_or_missing_cursor_stops():
    looping = cost_page([cost_row()], more=True, next_page="page-1")
    with pytest.raises(ClaudeUsageError, match="cursor"):
        list(client(cost_transport({START: [looping]})).cost_pages(*RANGE))
    missing = cost_page([cost_row()], more=True, next_page=None)
    with pytest.raises(ClaudeUsageError, match="cursor"):
        list(client(cost_transport({START: [missing]})).cost_pages(*RANGE))


def test_a_stale_cursor_restarts_the_range_once():
    calls = []
    pages_by = {START: [cost_page([cost_row()], more=True, next_page="page-2"), cost_page([cost_row()])]}
    # call 1 ok, call 2 (page-2) is 410, then the restart succeeds
    tx = cost_transport(pages_by, status=lambda n: 410 if n == 2 else None, calls=calls)
    pages = list(client(tx).cost_pages(*RANGE))
    assert len(pages) == 2 and len(calls) == 4
    assert "page" not in calls[2].url.params


def test_a_second_stale_cursor_fails_plainly():
    with pytest.raises(ClaudeUsageError) as caught:
        list(client(cost_transport(status=410)).cost_pages(*RANGE))
    assert KEY not in str(caught.value) and "cursor" in str(caught.value)


def test_errors_are_specific_and_never_contain_the_key():
    for status, error, words in (
        (401, AuthError, "rejected"),
        (403, ForbiddenError, "read:analytics"),
        (404, NotFoundError, "Enterprise"),
    ):
        with pytest.raises(error) as caught:
            list(client(cost_transport(status=status)).cost_pages(*RANGE))
        assert words in str(caught.value) and KEY not in str(caught.value)
        assert "Admin key" not in str(caught.value)
    with pytest.raises(RateLimitedError) as caught:
        list(client(cost_transport(status=503), max_retries=2).cost_pages(*RANGE))
    assert KEY not in str(caught.value)


def test_back_off_on_429_and_5xx_is_reused():
    calls = []
    transport = httpx.MockTransport(lambda r: (calls.append(r), httpx.Response(
        429, headers={"retry-after": "3"}) if len(calls) == 1 else httpx.Response(200, json=cost_page([])))[1])
    clock = Clock()
    pages = list(client(transport, clock).cost_pages(*RANGE))
    assert pages[0]["data"] == [] and 3.0 in clock.slept
    clock2 = Clock()
    list(client(cost_transport(status=lambda n: 500 if n == 1 else None), clock2).cost_pages(*RANGE))
    assert clock2.slept == [2.0]  # 2**1 * (0.7 + 0.6 * 0.5)


def test_probe_cost_asks_for_one_row_from_yesterday_to_today():
    calls = []
    client(cost_transport(calls=calls)).probe_cost(TODAY)
    params = calls[0].url.params
    assert params["starting_at"] == "2026-06-19T00:00:00Z" and params["ending_at"] == "2026-06-20T00:00:00Z"
    assert params["limit"] == "1"


# ---- connector ----

def test_validate_needs_no_admin_prefix_and_reports_plain_errors():
    calls = []
    assert connector(cost_transport(calls=calls), admin_key=False).validate() == []
    assert calls[0].url.params["starting_at"] == "2026-06-19T00:00:00Z"
    (problem,) = connector(cost_transport(status=403)).validate()
    assert "read:analytics" in problem and KEY not in problem


def test_a_90_day_window_is_fetched_in_chunks_of_at_most_31_days():
    calls = []
    batches = list(connector(cost_transport(calls=calls)).sync("org", None))
    spans = [(c.url.params["starting_at"][:10], c.url.params["ending_at"][:10]) for c in calls]
    assert spans == [("2026-03-22", "2026-04-22"), ("2026-04-22", "2026-05-23"), ("2026-05-23", "2026-06-21")]
    assert len(batches) == 91 and batches[0].replace[0][1]["day"] == "2026-03-22"
    assert batches[-1].replace[0][1]["day"] == "2026-06-20"
    raws = [b.raw for b in batches if b.raw]
    assert [r[0].source_id for r in raws] == ["2026-03-22..2026-04-22", "2026-04-22..2026-05-23", "2026-05-23..2026-06-21"]
    assert all(r[0].kind == "user_cost_chunk" and KEY not in r[0].json for r in raws)


def test_the_window_never_starts_before_the_endpoint_floor():
    calls = []
    c = ClaudeCodeClient(KEY, transport=cost_transport(calls=calls), sleep=lambda s: None, clock=lambda: 0.0)
    list(ClaudeCodeConnector(c, report="user_cost", today=lambda: date(2026, 2, 1)).sync("org", None))
    assert calls[0].url.params["starting_at"] == "2026-01-01T00:00:00Z"


def test_one_replacing_batch_per_day_and_empty_days_clear():
    tx = cost_transport({"2026-06-17T00:00:00Z": [cost_page([
        cost_row(day="2026-06-17", amount="1000"), cost_row(day="2026-06-19", amount="500", email="bo@corp.example"),
    ])]})
    batches = list(connector(tx).sync("org", "2026-06-17T00:00:00Z"))
    assert [b.replace[0][1]["day"] for b in batches] == ["2026-06-17", "2026-06-18", "2026-06-19", "2026-06-20"]
    assert batches[0].replace == [("claude_usage_day", {"source": "claude_code_analytics", "day": "2026-06-17"})]
    assert [len(b.records) for b in batches] == [1, 0, 1, 0]
    assert batches[0].records[0].values["cost_usd"] == 10.0
    assert batches[0].raw and not batches[1].raw


def test_cursor_only_on_complete_days_honouring_data_refreshed_at():
    tx = cost_transport({"2026-06-15T00:00:00Z": [cost_page([], refreshed="2026-06-17T12:00:00Z")]})
    batches = list(connector(tx).sync("org", "2026-06-15T00:00:00Z"))
    # days 15 and 16 end before the refresh; 17 ends after it; 18 is today-2 but not refreshed; 19, 20 too recent
    assert [b.cursor for b in batches] == ["2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", None, None, None, None]


def test_no_cursor_when_data_refreshed_at_is_missing():
    tx = cost_transport({"2026-06-15T00:00:00Z": [cost_page([], refreshed=None)]})
    assert [b.cursor for b in connector(tx).sync("org", "2026-06-15T00:00:00Z")] == [None] * 6


def test_cursors_stay_monotone_when_a_later_chunk_is_staler():
    tx = cost_transport({
        "2026-03-22T00:00:00Z": [cost_page([], refreshed="2099-01-01T00:00:00Z")],
        "2026-04-22T00:00:00Z": [cost_page([], refreshed=None)],
        "2026-05-23T00:00:00Z": [cost_page([], refreshed="2099-01-01T00:00:00Z")],
    })
    cursors = [b.cursor for b in connector(tx).sync("org", None)]
    first_none = cursors.index(None)
    assert first_none == 31 and cursors[0] is not None
    assert all(c is None for c in cursors[first_none:])


def test_the_old_report_mode_still_uses_the_old_endpoint():
    calls = []
    c = ClaudeCodeClient(KEY, transport=httpx.MockTransport(
        lambda r: (calls.append(r), httpx.Response(200, json={"data": [], "has_more": False}))[1]),
        sleep=lambda s: None, clock=lambda: 0.0)
    assert ClaudeCodeConnector(c, today=lambda: TODAY).validate() == []
    assert calls[0].url.path == "/v1/organizations/usage_report/claude_code"


# ---- registry ----

def test_the_registry_uses_user_cost_mode_for_any_key(tmp_path):
    calls = []
    settings = Settings(db_path=tmp_path / "d.sqlite")
    (plain,) = build_connectors(settings, {"ANTHROPIC": "sk-ant-api03-not-admin"}, transport=cost_transport(calls=calls))
    assert calls == []
    assert plain.validate() == []
    assert calls[0].url.path == "/v1/organizations/analytics/user_cost_report"
