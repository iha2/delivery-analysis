import json

import pytest

from claude_fakes import PAGE_1, PAGE_2
from delivery_analysis.connectors.claude_code.normalize import (
    NormalizeError, activity_values, normalize_day, usage_values,
)


def test_rows_are_summed_per_actor_and_model_with_cents_as_dollars():
    result = normalize_day("2026-03-17", PAGE_1["data"] + PAGE_2["data"])
    usage = [(r.actor_type, r.actor, r.model, r.cost_usd, r.input_tokens, r.output_tokens, r.cache_read_tokens,
              r.cache_creation_tokens) for r in result.usage]
    assert usage == [
        ("claude_api_key", "ci-runner", "model-a", 0.99, 500, 100, 0, 0),
        ("email", "ada@corp.example", "model-a", 15.005, 1010, 205, 5020, 300),
        ("email", "ada@corp.example", "model-b", 3.3, 100, 50, 0, 0),
        ("email", "bo@corp.example", "model-a", 10.0, 0, 0, 0, 0),
    ]
    assert result.skipped == 1


def test_activity_is_summed_and_new_tool_names_are_kept():
    result = normalize_day("2026-03-17", PAGE_1["data"] + PAGE_2["data"])
    ada = next(r for r in result.activity if r.actor == "ada@corp.example")
    assert (ada.sessions, ada.lines_added, ada.lines_removed, ada.commits, ada.pull_requests,
            ada.edits_accepted, ada.edits_rejected, ada.customer_types) == (3, 50, 5, 1, 0, 9, 1, "api")
    assert json.loads(ada.tool_actions) == {
        "edit_tool": {"accepted": 7, "rejected": 1},
        "future_tool": {"accepted": 3, "rejected": 0},
        "write_tool": {"accepted": 2, "rejected": 0},
    }
    bo = next(r for r in result.activity if r.actor == "bo@corp.example")
    assert bo.customer_types == "subscription" and bo.sessions == 1


def test_column_dicts_match_the_tables():
    result = normalize_day("2026-03-17", PAGE_2["data"])
    assert usage_values("claude_code_analytics", result.usage[0]) == {
        "source": "claude_code_analytics", "day": "2026-03-17", "actor_type": "claude_api_key",
        "actor": "ci-runner", "model": "model-a", "cost_usd": 0.99, "input_tokens": 500,
        "output_tokens": 100, "cache_read_tokens": 0, "cache_creation_tokens": 0,
    }
    assert set(activity_values("claude_code_analytics", result.activity[0])) == {
        "source", "day", "actor_type", "actor", "sessions", "lines_added", "lines_removed", "commits",
        "pull_requests", "edits_accepted", "edits_rejected", "tool_actions", "customer_types",
    }


def test_a_currency_other_than_usd_fails_the_day():
    record = {
        "actor": {"type": "user_actor", "email_address": "ada@corp.example"},
        "model_breakdown": [{"model": "m", "estimated_cost": {"amount": 1, "currency": "EUR"}}],
    }
    with pytest.raises(NormalizeError, match="EUR"):
        normalize_day("2026-03-17", [record])
