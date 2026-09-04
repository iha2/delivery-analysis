from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, TextIO
from zoneinfo import ZoneInfo

from github_analysis.models import PullRequestRow, ReportConfig, UserSummary
from github_analysis.time_utils import format_report_ts, hours_between, hours_since


def _ts_pair(
    branch_start: Optional[datetime], event: Optional[datetime], report_tz: ZoneInfo
) -> tuple[str, str]:
    if branch_start is None:
        return format_report_ts(event, report_tz), ""
    return format_report_ts(event, report_tz), hours_since(branch_start, event)


def write_detail_tsv(result_rows: list[PullRequestRow], fh: TextIO, config: ReportConfig) -> None:
    repository = config.repository
    tz_key = config.report_tz.key
    start_date = config.start_date.isoformat()
    end_date = config.end_date.isoformat()

    fh.write(
        f"GitHub PR timeline — {repository.slug} — calendar window {start_date} .. "
        f"{end_date} (end date exclusive) — event times {tz_key}\n"
    )
    fh.write(
        f"Datetime columns in the table below are local wall-clock in {tz_key} (ISO-8601 with offset). "
        "Hour/delta columns are decimal elapsed hours. Row 3 is the column header; rows 1–2 are notes.\n"
    )

    headers = [
        "pr_creator",
        "head_branch",
        "pr_number",
        "notes",
        "pr_url",
        "branch_start",
        "branch_start_hours_since_branch",
        "pr_created",
        "pr_created_hours_since_branch",
        "first_draft",
        "first_draft_hours_since_branch",
        "ready_for_review",
        "ready_for_review_hours_since_branch",
        "first_feedback",
        "first_feedback_hours_since_branch",
        "approved",
        "approved_hours_since_branch",
        "approved_by",
        "merged",
        "merged_hours_since_branch",
        "hours_pr_created_to_first_feedback",
        "hours_pr_created_to_approved",
        "hours_pr_created_to_closed",
        "pr_files_total",
        "pr_files_added",
        "pr_files_modified",
        "pr_files_removed",
        "pr_commits_total",
        "pr_commits_before_pr_open",
        "pr_commits_after_pr_open",
    ]
    fh.write("\t".join(headers) + "\n")

    for row in result_rows:
        branch_start = row.branch_start
        pr_created = row.pr_created
        line = [
            row.author,
            row.branch,
            str(row.pr_number),
            row.notes,
            row.pr_url,
            *_ts_pair(branch_start, branch_start, config.report_tz),
            *_ts_pair(branch_start, pr_created, config.report_tz),
            *_ts_pair(branch_start, row.first_draft, config.report_tz),
            *_ts_pair(branch_start, row.ready_for_review, config.report_tz),
            *_ts_pair(branch_start, row.first_feedback, config.report_tz),
            *_ts_pair(branch_start, row.approved, config.report_tz),
            row.approved_by,
            *_ts_pair(branch_start, row.merged, config.report_tz),
            hours_between(pr_created, row.first_feedback),
            hours_between(pr_created, row.approved),
            hours_between(pr_created, row.closed_at),
            str(row.pr_files_total),
            str(row.pr_files_added),
            str(row.pr_files_modified),
            str(row.pr_files_removed),
            str(row.pr_commits_total),
            "" if row.pr_commits_before_pr_open is None else str(row.pr_commits_before_pr_open),
            "" if row.pr_commits_after_pr_open is None else str(row.pr_commits_after_pr_open),
        ]
        fh.write("\t".join(line) + "\n")

    fh.write(
        f"END NOTES — All datetime columns above use IANA timezone {tz_key}. "
        f"Repository {repository.slug} only.\n"
    )
    fh.write(
        "END NOTES — For a clean table in Excel you may delete this line and the line above, "
        "plus the two title lines at the top of the file.\n"
    )


def write_summary_tsv(summaries: list[UserSummary], fh: TextIO, config: ReportConfig) -> None:
    repository = config.repository
    tz_key = config.report_tz.key
    start_date = config.start_date.isoformat()
    end_date = config.end_date.isoformat()

    fh.write(
        f"GitHub individual production summary — {repository.slug} — calendar window {start_date} .. "
        f"{end_date} (end date exclusive) — report timezone {tz_key}\n"
    )
    fh.write(
        "One row per person (GitHub login) for individual production evaluation. "
        "PR counts: prs_merged = PRs they authored that merged; prs_reviewed = distinct PRs they reviewed; "
        "prs_approved = distinct PRs where they submitted an APPROVED review. "
        "prs_authored = PRs they opened in the calendar window; prs_open = PRs still open at month-end "
        "(existed before window end; not merged or closed unmerged before window end — any create date); "
        "prs_closed_unmerged = PRs they opened in the calendar window and closed without merge before window end. "
        "File columns are means per authored PR (not repo-wide totals): "
        "avg_files_added_per_pr = new files; avg_files_changed_per_pr = modified/renamed files "
        "(excludes new files and deletions). "
        "min/max/avg_hours_pr_created_to_merged = hours from PR open to merge on PRs merged in the window only "
        "(excludes prs_open / still-open-at-month-end PRs). "
        "Blank when the person authored no merged PRs in the window.\n"
    )
    headers = [
        "user",
        "prs_merged",
        "prs_reviewed",
        "prs_approved",
        "prs_authored",
        "prs_open",
        "prs_closed_unmerged",
        "avg_files_added_per_pr",
        "avg_files_changed_per_pr",
        "min_hours_pr_created_to_merged",
        "max_hours_pr_created_to_merged",
        "avg_hours_pr_created_to_merged",
    ]
    fh.write("\t".join(headers) + "\n")
    for summary in summaries:
        fh.write(
            "\t".join(
                [
                    summary.user,
                    str(summary.prs_merged),
                    str(summary.prs_reviewed),
                    str(summary.prs_approved),
                    str(summary.prs_authored),
                    str(summary.prs_open),
                    str(summary.prs_closed_unmerged),
                    summary.avg_files_added_per_pr,
                    summary.avg_files_changed_per_pr,
                    summary.min_hours_pr_created_to_merged,
                    summary.max_hours_pr_created_to_merged,
                    summary.avg_hours_pr_created_to_merged,
                ]
            )
            + "\n"
        )
    fh.write(
        f"END NOTES — Window and timezone match the detail report ({tz_key}). "
        f"Repository {repository.slug} only.\n"
    )
