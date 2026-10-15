from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from delivery_analysis.core import time_utils as tu

EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc


def test_may_2026_window_in_utc():
    start, end = tu.window_bounds_utc(date(2026, 5, 1), date(2026, 6, 1), EASTERN)
    assert tu.iso_utc_z(start) == "2026-05-01T04:00:00Z"
    assert tu.iso_utc_z(end) == "2026-06-01T04:00:00Z"


def test_window_spanning_daylight_saving_start():
    start, end = tu.window_bounds_utc(date(2026, 3, 1), date(2026, 4, 1), EASTERN)
    assert tu.iso_utc_z(start) == "2026-03-01T05:00:00Z"
    assert tu.iso_utc_z(end) == "2026-04-01T04:00:00Z"


def test_calendar_month_window_rolls_over_the_year():
    assert tu.calendar_month_window(2026, 12) == (date(2026, 12, 1), date(2027, 1, 1))
    assert tu.calendar_month_window(2026, 5) == (date(2026, 5, 1), date(2026, 6, 1))


def test_calendar_month_window_rejects_month_13():
    with pytest.raises(ValueError):
        tu.calendar_month_window(2026, 13)


def test_parse_calendar_month_rejects_bad_format():
    assert tu.parse_calendar_month("2026-05") == (2026, 5)
    with pytest.raises(ValueError, match="YYYY-MM"):
        tu.parse_calendar_month("2026/05")


def test_parse_github_ts_handles_z_none_and_naive():
    assert tu.parse_github_ts("2026-05-01T12:00:00Z") == datetime(2026, 5, 1, 12, tzinfo=UTC)
    assert tu.parse_github_ts("2026-05-01T12:00:00") == datetime(2026, 5, 1, 12, tzinfo=UTC)
    assert tu.parse_github_ts(None) is None
    assert tu.parse_github_ts("") is None


def test_hours_helpers():
    start = datetime(2026, 5, 1, 12, tzinfo=UTC)
    assert tu.hours_since(start, datetime(2026, 5, 1, 13, 30, tzinfo=UTC)) == "1.5000"
    assert tu.hours_since(start, datetime(2026, 5, 1, 10, tzinfo=UTC)) == "0.0000"
    assert tu.hours_since(start, None) == ""
    assert tu.hours_between(start, datetime(2026, 5, 2, 12, tzinfo=UTC)) == "24.0000"
    assert tu.hours_between(None, start) == ""


def test_format_report_ts_uses_report_zone():
    moment = datetime(2026, 5, 1, 4, 0, tzinfo=UTC)
    assert tu.format_report_ts(moment, EASTERN) == "2026-05-01T00:00:00-04:00"
    assert tu.format_report_ts(None, EASTERN) == ""


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-09-01T12:00:00Z", "2026-09-01T12:00:00Z"),
        ("2026-09-01T12:00:00+00:00", "2026-09-01T12:00:00Z"),
        ("2026-09-01T12:00:00.444234+00:00", "2026-09-01T12:00:00Z"),
        ("2026-09-01T12:00:00.832-0700", "2026-09-01T19:00:00Z"),
        ("2026-09-01T12:00:00+0200", "2026-09-01T10:00:00Z"),
        ("2026-09-01T12:00:00.123456789Z", "2026-09-01T12:00:00Z"),
        ("2026-09-01T12:00:00", "2026-09-01T12:00:00Z"),
        ("2026-09-01", "2026-09-01T00:00:00Z"),
    ],
)
def test_to_utc_iso_normalizes_every_shape_seen_in_atlassian_data(value, expected):
    assert tu.to_utc_iso(value) == expected


def test_to_utc_iso_gives_none_for_nothing_and_raises_for_junk():
    assert tu.to_utc_iso(None) is None
    assert tu.to_utc_iso("   ") is None
    with pytest.raises(ValueError):
        tu.to_utc_iso("yesterday")
