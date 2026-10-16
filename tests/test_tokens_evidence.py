from datetime import date

from token_world import World
from delivery_analysis.tokens.accounts import AccountMap
from delivery_analysis.tokens.evidence import load_evidence
from delivery_analysis.tokens.tickets import load_tickets


def d(day):
    return date(2026, 3, day)


def build(conn):
    w = World(conn)
    ada, bo = w.person("Ada Example"), w.person("Bo Example")
    t1 = w.ticket("MD-1", assignee=ada, points=3).in_progress("2026-03-02").completed("2026-03-06")
    epic = w.ticket("MD-9", kind="Epic")
    pr1 = w.pull_request(ada, created="2026-03-03", merged="2026-03-05", links=[t1])
    w.commit(ada, "2026-03-03", pr=pr1)
    w.commit(ada, "2026-03-04", pr=pr1, merge=True)
    w.commit(ada, "2026-03-04", pr=pr1, email_only=True)
    w.event(pr1, bo, "comment", "2026-03-04")
    w.event(pr1, bo, "merged", "2026-03-05")
    w.event(pr1, ada, "update", "2026-03-04")
    pr2 = w.pull_request(ada, created="2026-03-05")
    w.commit(ada, "2026-03-05", pr=pr2)
    return w, ada, bo, t1, epic


def test_tickets_carry_categories_merges_and_assignees(conn):
    w, ada, bo, t1, epic = build(conn)
    tickets = load_tickets(conn, AccountMap(conn))
    info = tickets[t1.key]
    assert info.transitions == [("2026-03-02T10:00:00Z", "in_progress"), ("2026-03-06T10:00:00Z", "done")]
    assert info.merges == ["2026-03-05T15:00:00Z"]
    assert (info.issue_key, info.assignee_person, info.eligible, info.counts_for_impact, info.story_points) == (
        "MD-1", "p-ada", True, True, 3.0)
    assert tickets[epic.key].eligible is False and tickets[epic.key].counts_for_impact is False


def test_evidence_per_person_ticket_and_day(conn):
    w, ada, bo, t1, epic = build(conn)
    accounts = AccountMap(conn)
    index = load_evidence(conn, accounts, load_tickets(conn, accounts))
    assert index.for_person("p-ada")[t1.key] == {d(2): 1.0, d(3): 2.0, d(4): 2.0, d(6): 1.0}
    assert index.for_person("p-bo")[t1.key] == {d(4): 1.0}
    assert index.untracked == {("p-ada", d(5))}
    assert index.totals() == {(t1.key, "p-ada"): 6.0, (t1.key, "p-bo"): 1.0}


def test_a_commit_linked_directly_to_a_ticket_counts(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    t1 = w.ticket("MD-1", assignee=ada)
    w.commit(ada, "2026-03-07", links=[t1])
    accounts = AccountMap(conn)
    index = load_evidence(conn, accounts, load_tickets(conn, accounts))
    assert index.for_person("p-ada") == {t1.key: {d(7): 1.0}} and index.untracked == set()
