import pytest

from delivery_analysis.connectors.fake import FakeConnector
from delivery_analysis.model.records import TABLE_KEYS, Batch, Record
from delivery_analysis.store.upsert import delete_matching, write_batch
from delivery_analysis.sync.runner import run_sync

NOW = "2026-03-21T00:00:00Z"


def usage(actor, day="2026-03-17", cost=1.0):
    return Record("claude_usage_day", {
        "source": "claude_code_analytics", "day": day, "actor_type": "email", "actor": actor,
        "model": "model-a", "cost_usd": cost,
    })


def actors(conn, day="2026-03-17"):
    return [r["actor"] for r in conn.execute(
        "SELECT actor FROM claude_usage_day WHERE day = ? ORDER BY actor", (day,))]


REPLACE = [("claude_usage_day", {"source": "claude_code_analytics", "day": "2026-03-17"})]


def test_replace_deletes_the_day_then_writes_the_new_rows(conn):
    write_batch(conn, Batch([usage("ada@corp.example"), usage("bo@corp.example"), usage("ada@corp.example", "2026-03-18")]), NOW)
    write_batch(conn, Batch([usage("ada@corp.example", cost=2.0)], replace=REPLACE), NOW)
    assert actors(conn) == ["ada@corp.example"]
    assert actors(conn, "2026-03-18") == ["ada@corp.example"]
    assert conn.execute("SELECT cost_usd FROM claude_usage_day WHERE day = '2026-03-17'").fetchone()[0] == 2.0


def test_replace_rejects_unknown_tables_columns_and_empty_filters(conn):
    with pytest.raises(ValueError, match="unknown table"):
        delete_matching(conn, "nope", {"a": 1})
    with pytest.raises(ValueError, match="at least one"):
        delete_matching(conn, "claude_usage_day", {})
    with pytest.raises(ValueError, match="no column"):
        delete_matching(conn, "claude_usage_day", {"nope": 1})


def test_a_failed_batch_rolls_back_its_delete(conn):
    write_batch(conn, Batch([usage("ada@corp.example"), usage("bo@corp.example")]), NOW)
    bad = Record("claude_usage_day", {
        "source": "claude_code_analytics", "day": "2026-03-17", "actor_type": "email", "actor": "x@corp.example",
        "model": "m", "cost_usd": 1.0, "nope": 1,
    })
    fake = FakeConnector(name="claude_code_analytics", batches={"org": [Batch([bad], replace=REPLACE)]})
    (result,) = run_sync(conn, [fake])
    assert result.status == "failed"
    assert actors(conn) == ["ada@corp.example", "bo@corp.example"]


@pytest.mark.parametrize("table", [
    "token_usage", "token_attribution", "ticket_credit", "claude_usage_day", "claude_activity_day",
])
def test_table_keys_match_the_primary_key_of_the_migration(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    primary = tuple(r["name"] for r in sorted((r for r in rows if r["pk"]), key=lambda r: r["pk"]))
    assert TABLE_KEYS[table] == primary
