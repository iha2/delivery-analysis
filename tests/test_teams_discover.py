import pytest

from delivery_analysis.teams.discover import discover_people, window_start

REPOS = [("bitbucket", "r1")]
SINCE = "2026-07-17T00:00:00Z"


def test_window_start_subtracts_whole_days():
    assert window_start("2026-10-15T00:00:00Z", 90) == SINCE
    with pytest.raises(ValueError):
        window_start("not a time", 90)


def test_groups_commits_by_email_inside_the_window(conn, add_commit):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    add_commit("ann@corp.example", "Ann Example", "2026-09-10")
    add_commit("ann@corp.example", "A. Example", "2026-09-11", account="{acc-1}")
    add_commit("old@corp.example", "Old Timer", "2026-01-01")
    result = discover_people(conn, REPOS, SINCE)
    assert [activity.email for activity in result] == ["ann@corp.example"]
    ann = result[0]
    assert ann.commits == 3
    assert ann.last_commit == "2026-09-11T12:00:00Z"
    assert ann.names == {"Ann Example": 2, "A. Example": 1}
    assert ann.account_ids == (("bitbucket", "{acc-1}"),)


def test_only_the_selected_repositories_count(conn, add_commit):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01", repo="r1")
    add_commit("bob@corp.example", "Bob Builder", "2026-09-01", repo="r2")
    add_commit("cy@corp.example", "Cy Source", "2026-09-01", repo="r1", source="github")
    assert [a.email for a in discover_people(conn, REPOS, SINCE)] == ["ann@corp.example"]
    both = discover_people(conn, [("bitbucket", "r1"), ("bitbucket", "r2")], SINCE)
    assert [a.email for a in both] == ["ann@corp.example", "bob@corp.example"]


def test_emails_are_trimmed_and_lower_cased(conn, add_commit):
    add_commit("  Ann@Corp.Example ", "Ann Example", "2026-09-01")
    add_commit("ann@corp.example", "Ann Example", "2026-09-02")
    result = discover_people(conn, REPOS, SINCE)
    assert [(a.email, a.commits) for a in result] == [("ann@corp.example", 2)]


def test_commits_without_an_author_email_are_skipped(conn, add_commit):
    add_commit(None, "No Email", "2026-09-01")
    add_commit("   ", "Blank Email", "2026-09-02")
    add_commit("ann@corp.example", None, "2026-09-03")
    result = discover_people(conn, REPOS, SINCE)
    assert [(a.email, a.names) for a in result] == [("ann@corp.example", {})]


def test_no_repositories_means_nobody(conn, add_commit):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    assert discover_people(conn, [], SINCE) == []
