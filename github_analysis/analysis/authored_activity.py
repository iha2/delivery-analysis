from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from threading import Lock
from typing import Callable, Optional

from github_analysis.github.pulls import PullRequestService
from github_analysis.models import PullRequestRow
from github_analysis.time_utils import parse_github_ts


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


def pr_state_from_row(row: PullRequestRow) -> dict[str, object]:
    return {
        "author": row.author,
        "pr_created": row.pr_created,
        "merged": row.merged,
        "closed_at": row.closed_at,
    }


def fetch_pr_state(service: PullRequestService, pull_number: int) -> dict[str, object]:
    detail = service.detail(pull_number)
    return {
        "author": ((detail.get("user") or {}).get("login")) or "",
        "pr_created": parse_github_ts(detail.get("created_at")),
        "merged": parse_github_ts(detail.get("merged_at")),
        "closed_at": parse_github_ts(detail.get("closed_at")),
    }


def _fetch_pr_state_safe(
    service: PullRequestService, pull_number: int
) -> tuple[int, Optional[dict[str, object]], Optional[str]]:
    try:
        return pull_number, fetch_pr_state(service, pull_number), None
    except Exception as exc:
        return pull_number, None, str(exc)


def build_pr_states(
    service: PullRequestService,
    catalog: dict[int, str],
    rows_by_pr: dict[int, PullRequestRow],
    *,
    workers: int,
    emit: Callable[[str], None],
    emit_error: Callable[[str], None],
    progress_label: str,
) -> dict[int, dict[str, object]]:
    """Resolve created/merged/closed timestamps for PRs in a search catalog."""
    states: dict[int, dict[str, object]] = {}
    for pull_number, login in catalog.items():
        row = rows_by_pr.get(pull_number)
        if row is not None:
            states[pull_number] = pr_state_from_row(row)
        else:
            states[pull_number] = {
                "author": login,
                "pr_created": None,
                "merged": None,
                "closed_at": None,
            }

    missing = sorted(number for number in catalog if number not in rows_by_pr)
    if not missing:
        return states

    emit(f"Fetching {progress_label} state for {len(missing)} PR(s) not in detail report")

    if workers <= 1:
        for index, pull_number in enumerate(missing, start=1):
            emit(f"[{progress_label} {index}/{len(missing)}] PR #{pull_number}")
            _, state, error = _fetch_pr_state_safe(service, pull_number)
            if error:
                emit_error(f"Skip {progress_label} PR #{pull_number}: {error}")
            elif state is not None:
                states[pull_number] = state
        return states

    completed = 0
    lock = Lock()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_pr_state_safe, service, pull_number): pull_number
            for pull_number in missing
        }
        for future in as_completed(futures):
            pull_number = futures[future]
            _, state, error = future.result()
            with lock:
                completed += 1
                if error:
                    emit_error(f"Skip {progress_label} PR #{pull_number}: {error}")
                elif state is not None:
                    states[pull_number] = state
                emit(f"[{progress_label} {completed}/{len(missing)}] PR #{pull_number}")

    return states


def counts_authored_in_window(
    pr_states: dict[int, dict[str, object]],
    *,
    start_utc: datetime,
    end_exclusive_utc: datetime,
) -> dict[str, int]:
    """PRs opened (created) in the calendar window."""
    authored: dict[str, int] = defaultdict(int)

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
    pr_states: dict[int, dict[str, object]],
    *,
    start_utc: datetime,
    end_exclusive_utc: datetime,
) -> dict[str, int]:
    """PRs merged in the calendar window (any create date)."""
    merged: dict[str, int] = defaultdict(int)

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
    pr_states: dict[int, dict[str, object]],
    *,
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
) -> dict[str, int]:
    """PRs opened in the calendar window and closed without merge before window end."""
    closed_unmerged: dict[str, int] = defaultdict(int)

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
    pr_states: dict[int, dict[str, object]],
    *,
    end_exclusive_utc: datetime,
) -> dict[str, int]:
    open_at_end: dict[str, int] = defaultdict(int)

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
