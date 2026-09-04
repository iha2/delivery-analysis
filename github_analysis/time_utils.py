from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def parse_calendar_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def parse_calendar_month(value: str) -> tuple[int, int]:
    """Parse YYYY-MM and return (year, month)."""
    text = value.strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"expected YYYY-MM for --month, got {value!r}") from exc
    return parsed.year, parsed.month


def calendar_month_window(year: int, month: int) -> tuple[date, date]:
    """Return (start_inclusive, end_exclusive) calendar dates for a full month."""
    if month < 1 or month > 12:
        raise ValueError(f"month must be 1-12, got {month}")
    start = date(year, month, 1)
    if month == 12:
        end_exclusive = date(year + 1, 1, 1)
    else:
        end_exclusive = date(year, month + 1, 1)
    return start, end_exclusive


def parse_report_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value.strip())
    except Exception as exc:
        raise ValueError(f"unknown timezone {value!r} (use an IANA name, e.g. America/New_York)") from exc


def window_bounds_utc(
    start_d: date, end_exclusive_d: date, report_tz: ZoneInfo
) -> tuple[datetime, datetime]:
    start_local = datetime.combine(start_d, time.min, tzinfo=report_tz)
    end_exclusive_local = datetime.combine(end_exclusive_d, time.min, tzinfo=report_tz)
    return (
        start_local.astimezone(timezone.utc),
        end_exclusive_local.astimezone(timezone.utc),
    )


def iso_utc_z(utc_dt: datetime) -> str:
    return utc_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_github_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_report_ts(dt: Optional[datetime], report_tz: ZoneInfo) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(report_tz).isoformat(timespec="seconds")


def hours_since(branch_start: datetime, event: Optional[datetime]) -> str:
    if event is None:
        return ""
    hours = (event - branch_start).total_seconds() / 3600.0
    if hours < 0:
        hours = 0.0
    return f"{hours:.4f}"


def hours_between(start: Optional[datetime], end: Optional[datetime]) -> str:
    if start is None or end is None:
        return ""
    return f"{(end - start).total_seconds() / 3600.0:.4f}"
