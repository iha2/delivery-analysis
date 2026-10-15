from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Callable, Optional

# The pure window logic lives in core.activity; re-exported so existing callers keep working.
from delivery_analysis.core.activity import (  # noqa: F401
    counts_authored_in_window,
    counts_closed_unmerged_in_window,
    counts_merged_in_window,
    counts_open_at_month_end,
    is_closed_unmerged_in_window,
    is_open_at_month_end,
)
from delivery_analysis.connectors.github.models import PullRequestRow
from delivery_analysis.connectors.github.pulls import PullRequestService
from delivery_analysis.core.time_utils import parse_github_ts


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
