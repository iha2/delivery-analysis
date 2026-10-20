from metrics_seed import SEPT, TODAY, TZ, seed
from delivery_analysis.metrics.catalog import METRICS
from delivery_analysis.metrics.matrix import people_matrix
from delivery_analysis.metrics.people import Scope, People, team_scope
from delivery_analysis.metrics.registry import PER_PERSON, run_metric
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)
PER = [m for m in METRICS if m.kind == PER_PERSON and m.group != "activity"]
MATRIX = ["impact_points", "impact_per_dollar", "delivery_points", "delivery_speed", "durability",
          "participation_points", "review_responsiveness", "review_follow_through"]


def test_columns_follow_catalog_order_with_status(conn):
    seed(conn)
    out = people_matrix(conn, Scope(), WINDOW)
    assert [c["name"] for c in out["columns"]] == MATRIX
    by = {c["name"]: c for c in out["columns"]}
    assert by["review_follow_through"]["status"] == "ok" and by["review_follow_through"]["missing"] == []
    assert by["impact_points"]["status"] == "waiting" and by["impact_points"]["missing"] == ["jira"]
    assert by["impact_per_dollar"]["status"] == "waiting" and by["impact_per_dollar"]["missing"] == ["jira", "claude_usage"]
    assert set(by["impact_points"]) == {"name", "label", "unit", "better", "description", "needs", "status", "missing"}
    assert out["window"] == WINDOW.to_json()


def test_cells_match_run_metric_and_unmapped_row_is_last(conn):
    seed(conn)
    out = people_matrix(conn, Scope(), WINDOW)
    names = [r["name"] for r in out["rows"]]
    assert names[-1] == "Unmapped accounts" and out["rows"][-1]["person_id"] is None
    named = names[:-1]
    assert named == sorted(named, key=str.lower)
    ann = [r for r in out["rows"] if r["person_id"] == "p-ann"][0]
    for metric in PER:
        result = run_metric(conn, metric, Scope(), WINDOW)
        if result["status"] != "ok":
            assert metric.name not in ann["cells"]
            continue
        row = [x for x in result["rows"] if x["person_id"] == "p-ann"]
        if not row:
            assert metric.name not in ann["cells"]
            continue
        cell = ann["cells"][metric.name]
        assert set(cell) == {"value", "sample", "ranked", "rank", "confidence"}
        assert cell["value"] == row[0]["value"] and cell["rank"] == row[0]["rank"]
    assert out["rows"][-1]["cells"]  # zed's reviews land in the merged row


def test_waiting_metrics_have_no_cells_and_notes_name_missing_sources(conn):
    seed(conn)
    out = people_matrix(conn, Scope(), WINDOW)
    waiting = [c["name"] for c in out["columns"] if c["status"] == "waiting"]
    assert waiting
    for row in out["rows"]:
        assert not set(waiting) & set(row["cells"])
    assert any("waiting for claude_usage data" in n for n in out["notes"])
    assert len(out["notes"]) == len(set(out["notes"]))


def test_team_scope_drops_non_members(conn):
    seed(conn)
    out = people_matrix(conn, team_scope(conn, "t1"), WINDOW)
    ids = {r["person_id"] for r in out["rows"]}
    assert "p-cy" not in ids and "p-dee" not in ids
    assert {"p-ann", "p-bob"} <= ids
    assert People(conn).name("p-ann") in [r["name"] for r in out["rows"]]
