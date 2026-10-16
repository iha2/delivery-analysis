import pytest

from impact_seed import issue, link_pr, seed_impact
from metrics_seed import SEPT, TODAY, TZ, pr
from delivery_analysis.metrics import credit as cr
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)


def key(account):
    return f"jira:{account}|bitbucket:{account}"


def test_shares_follow_the_authors_of_linked_pull_requests_and_fall_back_to_the_assignee(conn):
    seed_impact(conn)
    credit = cr.credit_for(conn, WINDOW)
    assert credit.shares["1"] == {key("acc-ann"): 1.0}
    assert credit.shares["2"] == {key("acc-ann"): 1.0}
    assert credit.shares["3"] == {key("acc-ann"): 0.5, key("acc-bob"): 0.5}  # QA owns it, the authors are credited
    assert credit.shares["6"] == {key("acc-zed"): 1.0}
    assert credit.shares["9"] == {}
    assert credit.by_pr == {"1", "3"}
    assert [row["key"] for row in credit.issues] == ["MD-1", "MD-6", "MD-7", "MD-9", "MD-2", "MD-3"]
    assert all(abs(sum(shares.values()) - 1.0) < 1e-9 for shares in credit.shares.values() if shares)


def test_shares_split_by_each_authors_count_of_distinct_pull_requests(conn):
    seed_impact(conn)
    for number, author in ((8, "acc-bob"), (9, "acc-bob"), (10, "acc-ann")):
        pr(conn, number, author, "MERGED", "2026-09-22T14:00:00Z", "2026-09-23T14:00:00Z")
        link_pr(conn, number, "11")
    issue(conn, "11", "acc-qa", resolved="2026-09-25T14:00:00Z", points=6)
    shares = cr.credit_for(conn, WINDOW).shares["11"]
    assert shares[key("acc-bob")] == pytest.approx(2 / 3) and shares[key("acc-ann")] == pytest.approx(1 / 3)


def test_a_linked_pull_request_without_an_author_is_ignored_and_the_assignee_is_credited(conn):
    seed_impact(conn)
    pr(conn, 11, None, "MERGED", "2026-09-22T14:00:00Z", "2026-09-23T14:00:00Z")
    link_pr(conn, 11, "12")
    issue(conn, "12", "acc-ann", resolved="2026-09-25T14:00:00Z", points=1)
    credit = cr.credit_for(conn, WINDOW)
    assert credit.shares["12"] == {key("acc-ann"): 1.0} and "12" not in credit.by_pr


def test_only_issues_completed_in_the_window_are_credited(conn):
    seed_impact(conn)
    assert "8" not in cr.credit_for(conn, WINDOW).shares  # August
    assert "4" not in cr.credit_for(conn, WINDOW).shares  # Epic
    assert "5" not in cr.credit_for(conn, WINDOW).shares  # dropped


def test_first_merges_are_the_earliest_merged_linked_pull_request(conn):
    seed_impact(conn)
    assert cr.first_merges(conn) == {"1": "2026-09-12T14:00:00Z", "3": "2026-09-20T14:00:00Z"}


def test_the_credit_note_counts_issues_by_evidence_and_by_assignee(conn):
    seed_impact(conn)
    assert cr.credit_note(cr.credit_for(conn, WINDOW)) == (
        "2 of 5 completed issue(s) were credited to the authors of their linked pull requests; "
        "3 to the assignee because no pull request is linked."
    )
    conn.execute("DELETE FROM link WHERE source = 'linker'")
    assert cr.credit_note(cr.credit_for(conn, WINDOW)) is None  # no evidence used: nothing to explain


def test_under_a_team_scoped_keeps_only_members_and_counts_the_rest_as_outside(conn):
    seed_impact(conn)
    scoped = cr.scoped(conn, team_scope(conn, "t1"), cr.credit_for(conn, WINDOW))
    assert sorted(row["key"] for row, _ in scoped.items) == ["MD-1", "MD-2", "MD-3"]
    assert [row["key"] for row in scoped.unassigned] == ["MD-9"]
    assert scoped.outside == 2  # zed is unmapped and Cy is not a member: neither is the team's


def test_without_a_team_unmapped_people_stay_and_only_nobody_is_left_out(conn):
    seed_impact(conn)
    scoped = cr.scoped(conn, Scope(), cr.credit_for(conn, WINDOW))
    assert sorted(row["key"] for row, _ in scoped.items) == ["MD-1", "MD-2", "MD-3", "MD-6", "MD-7"]
    assert [row["key"] for row in scoped.unassigned] == ["MD-9"] and scoped.outside == 0


def test_an_issue_shared_with_someone_outside_the_team_keeps_only_the_members_share(conn):
    seed_impact(conn)
    pr(conn, 8, "acc-ann", "MERGED", "2026-09-22T14:00:00Z", "2026-09-23T14:00:00Z")
    pr(conn, 9, "acc-cy", "MERGED", "2026-09-22T14:00:00Z", "2026-09-23T14:00:00Z")
    link_pr(conn, 8, "13")
    link_pr(conn, 9, "13")
    issue(conn, "13", "acc-qa", resolved="2026-09-26T14:00:00Z", points=4)
    scoped = cr.scoped(conn, team_scope(conn, "t1"), cr.credit_for(conn, WINDOW))
    fractions = {row["key"]: fraction for row, fraction in scoped.items}
    assert fractions["MD-13"] == pytest.approx(0.5) and fractions["MD-1"] == pytest.approx(1.0)


def test_an_issue_credited_only_to_an_excluded_account_is_left_out_and_counted_as_outside(conn):
    seed_impact(conn)
    pr(conn, 8, "acc-dee", "MERGED", "2026-09-22T14:00:00Z", "2026-09-23T14:00:00Z")
    link_pr(conn, 8, "14")
    issue(conn, "14", "acc-ann", resolved="2026-09-26T14:00:00Z", points=4)
    scoped = cr.scoped(conn, team_scope(conn, "t1"), cr.credit_for(conn, WINDOW))
    assert "MD-14" not in [row["key"] for row, _ in scoped.items] and scoped.outside == 3
