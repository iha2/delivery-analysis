from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from github_analysis.analysis.authored_activity import (
    counts_authored_in_window,
    counts_closed_unmerged_in_window,
    counts_merged_in_window,
    counts_open_at_month_end,
)
from github_analysis.analysis.summaries import compute_user_summaries
from github_analysis.models import (
    PullRequestRow,
    ReportConfig,
    ReportResult,
    RepositoryRef,
)
from github_analysis.time_utils import parse_github_ts


def _dt_to_json(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def _dt_from_json(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return parse_github_ts(value)


def _row_to_dict(row: PullRequestRow) -> dict[str, Any]:
    data = asdict(row)
    for key in (
        "branch_start",
        "pr_created",
        "first_draft",
        "ready_for_review",
        "first_feedback",
        "approved",
        "merged",
        "closed_at",
    ):
        data[key] = _dt_to_json(data[key])
    return data


def _row_from_dict(data: dict[str, Any]) -> PullRequestRow:
    return PullRequestRow(
        author=data["author"],
        branch=data["branch"],
        pr_number=int(data["pr_number"]),
        pr_url=data["pr_url"],
        branch_start=_dt_from_json(data.get("branch_start")),
        pr_created=_dt_from_json(data.get("pr_created")),
        first_draft=_dt_from_json(data.get("first_draft")),
        ready_for_review=_dt_from_json(data.get("ready_for_review")),
        first_feedback=_dt_from_json(data.get("first_feedback")),
        approved=_dt_from_json(data.get("approved")),
        approved_by=data.get("approved_by", ""),
        merged=_dt_from_json(data.get("merged")),
        closed_at=_dt_from_json(data.get("closed_at")),
        notes=data.get("notes", ""),
        pr_files_total=int(data.get("pr_files_total", 0)),
        pr_files_added=int(data.get("pr_files_added", 0)),
        pr_files_modified=int(data.get("pr_files_modified", 0)),
        pr_files_removed=int(data.get("pr_files_removed", 0)),
        pr_commits_total=int(data.get("pr_commits_total", 0)),
        pr_commits_before_pr_open=data.get("pr_commits_before_pr_open"),
        pr_commits_after_pr_open=data.get("pr_commits_after_pr_open"),
    )


def _pr_states_to_json(states: dict[int, dict[str, object]]) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for pull_number, state in states.items():
        payload[str(pull_number)] = {
            "author": state.get("author", ""),
            "pr_created": _dt_to_json(
                state.get("pr_created") if isinstance(state.get("pr_created"), datetime) else None
            ),
            "merged": _dt_to_json(
                state.get("merged") if isinstance(state.get("merged"), datetime) else None
            ),
            "closed_at": _dt_to_json(
                state.get("closed_at") if isinstance(state.get("closed_at"), datetime) else None
            ),
        }
    return payload


def _pr_states_from_json(data: dict[str, dict[str, Any]]) -> dict[int, dict[str, object]]:
    states: dict[int, dict[str, object]] = {}
    for key, state in data.items():
        states[int(key)] = {
            "author": state.get("author", ""),
            "pr_created": _dt_from_json(state.get("pr_created")),
            "merged": _dt_from_json(state.get("merged")),
            "closed_at": _dt_from_json(state.get("closed_at")),
        }
    return states


def _legacy_merged_pr_states_from_rows(rows: list[PullRequestRow]) -> dict[int, dict[str, object]]:
    """Build merged PR states from detail rows for caches saved before merged_pr_states existed."""
    return {
        row.pr_number: {
            "author": row.author,
            "pr_created": row.pr_created,
            "merged": row.merged,
            "closed_at": row.closed_at,
        }
        for row in rows
    }


def _recompute_summaries(
    *,
    rows: list[PullRequestRow],
    review_counts: dict[str, int],
    approval_counts: dict[str, int],
    start_utc: Optional[datetime],
    end_exclusive_utc: Optional[datetime],
    created_pr_states: dict[int, dict[str, object]],
    open_pr_states: dict[int, dict[str, object]],
    merged_pr_states: dict[int, dict[str, object]],
) -> list:
    if start_utc is None or end_exclusive_utc is None:
        return compute_user_summaries(rows, review_counts, approval_counts)

    authored_counts = (
        counts_authored_in_window(
            created_pr_states,
            start_utc=start_utc,
            end_exclusive_utc=end_exclusive_utc,
        )
        if created_pr_states
        else {}
    )
    merged_in_month_counts = counts_merged_in_window(
        merged_pr_states,
        start_utc=start_utc,
        end_exclusive_utc=end_exclusive_utc,
    )
    open_at_end_counts = (
        counts_open_at_month_end(
            open_pr_states,
            end_exclusive_utc=end_exclusive_utc,
        )
        if open_pr_states
        else {}
    )
    closed_unmerged_counts = (
        counts_closed_unmerged_in_window(
            created_pr_states,
            start_inclusive_utc=start_utc,
            end_exclusive_utc=end_exclusive_utc,
        )
        if created_pr_states
        else {}
    )
    return compute_user_summaries(
        rows,
        review_counts,
        approval_counts,
        start_utc=start_utc,
        end_exclusive_utc=end_exclusive_utc,
        authored_in_month_by_user=authored_counts,
        merged_in_month_by_user=merged_in_month_counts,
        open_at_month_end_by_user=open_at_end_counts,
        closed_unmerged_in_window_by_user=closed_unmerged_counts,
    )


def save_raw_cache(
    path: str,
    *,
    result: ReportResult,
    activity_catalog: dict[int, str],
    review_catalog: dict[int, str],
    review_counts_by_user: dict[str, int],
    approval_counts_by_user: dict[str, int] | None = None,
    created_catalog: dict[int, str] | None = None,
    created_pr_states: dict[int, dict[str, object]] | None = None,
    open_pr_states: dict[int, dict[str, object]] | None = None,
    merged_pr_states: dict[int, dict[str, object]] | None = None,
) -> None:
    """Persist fetched GitHub data before writing TSV/Excel outputs."""
    config = result.config
    payload = {
        "version": 1,
        "config": {
            "repository": {
                "owner": config.repository.owner,
                "name": config.repository.name,
            },
            "start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "report_tz": config.report_tz.key,
            "merged_only": config.merged_only,
        },
        "start_utc": _dt_to_json(result.start_utc),
        "end_exclusive_utc": _dt_to_json(result.end_exclusive_utc),
        "activity_catalog": {str(k): v for k, v in activity_catalog.items()},
        "created_catalog": {str(k): v for k, v in (created_catalog or {}).items()},
        "created_pr_states": _pr_states_to_json(created_pr_states or {}),
        "open_pr_states": _pr_states_to_json(open_pr_states or {}),
        "merged_pr_states": _pr_states_to_json(merged_pr_states or {}),
        "review_catalog": {str(k): v for k, v in review_catalog.items()},
        "review_counts_by_user": review_counts_by_user,
        "approval_counts_by_user": approval_counts_by_user or {},
        "skipped_pr_numbers": result.skipped_pr_numbers,
        "rows": [_row_to_dict(row) for row in result.rows],
        "summaries": [asdict(summary) for summary in result.summaries],
    }
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_raw_cache(path: str) -> ReportResult:
    """Rebuild ReportResult from a saved raw JSON cache."""
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    cfg = payload["config"]
    config = ReportConfig(
        repository=RepositoryRef(owner=cfg["repository"]["owner"], name=cfg["repository"]["name"]),
        start_date=date.fromisoformat(cfg["start_date"]),
        end_date=date.fromisoformat(cfg["end_date"]),
        report_tz=ZoneInfo(cfg["report_tz"]),
        merged_only=bool(cfg.get("merged_only", False)),
    )
    rows = [_row_from_dict(row) for row in payload.get("rows", [])]
    review_counts = {
        key: int(value) for key, value in (payload.get("review_counts_by_user") or {}).items()
    }
    approval_counts = {
        key: int(value) for key, value in (payload.get("approval_counts_by_user") or {}).items()
    }
    start_utc = _dt_from_json(payload.get("start_utc"))
    end_exclusive_utc = _dt_from_json(payload.get("end_exclusive_utc"))
    created_pr_states = _pr_states_from_json(payload.get("created_pr_states") or {})
    open_pr_states = _pr_states_from_json(payload.get("open_pr_states") or {})
    merged_pr_states = _pr_states_from_json(payload.get("merged_pr_states") or {})
    if not open_pr_states:
        open_pr_states = created_pr_states
    if not merged_pr_states:
        merged_pr_states = _legacy_merged_pr_states_from_rows(rows)
    summaries = _recompute_summaries(
        rows=rows,
        review_counts=review_counts,
        approval_counts=approval_counts,
        start_utc=start_utc,
        end_exclusive_utc=end_exclusive_utc,
        created_pr_states=created_pr_states,
        open_pr_states=open_pr_states,
        merged_pr_states=merged_pr_states,
    )
    return ReportResult(
        config=config,
        rows=rows,
        summaries=summaries,
        skipped_pr_numbers=[int(n) for n in payload.get("skipped_pr_numbers", [])],
        start_utc=start_utc,
        end_exclusive_utc=end_exclusive_utc,
    )
