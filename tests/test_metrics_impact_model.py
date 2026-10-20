import json

import pytest

from impact_seed import issue, link_pr
from metrics_seed import NOW, REPO, SEPT, TODAY, TZ, event, pr, prop, put, seed
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.impact_build import rebuild_impact
from delivery_analysis.metrics.impact_model import impact_shares
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
ANN = "jira:acc-ann|bitbucket:acc-ann"
BOB = "jira:acc-bob|bitbucket:acc-bob"


def pr_commit(conn, sha, account, pr_sid, when="2026-09-08T16:00:00Z", hunks=((1, 2),)):
    put(conn, "vcs_commit", source="bitbucket", source_id=f"{REPO}:{sha}", repository_id=REPO, sha=sha,
        author_account=account, committed_at=when, change_request_id=pr_sid)
    put(conn, "commit_file", repository_id=REPO, sha=sha, path="f.py", lines_added=1, lines_removed=0,
        hunks=json.dumps([list(h) for h in hunks]))


def seed_model(conn):
    """a1 (10 pts): Ann's PR 20 changes f.py; Bob's inline comment on line 5 is fixed by a later commit
    (r = 1: Ann 10 - 0.05 delivered, Bob 0.5 participation); Bob also comments twice and approves once.
    b1 (4 pts): no linked PR, Ann assigned. c1 (6 pts): Bob's PR 21 (no file data), reopened once.
    d1 (2 pts): no linked PR, Cy (outside the team) assigned."""
    seed(conn)
    put(conn, "code_file", repository_id=REPO, path="f.py", weight=1.0, snapshot_sha="s", built_at=NOW)
    p20 = pr(conn, 20, "acc-ann", "MERGED", "2026-09-08T15:00:00Z", "2026-09-09T15:00:00Z")
    pr_commit(conn, "m1", "acc-ann", p20)
    pr_commit(conn, "m2", "acc-ann", p20)
    put(conn, "review_comment", source="bitbucket", source_id=f"{p20}:comment:1", change_request_id=p20,
        actor_account="acc-bob", created_at="2026-09-08T17:00:00Z", path="f.py", line=5, resolved=0)
    pr_commit(conn, "m3", "acc-ann", p20, when="2026-09-08T18:30:00Z", hunks=((3, 6),))
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
    rebuild_impact(conn, NOW)


def by_person(result):
    return {row["name"]: row for row in result["rows"]}


def test_points_follow_the_stored_impact_shares(conn):
    seed_model(conn)
    shares = impact_shares(conn, WINDOW)
    assert shares["a1"][ANN] == pytest.approx({"delivery": 9.95, "participation": 0.0})
    assert shares["a1"][BOB] == pytest.approx({"delivery": 0.0, "participation": 0.5})
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
    assert impact["Ann Example"]["value"] == pytest.approx(13.95) and delivery["Ann Example"]["value"] == pytest.approx(13.95)
    assert impact["Bob Builder"]["value"] == pytest.approx(6.5)
    assert delivery["Bob Builder"]["value"] == 6.0 and part["Bob Builder"]["value"] == pytest.approx(0.5)
    for name in impact:
        assert impact[name]["value"] == delivery[name]["value"] + part.get(name, {"value": 0.0})["value"]


def test_team_scope_drops_non_members_and_notes_the_points(conn):
    seed_model(conn)
    result = run_metric(conn, BY_NAME["impact_points"], team_scope(conn, "t1"), WINDOW)
    assert {row["name"] for row in result["rows"]} == {"Ann Example", "Bob Builder"}
    assert result["team"]["value"] == pytest.approx(20.45)
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
    assert BY_NAME["review_follow_through"].group == "activity"
    assert BY_NAME["prs_reviewed"].group == "participation" and BY_NAME["review_value"].group == "participation"


def test_shares_outside_the_window_are_not_read(conn):
    seed_model(conn)
    conn.execute("UPDATE impact_share SET resolved_at = '2026-08-10T14:00:00Z' WHERE issue_id = 'a1'")
    assert "a1" not in impact_shares(conn, WINDOW) and "b1" in impact_shares(conn, WINDOW)


def test_prs_reviewed_counts_distinct_prs_and_review_value_weighs_approvals(conn):
    seed_model(conn)
    p21 = "{11111111-1111-1111-1111-111111111111}#21"
    event(conn, p21, "comment", "acc-ann", "2026-09-12T11:00:00Z")
    event(conn, p21, "approved", "acc-ann", "2026-09-12T12:00:00Z")
    event(conn, p21, "comment", "acc-bob", "2026-09-12T13:00:00Z")  # the owner's own comment
    event(conn, p21, "approved", "acc-cy", "2026-09-12T14:00:00Z")  # an approval alone is not a reviewed PR
    event(conn, "{11111111-1111-1111-1111-111111111111}#20", "comment", "acc-bob", "2026-08-01T11:00:00Z")
    reviewed = by_person(run_metric(conn, BY_NAME["prs_reviewed"], Scope(), WINDOW))
    value = by_person(run_metric(conn, BY_NAME["review_value"], Scope(), WINDOW))
    assert reviewed["Bob Builder"]["value"] == 2.0 and reviewed["Ann Example"]["value"] == 1.0
    assert value["Bob Builder"]["value"] == 4.0  # PR 20: 2.5 (August comment left out), seed PR 1: 1.5
    assert value["Ann Example"]["value"] == 1.5
    assert "Cy Inactive" not in reviewed


def test_a_second_linked_account_of_the_author_earns_no_review_credit(conn):
    seed_model(conn)
    conn.execute("INSERT INTO identity (source, account_id, person_id, manual) VALUES ('bitbucket', 'acc-ann2', 'p-ann', 0)")
    p20 = "{11111111-1111-1111-1111-111111111111}#20"
    event(conn, p20, "comment", "acc-ann2", "2026-09-08T19:00:00Z")
    event(conn, p20, "approved", "acc-ann2", "2026-09-09T11:00:00Z")
    reviewed = by_person(run_metric(conn, BY_NAME["prs_reviewed"], Scope(), WINDOW))
    value = by_person(run_metric(conn, BY_NAME["review_value"], Scope(), WINDOW))
    assert "Ann Example" not in reviewed or reviewed["Ann Example"]["value"] == 0.0
    assert "Ann Example" not in value or value["Ann Example"]["value"] == 0.0
