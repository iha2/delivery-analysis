import pytest

from delivery_analysis.model.records import Batch, RawPayload, Record
from delivery_analysis.store import db
from delivery_analysis.store import sync_state as ss
from delivery_analysis.store import upsert as up

NOW = "2026-05-02T00:00:00Z"


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "d.sqlite")
    db.migrate(connection)
    yield connection
    connection.close()


def item(source_id, **extra):
    values = {"source": "jira", "source_id": source_id, "key": "MD-" + source_id}
    values.update(extra)
    return Record("work_item", values)


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_record_rejects_unknown_table_and_missing_key():
    with pytest.raises(ValueError, match="unknown table"):
        Record("nope", {"a": 1})
    with pytest.raises(ValueError, match="source_id"):
        Record("work_item", {"source": "jira"})


def test_upserting_twice_keeps_one_row_and_updates_values(conn):
    up.upsert_record(conn, item("1", status="todo"), NOW)
    up.upsert_record(conn, item("1", status="done"), NOW)
    assert count(conn, "work_item") == 1
    row = conn.execute("SELECT status, fetched_at FROM work_item").fetchone()
    assert (row["status"], row["fetched_at"]) == ("done", NOW)


def test_unknown_column_is_rejected(conn):
    with pytest.raises(ValueError, match="nope"):
        up.upsert_record(conn, item("1", nope=1), NOW)


def test_composite_key_tables_keep_distinct_rows(conn):
    conn.execute("INSERT INTO person (person_id, display_name, excluded, manual) VALUES ('p1', 'Ada Example', 0, 0)")
    base = {"person_id": "p1", "day": "2026-05-01", "model": "m", "cost_usd": 1.5, "source": "claude",
            "purpose_method": "model_mix_v1", "purpose_confidence": "low"}
    up.upsert_record(conn, Record("token_usage", dict(base, purpose="ask")), NOW)
    up.upsert_record(conn, Record("token_usage", dict(base, purpose="generate")), NOW)
    up.upsert_record(conn, Record("token_usage", dict(base, purpose="ask", cost_usd=2.0)), NOW)
    assert count(conn, "token_usage") == 2
    cost = conn.execute("SELECT cost_usd FROM token_usage WHERE purpose='ask'").fetchone()["cost_usd"]
    assert cost == 2.0


def test_raw_payload_is_replaced_not_duplicated(conn):
    up.upsert_raw(conn, RawPayload("jira", "1", "issue", '{"v":1}'), NOW)
    up.upsert_raw(conn, RawPayload("jira", "1", "issue", '{"v":2}'), NOW)
    assert count(conn, "raw_payload") == 1
    assert conn.execute("SELECT json FROM raw_payload").fetchone()["json"] == '{"v":2}'


def test_write_batch_writes_records_and_raw(conn):
    batch = Batch(
        records=[item("1"), item("2")],
        raw=[RawPayload("jira", "1", "issue", "{}")],
        cursor="2026-05-02T00:00:00Z",
    )
    assert up.write_batch(conn, batch, NOW) == 2
    assert count(conn, "work_item") == 2
    assert count(conn, "raw_payload") == 1


def test_unmapped_identities_excludes_mapped_accounts(conn):
    up.upsert_record(conn, item("1", assignee_account="acc-1", reporter_account="acc-2"), NOW)
    up.upsert_record(conn, item("2", assignee_account=""), NOW)
    up.upsert_record(conn, Record("person", {"person_id": "p1", "display_name": "Ann"}), NOW)
    up.upsert_record(
        conn,
        Record("identity", {"source": "jira", "account_id": "acc-1", "person_id": "p1"}),
        NOW,
    )
    assert up.unmapped_identities(conn) == [("jira", "acc-2")]


def test_sync_state_cursor_and_health(conn):
    assert ss.get_cursor(conn, "fake", "main") is None
    ss.set_cursor(conn, "fake", "main", "2026-05-10T00:00:00Z")
    assert ss.get_cursor(conn, "fake", "main") == "2026-05-10T00:00:00Z"
    ss.save_state(conn, "fake", "main", status="ok", error=None, records=3, now=NOW)
    ss.save_state(conn, "fake", "main", status="failed", error="boom", records=3, now=NOW)
    assert ss.get_cursor(conn, "fake", "main") == "2026-05-10T00:00:00Z"
    states = ss.list_sync_states(conn)
    assert len(states) == 1
    assert states[0]["stale"] is True
    assert states[0]["error"] == "boom"
    assert states[0]["last_run"] == NOW
