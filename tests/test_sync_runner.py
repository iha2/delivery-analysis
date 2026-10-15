import pytest

from delivery_analysis.connectors.fake import FakeConnector
from delivery_analysis.model.records import Batch, Record
from delivery_analysis.store import db
from delivery_analysis.store import sync_state as ss
from delivery_analysis.store import upsert as up
from delivery_analysis.sync import runner

CLOCK = lambda: "2026-05-20T00:00:00Z"  # noqa: E731


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "d.sqlite")
    db.migrate(connection)
    yield connection
    connection.close()


def rec(n, source="fake", **extra):
    values = {"source": source, "source_id": str(n), "key": f"MD-{n}"}
    values.update(extra)
    return Record("work_item", values)


def rows(conn):
    return [r["source_id"] for r in conn.execute("SELECT source_id FROM work_item ORDER BY source_id")]


def test_shift_cursor_subtracts_days_and_tolerates_junk():
    assert runner.shift_cursor("2026-05-10T00:00:00Z", 7) == "2026-05-03T00:00:00Z"
    assert runner.shift_cursor(None, 7) is None
    assert runner.shift_cursor("", 7) is None
    assert runner.shift_cursor("garbage", 7) is None


def test_successful_run_stores_rows_cursor_and_health(conn):
    fake = FakeConnector(batches={"main": [Batch([rec(1), rec(2)], cursor="2026-05-10T00:00:00Z")]})
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert [(r.status, r.records, r.error) for r in results] == [("ok", 2, None)]
    assert rows(conn) == ["1", "2"]
    assert ss.get_cursor(conn, "fake", "main") == "2026-05-10T00:00:00Z"
    state = ss.list_sync_states(conn)[0]
    assert (state["status"], state["stale"], state["records"]) == ("ok", False, 2)


def test_second_run_is_idempotent_and_applies_the_overlap_window(conn):
    fake = FakeConnector(batches={"main": [Batch([rec(1)], cursor="2026-05-10T00:00:00Z")]})
    runner.run_sync(conn, [fake], overlap_days=7, now=CLOCK)
    runner.run_sync(conn, [fake], overlap_days=7, now=CLOCK)
    assert rows(conn) == ["1"]
    assert fake.calls == [("main", None), ("main", "2026-05-03T00:00:00Z")]


def test_failure_after_a_good_batch_keeps_that_batch_and_marks_stale(conn):
    fake = FakeConnector(
        batches={"main": [Batch([rec(1)], cursor="c1"), Batch([rec(2)], cursor="c2")]},
        fail_on_batch=1,
        fail_message="source down",
    )
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert (results[0].status, results[0].error) == ("failed", "source down")
    assert rows(conn) == ["1"]
    assert ss.get_cursor(conn, "fake", "main") == "c1"
    assert ss.list_sync_states(conn)[0]["stale"] is True


def test_a_batch_that_fails_while_writing_leaves_no_partial_rows_or_cursor(conn):
    bad = Record("work_item", {"source": "fake", "source_id": "9", "no_such_column": 1})
    fake = FakeConnector(
        batches={"main": [Batch([rec(1)], cursor="c1"), Batch([rec(2), bad], cursor="c2")]}
    )
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert results[0].status == "failed"
    assert "no_such_column" in results[0].error
    assert rows(conn) == ["1"]
    assert ss.get_cursor(conn, "fake", "main") == "c1"
    assert not conn.in_transaction


def test_one_failing_source_does_not_block_another(conn):
    broken = FakeConnector(name="broken", batches={"main": [Batch([rec(1, "broken")])]}, fail_on_batch=0)
    healthy = FakeConnector(name="healthy", batches={"main": [Batch([rec(5, "healthy")], cursor="h1")]})
    results = {r.connector: r.status for r in runner.run_sync(conn, [broken, healthy], now=CLOCK)}
    assert results == {"broken": "failed", "healthy": "ok"}
    assert rows(conn) == ["5"]


def test_missing_or_unparseable_cursor_means_a_full_sync(conn):
    ss.set_cursor(conn, "fake", "main", "garbage")
    fake = FakeConnector(batches={"main": [Batch([rec(1)])]})
    results = runner.run_sync(conn, [fake], now=CLOCK)
    assert results[0].status == "ok"
    assert fake.calls == [("main", None)]


def test_a_token_in_an_error_message_is_redacted_everywhere(conn):
    fake = FakeConnector(
        batches={"main": [Batch([rec(1)])]},
        fail_on_batch=0,
        fail_message="401 for token sk-live-123",
    )
    messages = []
    results = runner.run_sync(conn, [fake], redact_values=["sk-live-123"], now=CLOCK, log=messages.append)
    assert "sk-live-123" not in results[0].error
    assert "***" in results[0].error
    assert "sk-live-123" not in ss.list_sync_states(conn)[0]["error"]
    assert all("sk-live-123" not in message for message in messages)


def test_only_runs_the_named_connector(conn):
    first = FakeConnector(name="first", batches={"main": [Batch([rec(1, "first")])]})
    second = FakeConnector(name="second", batches={"main": [Batch([rec(2, "second")])]})
    results = runner.run_sync(conn, [first, second], only="second", now=CLOCK)
    assert [r.connector for r in results] == ["second"]
    assert first.calls == []


def test_unmapped_identities_show_up_after_a_sync(conn):
    fake = FakeConnector(batches={"main": [Batch([rec(1, assignee_account="acc-9")])]})
    runner.run_sync(conn, [fake], now=CLOCK)
    assert up.unmapped_identities(conn) == [("fake", "acc-9")]


def test_two_sources_writing_many_batches_at_once_lose_nothing(conn):
    def many(name):
        batches = [Batch([rec(f"{name}-{i}", name)], cursor=f"c{i}") for i in range(25)]
        return FakeConnector(name=name, batches={"main": batches})

    results = runner.run_sync(conn, [many("a"), many("b")], now=CLOCK)
    assert all(r.status == "ok" for r in results)
    assert len(rows(conn)) == 50
