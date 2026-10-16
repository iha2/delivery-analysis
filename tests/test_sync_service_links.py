from pathlib import Path

from delivery_analysis.model.records import Record
from delivery_analysis.settings import Settings
from delivery_analysis.store.upsert import upsert_record
from delivery_analysis.sync import service

NOW = "2026-10-15T12:00:00Z"
REPO = "{11111111-1111-1111-1111-111111111111}"


def seed(conn):
    upsert_record(conn, Record("work_item", {"source": "jira", "source_id": "7001", "project": "MD", "key": "MD-7"}), NOW)
    upsert_record(
        conn,
        Record("change_request", {"source": "bitbucket", "source_id": f"{REPO}#1", "repository_id": REPO,
                                  "number": "1", "author_account": "acc-ann", "title": "MD-7 export", "branch": "feature/x"}),
        NOW,
    )


def settings():
    return Settings(db_path=Path("unused.sqlite"))


def test_the_sync_service_runs_the_key_pass_and_reports_coverage_first(conn):
    seed(conn)
    results, lines, failed = service.sync_and_reconcile(conn, [], settings(), {})
    assert results == [] and failed == 0
    assert lines[0] == "Issue links: 1 of 1 pull requests have an issue key."
    assert conn.execute("SELECT COUNT(*) AS n FROM link WHERE source = 'linker'").fetchone()["n"] == 1


def test_a_source_that_does_not_feed_links_skips_the_pass(conn):
    seed(conn)
    _, lines, _ = service.sync_and_reconcile(conn, [], settings(), {}, only="fake")
    assert not any(line.startswith("Issue links") for line in lines)
    assert conn.execute("SELECT COUNT(*) AS n FROM link").fetchone()["n"] == 0


def test_a_failing_pass_is_one_redacted_line_and_never_fails_the_sync(conn, monkeypatch):
    def boom(connection, now):
        raise RuntimeError("bad query tok-XYZ")

    monkeypatch.setattr(service, "link_pull_requests", boom)
    results, lines, failed = service.sync_and_reconcile(conn, [], settings(), {"ATLASSIAN": "tok-XYZ"})
    assert lines[0] == "Issue link pass failed: bad query ***"
    assert results == [] and failed == 0
