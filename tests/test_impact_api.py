from datetime import datetime, timezone

from fastapi.testclient import TestClient

from impact_seed import seed_impact
from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.server import create_app
from delivery_analysis.settings import Settings
from delivery_analysis.store import db

CLOCK = lambda: datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc)  # noqa: E731
PARAMS = {"team": "t1", "window": "month:2026-09"}


def make(tmp_path):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    seed_impact(conn)
    conn.close()
    app = create_app(
        path, settings=Settings(db_path=path), environ={}, worker=RefreshWorker(lambda source, full: "ok"),
        clock=CLOCK, port=8000,
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_the_new_row_shapes_come_through_the_api(tmp_path):
    client = make(tmp_path)
    weekly = client.get("/api/metrics/story_points_weekly", params=PARAMS).json()
    assert weekly["status"] == "ok"
    assert weekly["rows"][2] == {"week": "2026-09-14", "value": 3.0, "issues": 2, "unpointed": 1}
    kinds = client.get("/api/metrics/points_by_type", params=PARAMS).json()
    assert kinds["rows"][0] == {"part": "Story", "value": 8.0, "count": 2}
    cycle = client.get("/api/metrics/cycle_time_weekly", params=PARAMS).json()
    assert set(cycle["rows"][1]) == {"week", "median", "p85", "count", "pr_median", "pr_p85", "pr_count"}
    summary = client.get("/api/metrics/cycle_time_summary", params=PARAMS).json()
    assert [row["part"] for row in summary["rows"]] == ["In Progress to COMPLETED", "In Progress to first PR merge"]
    linked = client.get("/api/metrics/prs_linked_weekly", params=PARAMS).json()
    assert set(linked["rows"][0]) == {"week", "linked", "unlinked"}
    rate = client.get("/api/metrics/prs_with_issue_link", params=PARAMS).json()
    # Only the keys this task owns: other tasks add keys (previous, trend) to the team dict.
    assert rate["team"]["value"] == 0.75 and rate["team"]["sample"] == 4


def test_per_person_points_are_credited_by_pull_request_through_the_api(tmp_path):
    client = make(tmp_path)
    body = client.get("/api/metrics/story_points_done", params=PARAMS).json()
    assert [(r["name"], r["value"]) for r in body["rows"]] == [("Ann Example", 6.5), ("Bob Builder", 1.5)]
    assert any("credited to the authors of their linked pull requests" in note for note in body["notes"])


def test_the_cost_cards_read_existing_stubs_that_are_listed_as_waiting(tmp_path):
    client = make(tmp_path)
    listing = {m["name"]: m for m in client.get("/api/metrics").json()["metrics"]}
    assert listing["story_points_per_dollar"]["status"] == "waiting"
    assert listing["ask_generate_ratio"]["missing"] == ["claude_usage"]
    assert listing["story_points_weekly"]["status"] == "ok"
    assert "impact_per_dollar_weekly" not in listing and "cost_vs_points" not in listing
    waiting = client.get("/api/metrics/story_points_per_dollar", params=PARAMS).json()
    assert waiting["status"] == "waiting" and waiting["rows"] == []


def test_the_person_endpoint_has_credited_issues(tmp_path):
    client = make(tmp_path)
    body = client.get("/api/people/p-ann", params=PARAMS).json()
    assert [(row["key"], row["share"], row["basis"]) for row in body["issues_done"]] == [
        ("MD-3", 0.5, "pull request"), ("MD-2", 1.0, "assignee"), ("MD-1", 1.0, "pull request"),
    ]
