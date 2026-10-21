"""Recorded-shape Claude Code Analytics pages with made-up people and keys."""
import json

import httpx

KEY = "sk-ant-admin01-FAKE-KEY-FOR-TESTS"

PAGE_1 = {
    "data": [
        {
            "date": "2026-03-17T00:00:00Z",
            "actor": {"type": "user_actor", "email_address": "Ada@Corp.Example"},
            "organization_id": "00000000-0000-0000-0000-000000000001",
            "customer_type": "api",
            "terminal_type": "vscode",
            "core_metrics": {
                "num_sessions": 2,
                "lines_of_code": {"added": 40, "removed": 5},
                "commits_by_claude_code": 1,
                "pull_requests_by_claude_code": 0,
            },
            "tool_actions": {"edit_tool": {"accepted": 6, "rejected": 1}, "write_tool": {"accepted": 2, "rejected": 0}},
            "model_breakdown": [
                {
                    "model": "model-a",
                    "tokens": {"input": 1000, "output": 200, "cache_read": 5000, "cache_creation": 300},
                    "estimated_cost": {"amount": 1250, "currency": "USD"},
                },
                {
                    "model": "model-b",
                    "tokens": {"input": 100, "output": 50, "cache_read": 0, "cache_creation": 0},
                    "estimated_cost": {"amount": 330, "currency": "USD"},
                },
            ],
        },
        {
            "date": "2026-03-17T00:00:00Z",
            "actor": {"type": "user_actor", "email_address": "ada@corp.example"},
            "customer_type": "api",
            "terminal_type": "iTerm.app",
            "is_remote": True,
            "core_metrics": {"num_sessions": 1, "lines_of_code": {"added": 10, "removed": 0}},
            "tool_actions": {"edit_tool": {"accepted": 1, "rejected": 0}, "future_tool": {"accepted": 3, "rejected": 0}},
            "model_breakdown": [
                {
                    "model": "model-a",
                    "tokens": {"input": 10, "output": 5, "cache_read": 20, "cache_creation": 0},
                    "estimated_cost": {"amount": 250.5, "currency": "USD"},
                }
            ],
        },
    ],
    "has_more": True,
    "next_page": "page-2",
}

PAGE_2 = {
    "data": [
        {
            "date": "2026-03-17T00:00:00Z",
            "actor": {"type": "api_actor", "api_key_name": "ci-runner"},
            "customer_type": "api",
            "model_breakdown": [
                {
                    "model": "model-a",
                    "tokens": {"input": 500, "output": 100, "cache_read": 0, "cache_creation": 0},
                    "estimated_cost": {"amount": 99, "currency": "USD"},
                }
            ],
        },
        {"date": "2026-03-17T00:00:00Z", "actor": {"type": "service_actor"}, "model_breakdown": []},
        {
            "date": "2026-03-17T00:00:00Z",
            "actor": {"type": "user_actor", "email_address": "bo@corp.example"},
            "customer_type": "subscription",
            "subscription_type": "team",
            "core_metrics": {"num_sessions": 1},
            "model_breakdown": [
                {
                    "model": "model-a",
                    "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0},
                    "estimated_cost": {"amount": 1000, "currency": "USD"},
                }
            ],
        },
    ],
    "has_more": False,
    "next_page": None,
}

EMPTY = {"data": [], "has_more": False, "next_page": None}


def transport(pages_by_day, status=None, calls=None):
    """Serve `pages_by_day[day]` (a list of page bodies, paged by `page-N`); `status` forces an error code."""

    def handler(request):
        if calls is not None:
            calls.append(request)
        if status is not None:
            return httpx.Response(status, json={"error": {"type": "error", "message": "nope"}})
        day = request.url.params.get("starting_at")
        pages = pages_by_day.get(day, [EMPTY])
        token = request.url.params.get("page")
        index = int(token.split("-")[1]) - 1 if token else 0
        return httpx.Response(200, content=json.dumps(pages[index]).encode("utf-8"))

    return httpx.MockTransport(handler)


# ---- user_cost_report shape (made-up people, *.example only) ----

def cost_row(email="ada@corp.example", day="2026-03-17", amount="41280.000000", model="model-a", **extra):
    row = {
        "actor": {"type": "user_actor", "deleted": False, "email_address": email, "name": None, "user_id": "user_1"},
        "amount": amount,
        "list_amount": amount,
        "currency": "USD",
        "model": model,
        "product": "claude_code",
        "starting_at": f"{day}T00:00:00Z",
        "ending_at": f"{day}T00:00:00Z",
        "requests": 3,
    }
    row.update(extra)
    return row


def cost_page(rows, more=False, next_page=None, refreshed="2099-01-01T00:00:00Z"):
    return {
        "data": rows, "data_refreshed_at": refreshed, "has_more": more, "next_page": next_page,
        "organization_id": "00000000-0000-0000-0000-000000000001",
    }


def cost_transport(pages_by_start=None, status=None, calls=None, default=None):
    """Serve `pages_by_start[starting_at]` (list of pages, paged by `page-N`) for the user cost report.

    `status` may be an int or a function of the 1-based call count returning an int or None.
    """
    pages_by_start = pages_by_start or {}
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if calls is not None:
            calls.append(request)
        code = status(state["n"]) if callable(status) else status
        if code is not None:
            return httpx.Response(code, json={"error": {"type": "error", "message": "nope"}})
        start = request.url.params.get("starting_at")
        pages = pages_by_start.get(start, [default or cost_page([])])
        token = request.url.params.get("page")
        index = int(token.split("-")[1]) - 1 if token else 0
        return httpx.Response(200, content=json.dumps(pages[index]).encode("utf-8"))

    return httpx.MockTransport(handler)
