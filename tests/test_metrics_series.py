import statistics
import time
from datetime import date, timedelta

import pytest

from metrics_seed import TZ
from test_metrics_impact_model import seed_model
from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import People, Scope, team_scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.series import KEYS, person_series
from delivery_analysis.metrics.window import make_window

METRIC_OF = {
    "impact": "impact_points", "delivery": "delivery_points", "participation": "participation_points",
    "impact_per_dollar": "impact_per_dollar", "prs_reviewed": "prs_reviewed", "review_value": "review_value",
    "delivery_speed": "delivery_speed", "durability": "durability",
}
END = date(2026, 9, 20)


@pytest.fixture
def seeded(conn):
    seed_model(conn)
    return conn


def reference(conn, scope, person_id, key, end, days):
    result = run_metric(conn, BY_NAME[METRIC_OF[key]], scope, make_window(f"{days}d", TZ, end), People(conn))
    row = next((r for r in result["rows"] if r["person_id"] == person_id), None)
    return None if row is None else row["value"]


def test_shape_dates_and_keys(seeded):
    out = person_series(seeded, "p-ann", team_scope(seeded, "t1"), end=END, window_days=7, step_days=7,
                        history_days=28, tz=TZ)
    assert out["dates"] == ["2026-08-23", "2026-08-30", "2026-09-06", "2026-09-13", "2026-09-20"]
    assert out["window_days"] == 7
    assert set(out["series"]) == set(KEYS) == set(out["team_median"])
    assert all(len(v) == 5 for v in out["series"].values()) and all(len(v) == 5 for v in out["team_median"].values())
    assert isinstance(out["notes"], list)


def test_values_match_run_metric_for_every_point(seeded):
    scope = team_scope(seeded, "t1")
    out = person_series(seeded, "p-ann", scope, end=END, window_days=14, step_days=5, history_days=40, tz=TZ)
    for person in ("p-ann", "p-bob"):
        out = person_series(seeded, person, scope, end=END, window_days=14, step_days=5, history_days=40, tz=TZ)
        for key in METRIC_OF:
            for index, day in enumerate(out["dates"]):
                want = reference(seeded, scope, person, key, date.fromisoformat(day), 14)
                if want is None and key in ("impact", "delivery", "participation", "prs_reviewed", "review_value"):
                    want = 0.0
                got = out["series"][key][index]
                assert got == pytest.approx(want) if want is not None else got is None, (person, key, day)


def test_known_values_and_penalty(seeded):
    scope = team_scope(seeded, "t1")
    out = person_series(seeded, "p-ann", scope, end=END, window_days=30, step_days=30, history_days=30, tz=TZ)
    assert out["dates"][-1] == "2026-09-20"
    assert out["series"]["penalty"][-1] == pytest.approx(0.05)
    assert out["series"]["delivery"][-1] == pytest.approx(13.95)
    assert out["series"]["impact_per_dollar"][-1] is None  # no Claude cost yet


def test_window_and_step_edges(seeded):
    scope = team_scope(seeded, "t1")
    one = person_series(seeded, "p-ann", scope, end=END, window_days=7, step_days=7, history_days=0, tz=TZ)
    assert one["dates"] == ["2026-09-20"]
    weekly = person_series(seeded, "p-ann", scope, end=END, window_days=7, step_days=7, history_days=14, tz=TZ)
    # a1 resolved 09-10 falls in the window ending 09-13 only; b1 (09-15) in the window ending 09-20.
    assert weekly["series"]["delivery"][0] == 0
    assert weekly["series"]["delivery"][1] == pytest.approx(9.95)
    assert weekly["series"]["delivery"][2] == pytest.approx(4.0)
    daily = person_series(seeded, "p-ann", scope, end=END, window_days=7, step_days=1, history_days=3, tz=TZ)
    assert daily["dates"] == [(END - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)]


def test_person_without_shares_gets_zeros_not_an_error(seeded):
    scope = team_scope(seeded, "t1")
    for person in ("p-cy", "p-nobody"):
        out = person_series(seeded, person, scope, end=END, window_days=30, step_days=15, history_days=30, tz=TZ)
        for key in ("impact", "delivery", "participation", "penalty", "prs_reviewed", "review_value"):
            assert out["series"][key] == [0.0, 0.0, 0.0], key
        assert out["series"]["impact_per_dollar"] == [None, None, None]


def test_team_median_counts_every_member_for_sum_metrics_and_members_with_a_value_for_ratios(seeded):
    scope = team_scope(seeded, "t1")
    out = person_series(seeded, "p-ann", scope, end=END, window_days=30, step_days=30, history_days=0, tz=TZ)
    result = run_metric(seeded, BY_NAME["impact_points"], scope, make_window("30d", TZ, END), People(seeded))
    got = {r["person_id"]: r["value"] for r in result["rows"] if r["person_id"] is not None}
    want = statistics.median(got.get(member, 0.0) for member in scope.members)
    assert out["team_median"]["impact"] == [pytest.approx(want)]
    assert out["team_median"]["impact_per_dollar"] == [None]
    assert out["team_median"]["delivery_speed"][0] is not None


def test_without_a_team_the_median_covers_everyone(seeded):
    out = person_series(seeded, "p-ann", Scope(), end=END, window_days=30, step_days=30, history_days=0, tz=TZ)
    assert out["series"]["impact"][0] > 0 and out["team_median"]["impact"][0] is not None


def test_no_data_at_all_is_all_null_not_an_error(conn):
    out = person_series(conn, "p-x", Scope(), end=END, window_days=30, step_days=30, history_days=30, tz=TZ)
    assert out["series"]["impact"] == [None, None] and out["team_median"]["impact"] == [None, None]


def test_26_windows_are_fast(seeded):
    scope = team_scope(seeded, "t1")
    started = time.perf_counter()
    out = person_series(seeded, "p-ann", scope, end=END, window_days=30, step_days=7, history_days=180, tz=TZ)
    elapsed = time.perf_counter() - started
    print(f"series: {len(out['dates'])} windows in {elapsed:.3f}s")
    assert len(out["dates"]) == 26 and elapsed < 3.0


def test_without_a_team_sum_metric_median_counts_people_without_a_row_as_zero(seeded):
    people = People(seeded)
    out = person_series(seeded, "p-ann", Scope(), end=END, window_days=30, step_days=30, history_days=0, tz=TZ)
    everyone = [row["person_id"] for row in people.all()]
    for key in ("impact", "delivery", "participation", "prs_reviewed", "review_value", "penalty"):
        if key == "penalty":
            continue
        result = run_metric(seeded, BY_NAME[METRIC_OF[key]], Scope(), make_window("30d", TZ, END), people)
        got = {r["person_id"]: r["value"] for r in result["rows"] if r["person_id"] is not None}
        want = statistics.median(got.get(person, 0.0) or 0.0 for person in everyone)
        assert out["team_median"][key] == [pytest.approx(round(want, 4))], key
    ratio = [r["value"] for r in run_metric(seeded, BY_NAME["delivery_speed"], Scope(), make_window("30d", TZ, END), people)["rows"]
             if r["value"] is not None]
    assert out["team_median"]["delivery_speed"] == [pytest.approx(statistics.median(ratio))]
