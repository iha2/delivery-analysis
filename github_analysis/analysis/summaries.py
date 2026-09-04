from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from github_analysis.models import PullRequestRow, UserSummary


def _hours_created_to_merged(row: PullRequestRow) -> float | None:
    if row.pr_created is None or row.merged is None:
        return None
    return (row.merged - row.pr_created).total_seconds() / 3600.0


def _format_hours(value: float) -> str:
    return f"{value:.2f}"


def _merged_in_window(
    row: PullRequestRow,
    *,
    start_utc: datetime,
    end_exclusive_utc: datetime,
) -> bool:
    if row.merged is None:
        return False
    return start_utc <= row.merged < end_exclusive_utc


def _merge_cycle_stats(
    rows: list[PullRequestRow],
    *,
    start_utc: datetime | None = None,
    end_exclusive_utc: datetime | None = None,
) -> tuple[str, str, str]:
    """
    Min, max, and mean hours from PR open to merge.

    Only PRs merged in the calendar window count. PRs still open at month-end
    (prs_open) and PRs merged after the window are excluded.
    """
    hours: list[float] = []
    for row in rows:
        value = _hours_created_to_merged(row)
        if value is None:
            continue
        if start_utc is not None and end_exclusive_utc is not None:
            if not _merged_in_window(
                row, start_utc=start_utc, end_exclusive_utc=end_exclusive_utc
            ):
                continue
        hours.append(value)
    if not hours:
        return "", "", ""
    return (
        _format_hours(min(hours)),
        _format_hours(max(hours)),
        _format_hours(sum(hours) / len(hours)),
    )


def compute_user_summaries(
    rows: list[PullRequestRow],
    review_counts_by_user: dict[str, int],
    approval_counts_by_user: dict[str, int],
    *,
    start_utc: datetime | None = None,
    end_exclusive_utc: datetime | None = None,
    authored_in_month_by_user: dict[str, int] | None = None,
    merged_in_month_by_user: dict[str, int] | None = None,
    open_at_month_end_by_user: dict[str, int] | None = None,
    closed_unmerged_in_window_by_user: dict[str, int] | None = None,
) -> list[UserSummary]:
    """Roll up PR creator, reviewer, and approver metrics to one row per GitHub login."""
    by_creator: dict[str, list[PullRequestRow]] = defaultdict(list)
    for row in rows:
        by_creator[row.author or "(unknown)"].append(row)

    all_users = sorted(
        set(by_creator.keys())
        | set(review_counts_by_user.keys())
        | set(approval_counts_by_user.keys())
        | set((authored_in_month_by_user or {}).keys())
        | set((open_at_month_end_by_user or {}).keys())
        | set((closed_unmerged_in_window_by_user or {}).keys()),
        key=str.lower,
    )
    summaries: list[UserSummary] = []
    for user in all_users:
        detail_rows = by_creator.get(user, [])
        if merged_in_month_by_user is not None:
            merged = merged_in_month_by_user.get(user, 0)
        else:
            merged = sum(1 for row in detail_rows if row.merged is not None)
        if authored_in_month_by_user is not None:
            authored_count = authored_in_month_by_user.get(user, 0)
            open_count = (open_at_month_end_by_user or {}).get(user, 0)
            closed_unmerged_count = (closed_unmerged_in_window_by_user or {}).get(user, 0)
        else:
            authored_count = len(detail_rows)
            open_count = len(detail_rows) - merged
            closed_unmerged_count = 0
        if detail_rows:
            avg_added = sum(row.pr_files_added for row in detail_rows) / len(detail_rows)
            avg_modified = sum(row.pr_files_modified for row in detail_rows) / len(detail_rows)
            avg_added_s = f"{avg_added:.2f}"
            avg_modified_s = f"{avg_modified:.2f}"
        else:
            avg_added_s = ""
            avg_modified_s = ""
        min_hours, max_hours, avg_hours = _merge_cycle_stats(
            detail_rows,
            start_utc=start_utc,
            end_exclusive_utc=end_exclusive_utc,
        )
        summaries.append(
            UserSummary(
                user=user,
                prs_merged=merged,
                prs_reviewed=review_counts_by_user.get(user, 0),
                prs_approved=approval_counts_by_user.get(user, 0),
                prs_authored=authored_count,
                prs_open=open_count,
                prs_closed_unmerged=closed_unmerged_count,
                avg_files_added_per_pr=avg_added_s,
                avg_files_changed_per_pr=avg_modified_s,
                min_hours_pr_created_to_merged=min_hours,
                max_hours_pr_created_to_merged=max_hours,
                avg_hours_pr_created_to_merged=avg_hours,
            )
        )
    return summaries
