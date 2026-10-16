from datetime import date
from zoneinfo import ZoneInfo

from token_world import World
from delivery_analysis.metrics import tokens as tk
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import Scope, team_scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window
from delivery_analysis.tokens.rebuild import rebuild

TZ = ZoneInfo("America/New_York")
MARCH = make_window("month:2026-03", TZ, date(2026, 3, 20))


def build(conn):
    w = World(conn)
    ada, bo, cy = w.person("Ada Example"), w.person("Bo Example"), w.person("Cy Example")
    for key, points, start, end in (("MD-1", 3, 2, 3), ("MD-2", 2, 4, 5), ("MD-3", 5, 6, 7)):
        w.ticket(key, assignee=ada, points=points).in_progress(f"2026-03-0{start}").completed(f"2026-03-0{end}")
        w.usage(ada, f"2026-03-0{start}", 1000, accepted_edits=10 if key == "MD-1" else None)
    w.usage(ada, "2026-03-08", 1000)
    w.ticket("MD-4", assignee=bo, points=8).in_progress("2026-03-02").completed("2026-03-03")
    w.usage(bo, "2026-03-02", 5000)
    w.ticket("MD-5", assignee=cy).in_progress("2026-03-10").completed("2026-03-11")
    w.usage("ghost@corp.example", "2026-03-05", 300)
    rebuild(conn, date(2026, 3, 20))
    return w, ada, bo, cy


def run(conn, name, scope=None):
    return run_metric(conn, BY_NAME[name], scope or Scope(), MARCH)


def by_name(result):
    return {row["name"]: row for row in result["rows"]}


def test_story_points_per_dollar_is_a_cohort_ratio_with_confidence(conn):
    build(conn)
    result = run(conn, "story_points_per_dollar")
    rows = by_name(result)
    ada, bo = rows["Ada Example"], rows["Bo Example"]
    assert (ada["value"], ada["numerator"], ada["denominator"], ada["sample"], ada["ranked"], ada["confidence"]) == (
        0.3333, 10.0, 30.0, 3, True, "medium")
    assert (bo["value"], bo["ranked"], bo["unranked_reason"], bo["confidence"]) == (
        0.16, False, "fewer than 3 completed tickets", "low")
    assert result["team"]["value"] == 0.225
    assert "1 completed ticket without story points left out." in result["notes"]
    assert tk.COVERAGE_NOTE in result["notes"]


def test_all_in_divides_by_every_attributed_day(conn):
    build(conn)
    rows = by_name(run(conn, "story_points_per_dollar_all_in"))
    assert rows["Ada Example"]["value"] == 0.25 and rows["Bo Example"]["value"] == 0.16


def test_weekly_impact_series(conn):
    build(conn)
    result = run(conn, "story_points_per_dollar_weekly")
    week = next(row for row in result["rows"] if row["week"] == "2026-03-02")
    assert week == {"week": "2026-03-02", "points": 18.0, "cost_usd": 80.0, "tickets": 4, "value": 0.225}
    assert all(row["value"] is None for row in result["rows"] if row["week"] != "2026-03-02")


def test_cost_unattributed_share_ask_ratio_and_purpose_weeks(conn):
    build(conn)
    cost = by_name(run(conn, "cost_spent"))
    assert cost["Ada Example"]["value"] == 40.0 and cost["Bo Example"]["value"] == 50.0
    assert cost["Unmapped (1 account)"]["value"] == 3.0
    share = by_name(run(conn, "unattributed_cost_share"))
    assert share["Ada Example"]["value"] == 0.25 and share["Ada Example"]["ranked"] is True
    ratio = by_name(run(conn, "ask_generate_ratio"))
    assert ratio["Ada Example"]["value"] == 1.0 and ratio["Ada Example"]["ranked"] is False
    weeks = run(conn, "cost_by_purpose_weekly")["rows"]
    assert next(r for r in weeks if r["week"] == "2026-03-02") == {
        "week": "2026-03-02", "ask": 5.0, "generate": 5.0, "unclassified": 80.0}


def test_team_scope_keeps_other_teams_tickets_out(conn):
    w, ada, bo, cy = build(conn)
    w.team("t-ada", "Ada team", [ada])
    scope = team_scope(conn, "t-ada")
    result = run(conn, "story_points_per_dollar", scope)
    assert [row["name"] for row in result["rows"]] == ["Ada Example"] and result["team"]["value"] == 0.3333
    week = next(r for r in run(conn, "story_points_per_dollar_weekly", scope)["rows"] if r["week"] == "2026-03-02")
    assert (week["points"], week["cost_usd"], week["tickets"]) == (10.0, 30.0, 3)


def test_cost_spent_counts_utc_days_inside_the_local_window_only(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    w.usage(ada, "2026-03-31", 100)
    w.usage(ada, "2026-04-01", 100)
    w.usage(ada, "2026-02-28", 100)
    assert tk.cost_spent(conn, Scope(), MARCH).by_actor == {"email:ada@corp.example": [1.0]}


def test_ask_generate_ratio_without_generate_cost_is_none(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    w.usage(ada, "2026-03-03", 1000, accepted_edits=0)
    rebuild(conn, date(2026, 3, 20))
    row = by_name(run(conn, "ask_generate_ratio"))["Ada Example"]
    assert row["value"] is None and row["ranked"] is False
