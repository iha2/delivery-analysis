from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Dict, Iterable, List, Optional

ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class Window:
    """Local calendar days as UTC bounds: start inclusive, end exclusive."""

    start: str
    end: str
    label: str
    first_day: date
    days: int
    tz: tzinfo

    def to_json(self) -> Dict[str, Any]:
        return {"start": self.start, "end": self.end, "label": self.label, "days": self.days}


def _utc(day: date, tz: tzinfo) -> str:
    return datetime.combine(day, time(0), tzinfo=tz).astimezone(timezone.utc).strftime(ISO_Z)


def _build(first: date, days: int, label: str, tz: tzinfo) -> Window:
    return Window(_utc(first, tz), _utc(first + timedelta(days=days), tz), label, first, days, tz)


def make_window(
    spec: Optional[str],
    tz: tzinfo,
    today: date,
    *,
    default_days: int = 90,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Window:
    text = (spec or "").strip() or f"{default_days}d"
    match = re.fullmatch(r"(\d{1,4})d", text)
    if match:
        days = int(match.group(1))
        if days < 1:
            raise ValueError("A window needs at least one day.")
        return _build(today - timedelta(days=days - 1), days, f"Last {days} days", tz)
    match = re.fullmatch(r"month:(\d{4})-(\d{2})", text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"Unknown month in {text!r}.")
        first = date(year, month, 1)
        after = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        return _build(first, (after - first).days, first.strftime("%B %Y"), tz)
    if text == "custom":
        try:
            first = date.fromisoformat(start or "")
            last = date.fromisoformat(end or "")
        except ValueError:
            raise ValueError("A custom window needs from and to dates as YYYY-MM-DD.") from None
        if last < first:
            raise ValueError("The window end must be on or after its start.")
        return _build(first, (last - first).days + 1, f"{first.isoformat()} to {last.isoformat()}", tz)
    raise ValueError(f"Unknown window {text!r}. Use 30d, 90d, month:YYYY-MM or custom.")


def previous(window: Window) -> Window:
    """The window of the same number of days just before this one."""
    first = window.first_day - timedelta(days=window.days)
    return _build(first, window.days, f"Previous {window.days} days", window.tz)


def local_day(timestamp: str, tz: tzinfo) -> date:
    return datetime.strptime(timestamp, ISO_Z).replace(tzinfo=timezone.utc).astimezone(tz).date()


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def hours_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
    if not start or not end:
        return None
    return (datetime.strptime(end, ISO_Z) - datetime.strptime(start, ISO_Z)).total_seconds() / 3600.0


def weekly(window: Window, timestamps: Iterable[Optional[str]]) -> List[Dict[str, Any]]:
    """Count timestamps per local week (Monday start), with every week of the window present."""
    counts: Dict[date, int] = {}
    for stamp in timestamps:
        if stamp:
            week = week_start(local_day(stamp, window.tz))
            counts[week] = counts.get(week, 0) + 1
    rows: List[Dict[str, Any]] = []
    week = week_start(window.first_day)
    last = window.first_day + timedelta(days=window.days - 1)
    while week <= last:
        rows.append({"week": week.isoformat(), "value": counts.get(week, 0)})
        week += timedelta(days=7)
    return rows
