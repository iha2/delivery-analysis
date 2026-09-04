from __future__ import annotations

import argparse
from datetime import date
from zoneinfo import ZoneInfo

from github_analysis.config import DEFAULT_REPORT_TZ_NAME, REPORT_TZ
from github_analysis.time_utils import (
    calendar_month_window,
    parse_calendar_date,
    parse_calendar_month,
    parse_report_timezone,
)


def date_window_note(report_tz: ZoneInfo | None = None) -> str:
    tz_key = (report_tz or REPORT_TZ).key
    return f"Half-open window in {tz_key}: start <= event time < end (end date exclusive)"


def add_period_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--month",
        metavar="YYYY-MM",
        help=(
            "Full calendar month in --timezone (sets --start-date and --end-date automatically). "
            "Cannot be combined with --start-date or --end-date. Example: 2026-05 for all of May."
        ),
    )
    parser.add_argument(
        "--start-date",
        metavar="YYYY-MM-DD",
        help=(
            "First calendar day included, 00:00 in --timezone. "
            "Required unless --month is set."
        ),
    )
    parser.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        help=(
            "First calendar day excluded, 00:00 in --timezone "
            "(e.g. 2026-06-01 includes through May 31). Required unless --month is set."
        ),
    )
    parser.add_argument(
        "--timezone",
        default=DEFAULT_REPORT_TZ_NAME,
        metavar="IANA",
        help=(
            f"IANA timezone for calendar dates and report timestamps "
            f"(default: {DEFAULT_REPORT_TZ_NAME})"
        ),
    )


def resolve_report_window(args: argparse.Namespace) -> tuple[date, date, ZoneInfo]:
    """Resolve start/end dates and report timezone from CLI period arguments."""
    report_tz = parse_report_timezone(args.timezone)
    month = getattr(args, "month", None)
    start_s = getattr(args, "start_date", None)
    end_s = getattr(args, "end_date", None)

    if month:
        if start_s or end_s:
            raise ValueError("Use either --month or --start-date/--end-date, not both")
        year, month_num = parse_calendar_month(month)
        start_date, end_date = calendar_month_window(year, month_num)
    else:
        if not start_s or not end_s:
            raise ValueError("Provide --month YYYY-MM or both --start-date and --end-date")
        start_date = parse_calendar_date(start_s)
        end_date = parse_calendar_date(end_s)

    if end_date <= start_date:
        raise ValueError("--end-date must be after --start-date (end is exclusive)")

    return start_date, end_date, report_tz


def apply_resolved_window_to_args(
    args: argparse.Namespace, start_date: date, end_date: date, report_tz: ZoneInfo
) -> None:
    """Store resolved dates on args for output path helpers that read ISO strings."""
    args.start_date = start_date.isoformat()
    args.end_date = end_date.isoformat()
    args.report_tz = report_tz
