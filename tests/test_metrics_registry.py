from metrics_seed import SEPT, TODAY, TZ, seed
from delivery_analysis.metrics import registry as r
from delivery_analysis.metrics.people import Scope, actor_key, team_scope
from delivery_analysis.metrics.window import make_window


def counting(values_by_window):
    """A fake metric that returns fixed observations per window start."""
    def compute(conn, scope, window):
        obs = r.Observations(notes=["a note"])
        for key, values in values_by_window.get(window.start, {}).items():
            for value in values:
                obs.add(key, value)
        return obs
    return compute


SEPT_WINDOW = make_window(SEPT, TZ, TODAY)
AUG_START = "2026-08-02T04:00:00Z"


def test_per_person_rows_rank_trend_unranked_and_unmapped(conn):
    seed(conn)
    data = {
        SEPT_WINDOW.start: {"bitbucket:acc-ann": [1, 1, 1, 1], "bitbucket:acc-bob": [1], "bitbucket:acc-zed": [1, 1],
                            "bitbucket:acc-dee": [1, 1, 1], "bitbucket:acc-cy": [1, 1, 1]},
        AUG_START: {"bitbucket:acc-ann": [1, 1]},
    }
    metric = r.Metric("m", "M", "count", r.PER_PERSON, ("bitbucket",), compute=counting(data))
    result = r.run_metric(conn, metric, team_scope(conn, "t1"), SEPT_WINDOW)
    assert result["status"] == "ok" and result["notes"] == ["a note"]
    rows = [(x["name"], x["value"], x["sample"], x["previous"], x["trend"], x["ranked"], x["rank"]) for x in result["rows"]]
    assert rows == [
        ("Ann Example", 4.0, 4, 2.0, 1.0, True, 1),
        ("Bob Builder", 1.0, 1, 0.0, None, False, None),
        ("Unmapped (1 account)", 2.0, 2, None, None, False, None),
    ]
    assert result["team"] == {"value": 5.0, "sample": 5}
    assert result["window"]["label"] == "September 2026"


def test_without_a_team_everyone_with_activity_appears_except_excluded(conn):
    seed(conn)
    data = {SEPT_WINDOW.start: {"bitbucket:acc-cy": [1], "email:ann@corp.example": [1], "bitbucket:acc-dee": [1]}}
    metric = r.Metric("m", "M", "count", r.PER_PERSON, ("bitbucket",), min_sample=1, compute=counting(data))
    names = [row["name"] for row in r.run_metric(conn, metric, Scope(), SEPT_WINDOW)["rows"]]
    assert names == ["Ann Example", "Cy Inactive"]


def test_lower_is_better_sorts_ascending_and_median_has_p85(conn):
    seed(conn)
    data = {SEPT_WINDOW.start: {"bitbucket:acc-ann": [10, 20, 30], "bitbucket:acc-bob": [1, 2, 3]}}
    metric = r.Metric("t", "T", "hours", r.PER_PERSON, ("bitbucket",), better="lower", aggregate="median",
                      compute=counting(data))
    result = r.run_metric(conn, metric, team_scope(conn, "t1"), SEPT_WINDOW)
    assert [(row["name"], row["rank"]) for row in result["rows"]] == [("Bob Builder", 1), ("Ann Example", 2)]
    assert result["team"]["value"] == 6.5 and result["team"]["p85"] == 22.5


def test_a_metric_without_compute_or_data_is_waiting(conn):
    stub = r.Metric("x", "X", "count", r.PER_PERSON, ("jira",))
    assert r.describe(conn, stub)["status"] == "waiting" and r.describe(conn, stub)["missing"] == ["jira"]
    built = r.Metric("y", "Y", "count", r.PER_PERSON, ("bitbucket",), compute=counting({}))
    assert r.describe(conn, built)["missing"] == ["bitbucket"]  # no Bitbucket rows yet
    seed(conn)
    assert r.describe(conn, built)["status"] == "ok"
    waiting = r.run_metric(conn, stub, Scope(), SEPT_WINDOW)
    assert waiting["status"] == "waiting" and waiting["rows"] == []


def test_a_failing_metric_reports_an_error_instead_of_raising(conn):
    seed(conn)

    def boom(conn, scope, window):
        raise RuntimeError("bad query")

    metric = r.Metric("b", "B", "count", r.TEAM_SERIES, ("bitbucket",), compute=boom)
    result = r.run_metric(conn, metric, Scope(), SEPT_WINDOW)
    assert result["status"] == "error" and result["error"] == "bad query"


def test_percentile_and_aggregate():
    assert r.percentile([], 85) is None
    assert r.percentile([12, 24, 48], 85) == 40.8
    assert r.aggregate([], "sum") == 0.0 and r.aggregate([], "median") is None
    assert r.aggregate([1, 0, 1, 0], "mean") == 0.5
    assert actor_key(("bitbucket", "a")) == "bitbucket:a"
