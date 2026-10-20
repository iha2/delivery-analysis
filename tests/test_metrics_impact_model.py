from impact_seed import issue, link_pr
from metrics_seed import SEPT, TODAY, TZ, event, pr, prop, put, seed
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.impact_model import impact_shares
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
ANN = "jira:acc-ann|bitbucket:acc-ann"
BOB = "jira:acc-bob|bitbucket:acc-bob"


def pr_commit(conn, sha, account, pr_sid):
    put(conn, "vcs_commit", source="bitbucket", source_id=f"x:{sha}", repository_id="x", sha=sha,
        author_account=account, committed_at="2026-09-08T16:00:00Z", change_request_id=pr_sid)


def seed_model(conn):
    """a1 (10 pts): Ann's PR 20 with 2 commits, Bob reviews 3 times -> Ann 3 of 6, Bob 3 of 6.
    b1 (4 pts): no linked PR, Ann assigned. c1 (6 pts): Bob's PR 21, reopened once.
    d1 (2 pts): no linked PR, Cy (outside the team) assigned."""
    seed(conn)
    p20 = pr(conn, 20, "acc-ann", "MERGED", "2026-09-08T15:00:00Z", "2026-09-09T15:00:00Z")
    pr_commit(conn, "m1", "acc-ann", p20)
    pr_commit(conn, "m2", "acc-ann", p20)
    event(conn, p20, "comment", "acc-ann", "2026-09-08T16:00:00Z")  # the author's own comment is no evidence
    event(conn, p20, "comment", "acc-bob", "2026-09-08T17:00:00Z")
    event(conn, p20, "comment", "acc-bob", "2026-09-08T18:00:00Z")
    event(conn, p20, "approved", "acc-bob", "2026-09-09T10:00:00Z")
    p21 = pr(conn, 21, "acc-bob", "MERGED", "2026-09-12T10:00:00Z", "2026-09-12T20:00:00Z")
    issue(conn, "a1", "acc-qa", resolved="2026-09-10T14:00:00Z", started="2026-09-08T14:00:00Z", points=10)
    issue(conn, "b1", "acc-ann", resolved="2026-09-15T14:00:00Z", started="2026-09-14T14:00:00Z", points=4)
    issue(conn, "c1", "acc-bob", resolved="2026-09-13T14:00:00Z", started="2026-09-11T14:00:00Z", points=6)
    issue(conn, "d1", "acc-cy", resolved="2026-09-16T14:00:00Z", points=2)
    prop(conn, "work_item", "c1", "reopen_count", "1")
    prop(conn, "work_item", "a1", "reopen_count", "0")
    link_pr(conn, 20, "a1")
    link_pr(conn, 21, "c1")


def by_person(result):
    return {row["name"]: row for row in result["rows"]}


def test_points_split_by_evidence(conn):
    seed_model(conn)
    shares = impact_shares(conn, WINDOW)
    assert shares["a1"][ANN] == {"delivery": 5.0, "participation": 0.0}
    assert shares["a1"][BOB] == {"delivery": 0.0, "participation": 5.0}
    assert set(shares["a1"]) == {ANN, BOB}


def test_no_linked_pr_goes_to_the_assignee_as_delivery(conn):
    seed_model(conn)
    shares = impact_shares(conn, WINDOW)
    assert shares["b1"] == {ANN: {"delivery": 4.0, "participation": 0.0}}
    assert shares["c1"] == {BOB: {"delivery": 6.0, "participation": 0.0}}


def test_impact_is_delivery_plus_participation(conn):
    seed_model(conn)
    impact = by_person(run_metric(conn, BY_NAME["impact_points"], Scope(), WINDOW))
    delivery = by_person(run_metric(conn, BY_NAME["delivery_points"], Scope(), WINDOW))
    part = by_person(run_metric(conn, BY_NAME["participation_points"], Scope(), WINDOW))
    assert impact["Ann Example"]["value"] == 9.0 and delivery["Ann Example"]["value"] == 9.0
    assert impact["Bob Builder"]["value"] == 11.0
    assert delivery["Bob Builder"]["value"] == 6.0 and part["Bob Builder"]["value"] == 5.0
    for name in impact:
        assert impact[name]["value"] == delivery[name]["value"] + part.get(name, {"value": 0.0})["value"]


def test_team_scope_drops_non_members_and_notes_the_points(conn):
    seed_model(conn)
    result = run_metric(conn, BY_NAME["impact_points"], team_scope(conn, "t1"), WINDOW)
    assert {row["name"] for row in result["rows"]} == {"Ann Example", "Bob Builder"}
    assert result["team"]["value"] == 20.0
    assert any("2" in note and "outside" in note for note in result["notes"])
    plain = run_metric(conn, BY_NAME["impact_points"], Scope(), WINDOW)
    assert not any("outside" in note for note in plain["notes"])


def test_durability_counts_reopened_issues_against_delivery(conn):
    seed_model(conn)
    rows = by_person(run_metric(conn, BY_NAME["durability"], Scope(), WINDOW))
    assert rows["Ann Example"]["value"] == 1.0
    assert rows["Bob Builder"]["value"] == 0.0 and rows["Bob Builder"]["denominator"] == 6.0


def test_delivery_speed_and_review_responsiveness(conn):
    seed_model(conn)
    speed = by_person(run_metric(conn, BY_NAME["delivery_speed"], Scope(), WINDOW))
    assert speed["Ann Example"]["value"] == 25.0  # a1: started 09-08 14:00, merged 09-09 15:00 (b1 has no PR)
    assert speed["Bob Builder"]["value"] == 30.0  # c1: started 09-11 14:00, merged 09-12 20:00
    resp = by_person(run_metric(conn, BY_NAME["review_responsiveness"], Scope(), WINDOW))
    assert resp["Bob Builder"]["value"] == 2.0  # PR 20 opened 15:00, first review 17:00


def test_impact_per_dollar_waits_without_claude_data(conn):
    seed_model(conn)
    result = run_metric(conn, BY_NAME["impact_per_dollar"], Scope(), WINDOW)
    assert result["status"] == "waiting" and result["missing"] == ["claude_usage"]


def test_groups(conn):
    assert BY_NAME["impact_points"].group == "impact" and BY_NAME["prs_merged"].group == "activity"
    assert BY_NAME["review_follow_through"].group == "participation"
