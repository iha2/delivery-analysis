import pytest

from metrics_seed import SEPT, TODAY, TZ, seed
from delivery_analysis.metrics.people import team_scope
from delivery_analysis.metrics.person import person_detail
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)


def test_person_detail_lists_work_reviews_pending_and_weekly_commits(conn):
    seed(conn)
    ann = person_detail(conn, "p-ann", WINDOW, team_scope(conn, "t1"))
    assert ann["person"] == {"person_id": "p-ann", "name": "Ann Example", "excluded": False,
                             "accounts": ["acc-ann"], "emails": ["ann@corp.example"]}
    assert [pr["number"] for pr in ann["pull_requests"]] == ["3", "2", "1"]
    assert ann["pull_requests"][0]["repository"] == "core-repo"
    assert [(r["number"], r["created_at"]) for r in ann["reviews_pending"]] == [("4", "2026-09-25T14:00:00Z")]
    assert ann["commits_weekly"][0] == {"week": "2026-08-31", "value": 2}
    bob = person_detail(conn, "p-bob", WINDOW, team_scope(conn, "t1"))
    assert sorted(r["type"] for r in bob["reviews_given"]) == ["approved", "comment"]


def test_person_detail_without_a_team_includes_other_repositories(conn):
    seed(conn)
    numbers = [pr["number"] for pr in person_detail(conn, "p-ann", WINDOW)["pull_requests"]]
    assert "6" in numbers


def test_an_unknown_person_is_a_lookup_error(conn):
    with pytest.raises(LookupError):
        person_detail(conn, "nobody", WINDOW)


from impact_seed import issue, seed_impact  # noqa: E402


def test_person_detail_lists_credited_issues_with_their_share_and_basis(conn):
    seed_impact(conn)
    ann = person_detail(conn, "p-ann", WINDOW, team_scope(conn, "t1"))
    assert ann["issues_done"] == [
        {"key": "MD-3", "type": "Story", "points": 3.0, "resolved_at": "2026-09-21T02:00:00Z",
         "share": 0.5, "basis": "pull request"},
        {"key": "MD-2", "type": "Bug", "points": None, "resolved_at": "2026-09-20T14:00:00Z",
         "share": 1.0, "basis": "assignee"},
        {"key": "MD-1", "type": "Story", "points": 5.0, "resolved_at": "2026-09-10T14:00:00Z",
         "share": 1.0, "basis": "pull request"},
    ]
    bob = person_detail(conn, "p-bob", WINDOW, team_scope(conn, "t1"))
    assert [(row["key"], row["share"]) for row in bob["issues_done"]] == [("MD-3", 0.5)]


def test_the_completed_issue_list_skips_epics_dropped_items_and_other_windows(conn):
    seed_impact(conn)
    keys = [row["key"] for row in person_detail(conn, "p-ann", WINDOW)["issues_done"]]
    assert "MD-4" not in keys and "MD-5" not in keys and "MD-8" not in keys


def test_a_jira_identity_mapped_to_the_person_counts_as_their_account(conn):
    seed_impact(conn)
    conn.execute("INSERT INTO identity (source, account_id, person_id, manual) VALUES ('jira', 'jira-only', 'p-bob', 0)")
    issue(conn, "20", "jira-only", resolved="2026-09-22T14:00:00Z", points=1)
    assert [row["key"] for row in person_detail(conn, "p-bob", WINDOW)["issues_done"]] == ["MD-20", "MD-3"]


def test_without_jira_data_the_person_has_no_issues_key(conn):
    seed(conn)
    assert "issues_done" not in person_detail(conn, "p-ann", WINDOW)
