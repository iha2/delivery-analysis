import pytest

from impact_seed import issue, seed_impact
from metrics_seed import SEPT, TODAY, TZ
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
WEEKS = ["2026-08-31", "2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"]
POINTS_NOTE = "1 completed issue(s) have no story points and are not counted."
START_NOTE = "1 completed issue(s) never entered In Progress, so they have no cycle time."
CREDIT = ("2 of 5 completed issue(s) were credited to the authors of their linked pull requests; "
          "3 to the assignee because no pull request is linked.")
UNASSIGNED = "1 completed issue(s) have no assignee and are not attributed to anyone."
OUTSIDE = "2 completed issue(s) belong to someone outside this team and are not counted."
NO_DATE = "1 done issue(s) have no resolved date and are not counted."
NO_KEY = "{n} merged pull request(s) have no issue key in the title or branch."


@pytest.fixture
def seeded(conn):
    seed_impact(conn)
    return conn


def run(conn, name, team=True):
    scope = team_scope(conn, "t1") if team else Scope()
    return run_metric(conn, BY_NAME[name], scope, WINDOW)


def table(result):
    return [(row["name"], row["value"], row["sample"]) for row in result["rows"]]


def points_rows(values):
    return [{"week": w, "value": v, "issues": i, "unpointed": u} for w, (v, i, u) in zip(WEEKS, values)]


def test_story_points_weekly_credits_pull_request_authors_not_the_qa_assignee(seeded):
    result = run(seeded, "story_points_weekly")
    assert result["status"] == "ok" and result["unit"] == "points" and result["kind"] == "team_series"
    assert result["rows"] == points_rows([(0, 0, 0), (5, 1, 0), (3, 2, 1), (0, 0, 0), (0, 0, 0)])
    assert result["notes"] == [POINTS_NOTE, CREDIT, OUTSIDE]  # zed (unmapped) and Cy are not the team's


def test_story_points_weekly_without_a_team_counts_everyone_credited(seeded):
    result = run(seeded, "story_points_weekly", team=False)
    assert result["rows"] == points_rows([(0, 0, 0), (5, 1, 0), (13, 4, 1), (0, 0, 0), (0, 0, 0)])
    assert result["notes"] == [POINTS_NOTE, CREDIT, UNASSIGNED]


def test_per_person_points_split_by_share_and_agree_with_the_weekly_total(seeded):
    per_person = run(seeded, "story_points_done")
    assert table(per_person) == [("Ann Example", 6.5, 2), ("Bob Builder", 1.5, 1)]
    # issue 3 (3 points) is split between its two authors; its QA assignee is not credited
    assert per_person["notes"] == [POINTS_NOTE, OUTSIDE, CREDIT]
    weekly = run(seeded, "story_points_weekly")
    assert sum(row["value"] for row in weekly["rows"]) == per_person["team"]["value"] == 8.0


def test_without_a_team_unmapped_people_and_the_inactive_are_counted_too(seeded):
    result = run(seeded, "story_points_done", team=False)
    assert table(result) == [
        ("Ann Example", 6.5, 2), ("Bob Builder", 1.5, 1), ("Cy Inactive", 2.0, 1), ("Unmapped (1 account)", 8.0, 1)
    ]
    assert result["notes"] == [POINTS_NOTE, UNASSIGNED, CREDIT]


def test_issues_done_counts_the_issue_once_for_each_credited_author(seeded):
    result = run(seeded, "issues_done")
    assert table(result) == [("Ann Example", 3.0, 3), ("Bob Builder", 1.0, 1)]
    assert result["notes"] == [OUTSIDE, CREDIT]
    assert result["team"]["value"] == 4.0  # issue 3 has two authors and counts once for each


def test_cycle_time_per_person_stays_by_assignee(seeded):
    result = run(seeded, "cycle_time")
    assert [row["name"] for row in result["rows"]] == ["Ann Example", "Bob Builder"]
    assert [row["sample"] for row in result["rows"]] == [1, 0]  # issue 3 is QA's: by assignee it is not Bob's


def test_dropped_epic_and_previous_window_issues_never_count(seeded):
    total = sum(row["value"] for row in run(seeded, "story_points_weekly", team=False)["rows"])
    assert total == 18.0  # 5 + 3 + 8 + 2; not 13 (Epic), 8 (dropped) or 2 (August)


def test_points_by_type_sums_credited_points_and_counts_pointed_issues(seeded):
    team = run(seeded, "points_by_type")
    assert team["kind"] == "team_breakdown"
    assert team["rows"] == [{"part": "Story", "value": 8.0, "count": 2}]
    assert team["notes"] == [POINTS_NOTE, CREDIT, OUTSIDE]
    everyone = run(seeded, "points_by_type", team=False)
    assert everyone["rows"] == [{"part": "Story", "value": 10.0, "count": 3}, {"part": "Task", "value": 8.0, "count": 1}]


def test_an_issue_resolved_after_midnight_utc_lands_in_the_previous_local_day_and_week(seeded):
    # Issue 3 is resolved 2026-09-21T02:00Z = Sunday 09-20 22:00 in New York: the week of 09-14, not 09-21.
    rows = run(seeded, "story_points_weekly")["rows"]
    assert rows[3] == {"week": "2026-09-21", "value": 0, "issues": 0, "unpointed": 0}
    assert rows[2]["value"] == 3


def cycle_row(week, median, p85, count, pr_median, pr_p85, pr_count):
    return {"week": week, "median": median, "p85": p85, "count": count,
            "pr_median": pr_median, "pr_p85": pr_p85, "pr_count": pr_count}


def test_cycle_time_weekly_is_by_issue_with_a_second_measure_to_the_first_merged_pull_request(seeded):
    result = run(seeded, "cycle_time_weekly")
    assert result["unit"] == "hours" and result["kind"] == "team_series"
    assert result["rows"] == [
        cycle_row("2026-08-31", None, None, 0, None, None, 0),
        cycle_row("2026-09-07", 48.0, 48.0, 1, 96.0, 96.0, 1),   # issue 1: 48 h to COMPLETED, 96 h to PR 2's merge
        cycle_row("2026-09-14", 48.0, 48.0, 1, 36.0, 36.0, 1),   # issue 3: 48 h to COMPLETED, 36 h to PR 7's merge
        cycle_row("2026-09-21", None, None, 0, None, None, 0),
        cycle_row("2026-09-28", None, None, 0, None, None, 0),
    ]
    no_pr = "1 completed issue(s) have no merged linked pull request after they started, so they have no time to first PR merge."
    assert result["notes"] == [START_NOTE, OUTSIDE]  # issues 1 and 3 both have a merged pull request
    everyone = run(seeded, "cycle_time_weekly", team=False)
    assert everyone["rows"][2] == cycle_row("2026-09-14", 24.0, 37.2, 4, 36.0, 36.0, 1)
    assert everyone["notes"] == [START_NOTE, no_pr.replace("1 completed", "3 completed")]  # issues 6, 7 and 9


def test_cycle_time_summary_is_the_team_level_figure_by_issue(seeded):
    result = run(seeded, "cycle_time_summary")
    assert result["kind"] == "team_breakdown"
    assert result["rows"] == [
        {"part": "In Progress to COMPLETED", "median": 48.0, "p85": 48.0, "count": 2},
        {"part": "In Progress to first PR merge", "median": 66.0, "p85": 87.0, "count": 2},
    ]
    everyone = run(seeded, "cycle_time_summary", team=False)
    assert everyone["rows"][0] == {"part": "In Progress to COMPLETED", "median": 24.0, "p85": 48.0, "count": 5}


def test_issues_done_weekly_counts_each_issue_once_by_credit(seeded):
    team = run(seeded, "issues_done_weekly")
    assert [row["value"] for row in team["rows"]] == [0, 1, 2, 0, 0]  # issues 1, 2 and 3: zed and Cy are not the team's
    everyone = run(seeded, "issues_done_weekly", team=False)
    assert [row["value"] for row in everyone["rows"]] == [0, 1, 5, 0, 0]


def test_prs_linked_weekly_counts_only_key_pass_links_for_merged_pull_requests(seeded):
    team = run(seeded, "prs_linked_weekly")
    assert team["kind"] == "team_series" and team["needs"] == ["bitbucket", "links"]
    assert team["rows"] == [
        {"week": "2026-08-31", "linked": 0, "unlinked": 1},
        {"week": "2026-09-07", "linked": 1, "unlinked": 0},
        {"week": "2026-09-14", "linked": 2, "unlinked": 0},
        {"week": "2026-09-21", "linked": 0, "unlinked": 0},
        {"week": "2026-09-28", "linked": 0, "unlinked": 0},
    ]
    assert team["notes"] == [NO_KEY.format(n=1)]
    everyone = run(seeded, "prs_linked_weekly", team=False)
    assert everyone["rows"][0] == {"week": "2026-08-31", "linked": 0, "unlinked": 2}
    assert everyone["notes"] == [NO_KEY.format(n=2)]


def test_prs_with_issue_link_is_the_share_of_merged_pull_requests_with_a_key(seeded):
    result = run(seeded, "prs_with_issue_link")
    rows = [(r["name"], r["value"], r["sample"]) for r in result["rows"]]
    assert rows == [("Ann Example", 0.67, 3), ("Bob Builder", 1.0, 1)]
    # Only the keys this task owns: other tasks add keys (previous, trend) to the team dict.
    assert result["team"]["value"] == 0.75 and result["team"]["sample"] == 4
    assert result["notes"] == [NO_KEY.format(n=1)]


def test_a_pull_request_linked_only_by_a_jira_issue_link_is_unlinked(conn):
    seed_impact(conn)
    conn.execute("DELETE FROM link WHERE source = 'linker'")
    result = run_metric(conn, BY_NAME["prs_with_issue_link"], team_scope(conn, "t1"), WINDOW)
    assert result["team"]["value"] == 0.0 and result["team"]["sample"] == 4


def test_without_pull_request_links_everything_falls_back_to_the_assignee(conn):
    seed_impact(conn)
    conn.execute("DELETE FROM link WHERE source = 'linker'")
    result = run_metric(conn, BY_NAME["issues_done"], team_scope(conn, "t1"), WINDOW)
    assert table(result) == [("Ann Example", 2.0, 2), ("Bob Builder", 0.0, 0)]
    assert not any("credited to the authors" in note for note in result["notes"])


def test_done_issues_without_a_resolved_date_are_noted_on_the_points_series(seeded):
    issue(seeded, "15", "acc-ann", points=2)  # done, never resolved
    assert NO_DATE in run(seeded, "story_points_weekly")["notes"]
    assert NO_DATE in run(seeded, "points_by_type")["notes"]


def test_the_new_metrics_wait_for_their_sources(conn):
    for name in ("story_points_weekly", "cycle_time_summary"):
        waiting = run_metric(conn, BY_NAME[name], Scope(), WINDOW)
        assert waiting["status"] == "waiting" and waiting["missing"] == ["jira"]
    linked = run_metric(conn, BY_NAME["prs_linked_weekly"], Scope(), WINDOW)
    assert linked["status"] == "waiting" and linked["missing"] == ["bitbucket", "links"]


def test_the_cost_cards_use_existing_waiting_stubs_and_no_new_names_are_registered(seeded):
    for name, missing in (
        ("story_points_per_dollar", ["claude_usage"]),  # computed now; this seed has Jira data
        ("ask_generate_ratio", ["claude_usage"]),
    ):
        metric = BY_NAME[name]
        result = run_metric(seeded, metric, Scope(), WINDOW)
        assert result["status"] == "waiting" and result["missing"] == missing
    assert "impact_per_dollar_weekly" not in BY_NAME and "cost_vs_points" not in BY_NAME
