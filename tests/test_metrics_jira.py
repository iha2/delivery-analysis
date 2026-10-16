import pytest

from metrics_seed import SEPT, TODAY, TZ, prop, put, seed
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
OUTSIDE = "{n} completed issue(s) belong to someone outside this team and are not counted."
NO_DATE = "{n} done issue(s) have no resolved date and are not counted."


def item(conn, sid, assignee, category="done", resolved=None, started=None, points=None, kind="Story", counts="1"):
    put(
        conn, "work_item", source="jira", source_id=sid, project="MD", key=f"MD-{sid}", type=kind,
        assignee_account=assignee, status="COMPLETED" if category == "done" else "Other",
        status_category=category, started_at=started, resolved_at=resolved, story_points=points,
    )
    prop(conn, "work_item", sid, "counts_for_impact", counts)


@pytest.fixture
def seeded(conn):
    seed(conn)
    item(conn, "1", "acc-ann", resolved="2026-09-10T14:00:00Z", started="2026-09-08T14:00:00Z", points=5)
    item(conn, "2", "acc-ann", resolved="2026-09-20T14:00:00Z")  # never started, no points
    item(conn, "3", "acc-bob", resolved="2026-09-21T02:00:00Z", started="2026-09-19T02:00:00Z", points=3)
    item(conn, "4", "acc-ann", resolved="2026-09-12T14:00:00Z", started="2026-09-01T14:00:00Z", points=13, kind="Epic", counts="0")
    item(conn, "5", "acc-ann", category="dropped", resolved="2026-09-12T14:00:00Z", points=8)  # DISREGARD
    item(conn, "6", "acc-zed", resolved="2026-09-15T14:00:00Z", started="2026-09-14T14:00:00Z", points=8)  # unmapped person
    item(conn, "7", "acc-cy", resolved="2026-09-16T14:00:00Z", started="2026-09-15T14:00:00Z", points=2)  # inactive member
    item(conn, "8", "acc-ann", resolved="2026-08-10T14:00:00Z", started="2026-08-09T14:00:00Z", points=2)  # last window
    item(conn, "9", None, resolved="2026-09-18T14:00:00Z", started="2026-09-17T14:00:00Z", points=1)  # no assignee
    return conn


def run(conn, name, scope):
    return run_metric(conn, BY_NAME[name], scope, WINDOW)


def table(result):
    return [(row["name"], row["value"], row["sample"]) for row in result["rows"]]


def test_issues_done_counts_done_countable_items_by_resolved_date_for_team_members(seeded):
    result = run(seeded, "issues_done", team_scope(seeded, "t1"))
    assert result["status"] == "ok"
    assert table(result) == [("Ann Example", 2.0, 2), ("Bob Builder", 1.0, 1)]
    assert result["notes"] == [OUTSIDE.format(n=2)]
    assert result["team"]["value"] == 3.0


def test_without_a_team_the_unassigned_note_counts_every_unassigned_issue(seeded):
    result = run(seeded, "issues_done", Scope())
    assert result["notes"] == ["1 completed issue(s) have no assignee and are not attributed to anyone."]


def test_team_per_person_sum_equals_the_weekly_total(seeded):
    scope = team_scope(seeded, "t1")
    people = run(seeded, "issues_done", scope)
    weekly = run(seeded, "issues_done_weekly", scope)
    assert sum(row["value"] for row in people["rows"]) == sum(row["value"] for row in weekly["rows"]) == 3


def test_done_issues_without_a_resolved_date_are_noted(seeded):
    item(seeded, "10", "acc-ann", started="2026-09-01T14:00:00Z", points=2)  # done, never resolved
    item(seeded, "11", "acc-zed", points=2)  # same, but outside the team
    for name in ("issues_done", "story_points_done"):
        assert NO_DATE.format(n=1) in run(seeded, name, team_scope(seeded, "t1"))["notes"]
        assert NO_DATE.format(n=2) in run(seeded, name, Scope())["notes"]


def test_without_a_team_other_people_count_and_dropped_and_epics_never_do(seeded):
    result = run(seeded, "issues_done", Scope())
    assert table(result) == [
        ("Ann Example", 2.0, 2), ("Bob Builder", 1.0, 1), ("Cy Inactive", 1.0, 1), ("Unmapped (1 account)", 1.0, 1)
    ]


def test_a_jira_assignee_resolves_through_the_bitbucket_account(seeded):
    # acc-ann exists only as a bitbucket identity in the seed; the Jira item still lands on Ann.
    assert ("Ann Example", 2.0, 2) in table(run(seeded, "issues_done", team_scope(seeded, "t1")))


def test_cycle_time_is_first_in_progress_to_the_last_completion_and_notes_missing_starts(seeded):
    result = run(seeded, "cycle_time", team_scope(seeded, "t1"))
    assert table(result) == [("Ann Example", 48.0, 1), ("Bob Builder", 48.0, 1)]
    assert result["notes"] == [
        "1 completed issue(s) never entered In Progress, so they have no cycle time.",
        OUTSIDE.format(n=2),
    ]


def test_story_points_done_sums_points_and_counts_the_unpointed(seeded):
    result = run(seeded, "story_points_done", team_scope(seeded, "t1"))
    assert table(result) == [("Ann Example", 5.0, 1), ("Bob Builder", 3.0, 1)]
    assert result["notes"] == [
        "1 completed issue(s) have no story points and are not counted.",
        OUTSIDE.format(n=2),
    ]


def test_the_weekly_series_uses_local_weeks_and_team_members_only(seeded):
    team = run(seeded, "issues_done_weekly", team_scope(seeded, "t1"))
    assert team["rows"] == [
        {"week": "2026-08-31", "value": 0}, {"week": "2026-09-07", "value": 1}, {"week": "2026-09-14", "value": 2},
        {"week": "2026-09-21", "value": 0}, {"week": "2026-09-28", "value": 0},
    ]
    everyone = run(seeded, "issues_done_weekly", Scope())
    assert [row["value"] for row in everyone["rows"]] == [0, 1, 5, 0, 0]


def test_the_catalog_wires_the_four_jira_metrics_and_they_wait_without_jira_data(conn):
    for name in ("issues_done", "issues_done_weekly", "cycle_time", "story_points_done"):
        assert BY_NAME[name].compute is not None
    empty = run_metric(conn, BY_NAME["issues_done"], Scope(), WINDOW)
    assert empty["status"] == "waiting" and empty["missing"] == ["jira"]
