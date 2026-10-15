from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Optional


def is_closed_unmerged_in_window(
    pr_created: Optional[datetime],
    merged_at: Optional[datetime],
    closed_at: Optional[datetime],
    *,
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
) -> bool:
    """True when a PR was opened in the calendar window and closed without merge before window end."""
    if pr_created is None or pr_created < start_inclusive_utc or pr_created >= end_exclusive_utc:
        return False
    if merged_at is not None:
        return False
    if closed_at is None or closed_at >= end_exclusive_utc:
        return False
    return True


def is_open_at_month_end(
    pr_created: Optional[datetime],
    merged_at: Optional[datetime],
    closed_at: Optional[datetime],
    *,
    end_exclusive_utc: datetime,
) -> bool:
    """
    True when a PR existed before month-end and was still open at that instant.

    Includes PRs created before or during the month. Excludes PRs merged or closed
    (without merge) before the window end.
    """
    if pr_created is None or pr_created >= end_exclusive_utc:
        return False
    if merged_at is not None and merged_at < end_exclusive_utc:
        return False
    if closed_at is not None and closed_at < end_exclusive_utc:
        return False
    return True


def counts_authored_in_window(
    pr_states: Dict[int, Dict[str, object]],
    *,
    start_utc: datetime,
    end_exclusive_utc: datetime,
) -> Dict[str, int]:
    """PRs opened (created) in the calendar window."""
    authored: Dict[str, int] = defaultdict(int)

    for state in pr_states.values():
        author = str(state.get("author") or "(unknown)")
        pr_created = state.get("pr_created")
        if not isinstance(pr_created, datetime):
            continue
        if pr_created < start_utc or pr_created >= end_exclusive_utc:
            continue
        authored[author] += 1

    return dict(authored)


def counts_merged_in_window(
    pr_states: Dict[int, Dict[str, object]],
    *,
    start_utc: datetime,
    end_exclusive_utc: datetime,
) -> Dict[str, int]:
    """PRs merged in the calendar window (any create date)."""
    merged: Dict[str, int] = defaultdict(int)

    for state in pr_states.values():
        author = str(state.get("author") or "(unknown)")
        merged_at = state.get("merged")
        if not isinstance(merged_at, datetime):
            continue
        if merged_at < start_utc or merged_at >= end_exclusive_utc:
            continue
        merged[author] += 1

    return dict(merged)


def counts_closed_unmerged_in_window(
    pr_states: Dict[int, Dict[str, object]],
    *,
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
) -> Dict[str, int]:
    """PRs opened in the calendar window and closed without merge before window end."""
    closed_unmerged: Dict[str, int] = defaultdict(int)

    for state in pr_states.values():
        author = str(state.get("author") or "(unknown)")
        pr_created = state.get("pr_created")
        merged_at = state.get("merged")
        closed_at = state.get("closed_at")
        if is_closed_unmerged_in_window(
            pr_created if isinstance(pr_created, datetime) else None,
            merged_at if isinstance(merged_at, datetime) else None,
            closed_at if isinstance(closed_at, datetime) else None,
            start_inclusive_utc=start_inclusive_utc,
            end_exclusive_utc=end_exclusive_utc,
        ):
            closed_unmerged[author] += 1

    return dict(closed_unmerged)


def counts_open_at_month_end(
    pr_states: Dict[int, Dict[str, object]],
    *,
    end_exclusive_utc: datetime,
) -> Dict[str, int]:
    open_at_end: Dict[str, int] = defaultdict(int)

    for state in pr_states.values():
        author = str(state.get("author") or "(unknown)")
        pr_created = state.get("pr_created")
        merged_at = state.get("merged")
        closed_at = state.get("closed_at")
        if is_open_at_month_end(
            pr_created if isinstance(pr_created, datetime) else None,
            merged_at if isinstance(merged_at, datetime) else None,
            closed_at if isinstance(closed_at, datetime) else None,
            end_exclusive_utc=end_exclusive_utc,
        ):
            open_at_end[author] += 1

    return dict(open_at_end)
