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
    assert result["team"] == {"value": 7.0, "sample": 7, "previous": 2.0, "trend": 2.5}
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


def test_the_team_total_includes_activity_by_unmapped_accounts(conn):
    seed(conn)
    data = {SEPT_WINDOW.start: {"bitbucket:acc-ann": [10.0], "bitbucket:acc-zed": [30.0, 50.0]}}
    metric = r.Metric("t", "T", "hours", r.PER_PERSON, ("bitbucket",), aggregate="median", compute=counting(data))
    result = r.run_metric(conn, metric, Scope(), SEPT_WINDOW)
    assert result["team"]["value"] == 30.0 and result["team"]["sample"] == 3


def _payload(conn, source, fetched_at, source_id="p1"):
    conn.execute("DELETE FROM raw_payload")
    if fetched_at:
        conn.execute(
            "INSERT INTO raw_payload (source, source_id, kind, json, fetched_at) VALUES (?, ?, 'x', '{}', ?)",
            (source, source_id, fetched_at),
        )


def _trend_metric():
    data = {
        SEPT_WINDOW.start: {"bitbucket:acc-ann": [1, 1, 1, 1], "bitbucket:acc-zed": [1, 1]},
        AUG_START: {"bitbucket:acc-ann": [1, 1], "bitbucket:acc-zed": [1, 1]},
    }
    return r.Metric("m", "M", "count", r.PER_PERSON, ("bitbucket",), compute=counting(data))


def test_team_previous_and_trend_use_the_same_grouping_as_the_total(conn):
    seed(conn)
    _payload(conn, "bitbucket", None)
    team = r.run_metric(conn, _trend_metric(), team_scope(conn, "t1"), SEPT_WINDOW)["team"]
    assert team == {"value": 6.0, "sample": 6, "previous": 4.0, "trend": 0.5}


def test_team_trend_is_none_when_previous_is_zero_and_for_non_windowed_metrics(conn):
    seed(conn)
    _payload(conn, "bitbucket", None)
    data = {SEPT_WINDOW.start: {"bitbucket:acc-ann": [1]}}
    metric = r.Metric("m", "M", "count", r.PER_PERSON, ("bitbucket",), compute=counting(data))
    team = r.run_metric(conn, metric, Scope(), SEPT_WINDOW)["team"]
    assert team["previous"] == 0.0 and team["trend"] is None
    flat = r.Metric("f", "F", "count", r.PER_PERSON, ("bitbucket",), windowed=False, compute=counting(data))
    team = r.run_metric(conn, flat, Scope(), SEPT_WINDOW)["team"]
    assert team["previous"] is None and team["trend"] is None


def test_coverage_start_is_the_first_fetch_minus_history_days(conn):
    _payload(conn, "bitbucket", "2026-10-01T12:00:00Z")
    conn.execute(
        "INSERT INTO raw_payload (source, source_id, kind, json, fetched_at) "
        "VALUES ('bitbucket', 'p2', 'x', '{}', '2026-10-10T00:00:00Z')"
    )
    assert r.coverage_start(conn, "bitbucket", 90) == "2026-07-03T12:00:00Z"
    assert r.coverage_start(conn, "jira", 90) is None


def test_trend_is_hidden_with_a_note_when_history_is_short(conn):
    seed(conn)
    _payload(conn, "bitbucket", "2026-10-01T12:00:00Z")
    result = r.run_metric(conn, _trend_metric(), team_scope(conn, "t1"), SEPT_WINDOW, history_days=20)
    # coverage starts 2026-09-11, after the previous window starts (2026-08-02)
    assert all(row["previous"] is None and row["trend"] is None for row in result["rows"])
    assert result["team"]["previous"] is None and result["team"]["trend"] is None
    assert result["team"]["value"] == 6.0
    assert "Not enough history for a trend yet: bitbucket data starts 2026-09-11." in result["notes"]


def test_trend_is_kept_when_history_is_long_enough(conn):
    seed(conn)
    _payload(conn, "bitbucket", "2026-10-01T12:00:00Z")  # coverage starts 2026-07-03
    result = r.run_metric(conn, _trend_metric(), team_scope(conn, "t1"), SEPT_WINDOW, history_days=90)
    assert result["team"]["trend"] == 0.5
    assert result["rows"][0]["trend"] == 1.0
    assert not any("Not enough history" in note for note in result["notes"])
