from datetime import date

import pytest

from token_world import World
from delivery_analysis.tokens import rebuild as rebuild_module
from delivery_analysis.tokens.explain import explain, explain_lines, find_person
from delivery_analysis.tokens.rebuild import RebuildError, rebuild
from delivery_analysis.tokens.types import Allocation

TODAY = date(2026, 3, 20)


def rows(conn, person="p-ada"):
    return [
        (r["day"], r["key"], round(r["cost_usd"], 6), r["method"], r["confidence"], r["reason"])
        for r in conn.execute(
            "SELECT ta.day, w.key, ta.cost_usd, ta.method, ta.confidence, ta.reason FROM token_attribution ta "
            "LEFT JOIN work_item w ON w.source = ta.work_item_source AND w.source_id = ta.work_item_id "
            "WHERE ta.person_id = ? ORDER BY ta.day, w.key", (person,)
        )
    ]


def single(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    t1 = w.ticket("MD-1", assignee=ada, points=3).in_progress("2026-03-02")
    pr = w.pull_request(ada, created="2026-03-03", merged="2026-03-05", links=[t1])
    w.commit(ada, "2026-03-03", pr=pr)
    t1.completed("2026-03-06")
    return w, ada, t1, pr


def test_single_ticket_days_are_high_and_today_is_not_attributed(conn):
    w, ada, t1, pr = single(conn)
    w.usage(ada, "2026-03-02", 400)
    w.usage(ada, "2026-03-03", 1000)
    w.usage(ada, "2026-03-10", 600)
    w.usage(ada, "2026-03-20", 500)
    summary = rebuild(conn, TODAY, now="2026-03-20T12:00:00Z")
    assert rows(conn) == [
        ("2026-03-02", "MD-1", 4.0, "window_single", "high", None),
        ("2026-03-03", "MD-1", 10.0, "window_single", "high", None),
        ("2026-03-10", None, 6.0, "unattributed", None, "no_active_ticket"),
    ]
    assert conn.execute("SELECT COUNT(*) FROM token_usage WHERE day = '2026-03-20'").fetchone()[0] == 1
    assert summary.attributed_usd == 14.0 and summary.unattributed_usd == {"no_active_ticket": 6.0}
    assert (summary.first_day, summary.last_day) == ("2026-03-02", "2026-03-10")
    inputs = conn.execute("SELECT inputs, algo_version FROM token_attribution WHERE day = '2026-03-03'").fetchone()
    assert '"key": "MD-1"' in inputs["inputs"] and inputs["algo_version"] == "a-plus-1"


def test_two_concurrent_tickets_split_by_evidence(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    t1 = w.ticket("MD-1", assignee=ada, points=3).in_progress("2026-03-02")
    w.ticket("MD-2", assignee=ada, points=2).in_progress("2026-03-02")
    pr = w.pull_request(ada, created="2026-03-03", links=[t1])
    w.commit(ada, "2026-03-03", pr=pr)
    w.usage(ada, "2026-03-02", 400)
    w.usage(ada, "2026-03-03", 1000)
    rebuild(conn, TODAY)
    assert rows(conn) == [
        ("2026-03-02", "MD-1", 2.0, "window_evidence", "medium", None),
        ("2026-03-02", "MD-2", 2.0, "window_evidence", "medium", None),
        ("2026-03-03", "MD-1", 9.0, "window_evidence", "medium", None),
        ("2026-03-03", "MD-2", 1.0, "window_evidence", "medium", None),
    ]


def test_untracked_work_and_the_idle_cutoff(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    w.ticket("MD-1", assignee=ada).in_progress("2026-03-01")
    other = w.pull_request(ada, created="2026-03-15")
    w.commit(ada, "2026-03-15", pr=other)
    w.usage(ada, "2026-03-05", 300)
    w.usage(ada, "2026-03-12", 300)
    w.usage(ada, "2026-03-15", 300)
    rebuild(conn, TODAY)
    assert rows(conn) == [
        ("2026-03-05", "MD-1", 3.0, "window_single", "medium", None),
        ("2026-03-12", None, 3.0, "unattributed", None, "no_active_ticket"),
        ("2026-03-15", None, 3.0, "unattributed", None, "untracked_work"),
    ]


def test_epics_are_never_candidates_subtasks_are_and_dropped_tickets_keep_their_cost(conn):
    w = World(conn)
    ada, bo = w.person("Ada Example"), w.person("Bo Example")
    w.ticket("MD-9", assignee=ada, kind="Epic").in_progress("2026-03-02")
    story = w.ticket("MD-1", points=5)
    w.ticket("MD-2", assignee=bo, kind="Sub-task", parent=story).in_progress("2026-03-02")
    dropped = w.ticket("MD-3", assignee=ada).in_progress("2026-03-04")
    w.usage(ada, "2026-03-02", 200)
    w.usage(bo, "2026-03-02", 200)
    w.usage(ada, "2026-03-05", 200)
    dropped.dropped("2026-03-06")
    rebuild(conn, TODAY)
    assert rows(conn, "p-ada") == [
        ("2026-03-02", None, 2.0, "unattributed", None, "no_active_ticket"),
        ("2026-03-05", "MD-3", 2.0, "window_single", "medium", None),
    ]
    assert rows(conn, "p-bo") == [("2026-03-02", "MD-2", 2.0, "window_single", "high", None)]


def test_a_merge_ends_the_window_but_later_linked_commits_still_count(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    t1 = w.ticket("MD-1", assignee=ada).in_progress("2026-03-02")
    pr = w.pull_request(ada, created="2026-03-02", merged="2026-03-04", links=[t1])
    t1.move("Dev Done", "2026-03-05")
    w.commit(ada, "2026-03-07", pr=pr)
    w.usage(ada, "2026-03-06", 100)
    w.usage(ada, "2026-03-07", 100)
    rebuild(conn, TODAY)
    assert rows(conn) == [
        ("2026-03-06", None, 1.0, "unattributed", None, "no_active_ticket"),
        ("2026-03-07", "MD-1", 1.0, "window_single", "high", None),
    ]


def test_unmapped_and_api_key_actors_then_a_remap_moves_cost(conn):
    w, ada, t1, pr = single(conn)
    cy = w.person("Cy Example")
    w.map_api_key(ada, "ada-laptop")
    w.usage("ada-laptop", "2026-03-03", 500)
    w.usage("ghost@corp.example", "2026-03-03", 300)
    summary = rebuild(conn, TODAY)
    assert rows(conn) == [("2026-03-03", "MD-1", 5.0, "window_single", "high", None)]
    assert (summary.unmapped_actors, summary.unmapped_usd) == (1, 3.0)
    first = conn.execute("SELECT * FROM token_attribution ORDER BY person_id, day").fetchall()
    rebuild(conn, TODAY, now=None)
    again = conn.execute("SELECT * FROM token_attribution ORDER BY person_id, day").fetchall()
    assert [tuple(r)[:11] for r in first] == [tuple(r)[:11] for r in again]
    w.map_email(cy, "ghost@corp.example")
    rebuild(conn, TODAY)
    assert rows(conn, "p-cy") == [("2026-03-03", None, 3.0, "unattributed", None, "no_active_ticket")]


def test_credit_rows_and_summary_lines(conn):
    w, ada, t1, pr = single(conn)
    w.ticket("MD-5", assignee=ada).in_progress("2026-03-02").completed("2026-03-03")
    w.usage(ada, "2026-03-03", 1000)
    summary = rebuild(conn, TODAY)
    credit = conn.execute("SELECT work_item_id, person_id, share, method FROM ticket_credit ORDER BY work_item_id").fetchall()
    assert [tuple(r) for r in credit] == [(t1.id, "p-ada", 1.0, "evidence_share"), ("10002", "p-ada", 1.0, "evidence_share")]
    assert summary.tickets_without_points == 1
    text = "\n".join(summary.lines())
    assert "Claude cost: $10.00 across 1 people." in text
    assert "Completed tickets without story points: 1." in text


def test_without_jira_only_usage_is_written(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    w.usage(ada, "2026-03-03", 1000)
    summary = rebuild(conn, TODAY)
    assert summary.attribution_ran is False
    assert conn.execute("SELECT COUNT(*) FROM token_attribution").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM token_usage").fetchone()[0] == 1
    assert "Attribution skipped: no Jira issues are synced yet." in summary.lines()


def test_days_before_the_window_are_not_attributed(conn):
    w, ada, t1, pr = single(conn)
    w.usage(ada, "2025-12-19", 100)
    w.usage(ada, "2025-12-20", 100)
    rebuild(conn, TODAY, window_days=90)
    assert [r[0] for r in rows(conn)] == ["2025-12-20"]


def test_a_failed_rebuild_changes_nothing(conn, monkeypatch):
    w, ada, t1, pr = single(conn)
    w.usage(ada, "2026-03-03", 1000)
    rebuild(conn, TODAY)
    before = conn.execute("SELECT COUNT(*) FROM token_attribution").fetchone()[0]
    monkeypatch.setattr(rebuild_module, "allocate", lambda cost, cands, untracked, config: [
        Allocation(None, 0.0, None, None, "unattributed", None, "no_active_ticket")])
    with pytest.raises(RebuildError, match="does not add up"):
        rebuild(conn, TODAY)
    assert conn.execute("SELECT COUNT(*) FROM token_attribution").fetchone()[0] == before


def test_explain_shows_the_day(conn):
    w, ada, t1, pr = single(conn)
    w.usage(ada, "2026-03-03", 1000, accepted_edits=10)
    rebuild(conn, TODAY)
    assert find_person(conn, "ada example") == "p-ada" and find_person(conn, "p-ada") == "p-ada"
    with pytest.raises(LookupError):
        find_person(conn, "Nobody")
    data = explain(conn, "p-ada", "2026-03-03")
    assert [(u["purpose"], u["cost_usd"]) for u in data["usage"]] == [("ask", 5.0), ("generate", 5.0)]
    assert [(r["key"], r["confidence"]) for r in data["rows"]] == [("MD-1", "high")]
    assert data["inputs"]["candidates"][0]["key"] == "MD-1"
    text = "\n".join(explain_lines(data))
    assert "MD-1" in text and "high" in text and "window_single" in text
