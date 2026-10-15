from datetime import date
from zoneinfo import ZoneInfo

import pytest

from delivery_analysis.metrics import window as w

TZ = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 15)


def test_last_n_days_includes_today_and_uses_local_midnight():
    win = w.make_window("90d", TZ, TODAY)
    assert (win.start, win.end, win.days, win.label) == (
        "2026-07-18T04:00:00Z", "2026-10-16T04:00:00Z", 90, "Last 90 days"
    )


def test_an_empty_spec_uses_the_default_days():
    assert w.make_window("", TZ, TODAY, default_days=30).days == 30


def test_a_month_across_the_dst_change_starts_and_ends_at_local_midnight():
    win = w.make_window("month:2026-11", TZ, TODAY)
    assert (win.start, win.end, win.days, win.label) == (
        "2026-11-01T04:00:00Z", "2026-12-01T05:00:00Z", 30, "November 2026"
    )
    december = w.make_window("month:2026-12", TZ, TODAY)
    assert december.end == "2027-01-01T05:00:00Z"


def test_a_custom_window_includes_its_last_day():
    win = w.make_window("custom", TZ, TODAY, start="2026-09-01", end="2026-09-30")
    assert (win.start, win.end, win.days) == ("2026-09-01T04:00:00Z", "2026-10-01T04:00:00Z", 30)


@pytest.mark.parametrize(
    "spec, start, end",
    [("0d", None, None), ("month:2026-13", None, None), ("weekly", None, None),
     ("custom", "2026-09-30", "2026-09-01"), ("custom", "bad", "2026-09-01")],
)
def test_bad_windows_are_plain_value_errors(spec, start, end):
    with pytest.raises(ValueError):
        w.make_window(spec, TZ, TODAY, start=start, end=end)


def test_previous_is_the_same_length_and_ends_where_this_one_starts():
    win = w.make_window("month:2026-09", TZ, TODAY)
    before = w.previous(win)
    assert before.end == win.start and before.days == 30
    assert before.first_day == date(2026, 8, 2)


def test_time_helpers():
    assert w.local_day("2026-09-21T02:00:00Z", TZ) == date(2026, 9, 20)
    assert w.week_start(date(2026, 9, 20)) == date(2026, 9, 14)
    assert w.hours_between("2026-09-01T14:00:00Z", "2026-09-02T02:00:00Z") == 12.0
    assert w.hours_between(None, "2026-09-02T02:00:00Z") is None


def test_weekly_fills_empty_weeks_across_the_window():
    win = w.make_window("month:2026-09", TZ, TODAY)
    rows = w.weekly(win, ["2026-09-02T14:00:00Z", "2026-09-21T02:00:00Z", "2026-09-03T10:00:00Z"])
    assert rows == [
        {"week": "2026-08-31", "value": 2}, {"week": "2026-09-07", "value": 0},
        {"week": "2026-09-14", "value": 1}, {"week": "2026-09-21", "value": 0},
        {"week": "2026-09-28", "value": 0},
    ]
