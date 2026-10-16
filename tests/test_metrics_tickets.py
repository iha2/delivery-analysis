from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from token_world import World
from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.app.server import create_app
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.tickets import ticket_costs
from delivery_analysis.metrics.window import make_window
from delivery_analysis.settings import Settings
from delivery_analysis.store import db
from delivery_analysis.tokens.rebuild import rebuild

MARCH = make_window("month:2026-03", ZoneInfo("America/New_York"), date(2026, 3, 20))


def build(conn):
    w = World(conn)
    ada, eve = w.person("Ada Example"), w.person("Eve Example")
    t1 = w.ticket("MD-1", assignee=ada, points=3).in_progress("2026-03-02")
    pr = w.pull_request(ada, created="2026-03-02", merged="2026-03-03", links=[t1])
    w.commit(ada, "2026-03-02", pr=pr)
    w.event(pr, eve, "comment", "2026-03-02")
    w.usage(ada, "2026-03-02", 1000)
    t1.completed("2026-03-03")
    rebuild(conn, date(2026, 3, 20))
    return w, ada, eve


def test_ticket_rows_carry_cost_credit_and_pull_request_evidence(conn):
    build(conn)
    out = ticket_costs(conn, Scope(), MARCH)
    (row,) = out["tickets"]
    assert (row["key"], row["points"], row["cost_usd"], row["points_per_usd"], row["confidence"]) == (
        "MD-1", 3.0, 10.0, 0.3, "high")
    assert row["people"] == [
        {"person_id": "p-ada", "name": "Ada Example", "share": 0.8, "cost_usd": 10.0},
        {"person_id": "p-eve", "name": "Eve Example", "share": 0.2, "cost_usd": 0.0},
    ]
    assert (row["pull_requests"], row["files_changed"], row["commits"], row["review_comments"],
            row["hours_to_merge"]) == (1, 3, 2, 1, 30.0)
    assert "cost_weekly" not in out


def test_the_person_filter_and_their_weekly_cost(conn):
    build(conn)
    assert [t["key"] for t in ticket_costs(conn, Scope(), MARCH, "p-eve")["tickets"]] == ["MD-1"]
    assert ticket_costs(conn, Scope(), MARCH, "p-zed")["tickets"] == []
    weekly = ticket_costs(conn, Scope(), MARCH, "p-ada")["cost_weekly"]
    assert {"week": "2026-03-02", "cost_usd": 10.0} in weekly


def test_the_tickets_endpoint(tmp_path):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    build(conn)
    conn.close()
    app = create_app(path, settings=Settings(db_path=path), environ={}, worker=RefreshWorker(lambda s, f: "ok"),
                     clock=lambda: datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc), port=8000)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get("/api/tickets", params={"window": "month:2026-03", "person": "p-ada"})
    assert response.status_code == 200 and response.json()["tickets"][0]["key"] == "MD-1"
    assert client.get("/api/tickets", params={"team": "nope"}).status_code == 404


def test_a_team_sees_only_its_members_cost_levels_and_people_on_a_shared_ticket(conn):
    import pytest
    from delivery_analysis.metrics.people import team_scope
    world, ada, eve = build(conn)
    world.team("t-eve", "Eve team", [eve])
    scope = team_scope(conn, "t-eve")
    (row,) = ticket_costs(conn, scope, MARCH)["tickets"]  # eve is a member, ada is not
    assert [p["person_id"] for p in row["people"]] == ["p-eve"]
    assert (row["cost_usd"], row["points_per_usd"], row["confidence"]) == (0.0, None, None)  # ada's $10 is hidden
    with pytest.raises(ValueError, match="not a member"):
        ticket_costs(conn, scope, MARCH, "p-ada")


def test_the_tickets_endpoint_refuses_a_person_outside_the_team(tmp_path):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    world, ada, eve = build(conn)
    world.team("t-eve", "Eve team", [eve])
    conn.commit()
    conn.close()
    app = create_app(path, settings=Settings(db_path=path), environ={}, worker=RefreshWorker(lambda s, f: "ok"),
                     clock=lambda: datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc), port=8000)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get("/api/tickets", params={"team": "t-eve", "window": "month:2026-03", "person": "p-ada"})
    assert response.status_code == 400 and "not a member" in response.json()["detail"]
