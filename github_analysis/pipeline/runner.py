from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any, Optional

from github_analysis.analysis.authored_activity import (
    build_pr_states,
    counts_authored_in_window,
    counts_closed_unmerged_in_window,
    counts_merged_in_window,
    counts_open_at_month_end,
)
from github_analysis.analysis.pr_builder import build_pull_request_row
from github_analysis.analysis.reviews import (
    collect_approval_counts_by_user,
    collect_review_counts_by_user,
)
from github_analysis.analysis.summaries import compute_user_summaries
from github_analysis.cache.raw_store import save_raw_cache
from github_analysis.catalog.search import (
    build_activity_catalog,
    build_created_in_window_catalog,
    build_merged_in_window_catalog,
    build_open_at_month_end_candidate_catalog,
    build_review_catalog,
    group_prs_by_user,
)
from github_analysis.config import DEFAULT_FETCH_WORKERS
from github_analysis.github.client import GhClient
from github_analysis.github.pulls import PullRequestService
from github_analysis.logging.run_log import RunLog
from github_analysis.models import PullRequestRow, ReportConfig, ReportResult, RepositoryRef
from github_analysis.time_utils import iso_utc_z, window_bounds_utc


def _log_person_coverage(
    log: RunLog,
    *,
    activity_catalog: dict[int, str],
    rows: list,
    summaries: list,
    skipped: list[int],
) -> None:
    authors_in_catalog = sorted({login or "(unknown)" for login in activity_catalog.values()}, key=str.lower)
    authors_in_rows = sorted({row.author for row in rows}, key=str.lower)
    summary_users = sorted((summary.user for summary in summaries), key=str.lower)

    log.info(f"Individual summary rows: {len(summaries)}")
    log.info(f"PR authors in catalog: {len(authors_in_catalog)}")
    log.info(f"PR authors with detail rows: {len(authors_in_rows)}")
    if skipped:
        log.warn(f"Skipped PR numbers ({len(skipped)}): {', '.join(str(n) for n in skipped)}")

    missing_rows = sorted(set(authors_in_catalog) - set(authors_in_rows), key=str.lower)
    if missing_rows:
        log.warn(
            "Authors in catalog without detail rows (likely all PRs skipped): "
            + ", ".join(missing_rows)
        )

    reviewers_only = sorted(set(summary_users) - set(authors_in_rows), key=str.lower)
    if reviewers_only:
        log.info(
            "Users in summary with reviews but no authored PR rows: "
            + ", ".join(reviewers_only)
        )

    log.info("Person-level metrics:")
    for summary in sorted(summaries, key=lambda item: item.user.lower()):
        log.info(
            "  "
            f"{summary.user}: "
            f"merged={summary.prs_merged}, "
            f"reviewed={summary.prs_reviewed}, "
            f"approved={summary.prs_approved}, "
            f"authored={summary.prs_authored}, "
            f"open_at_month_end={summary.prs_open}, "
            f"closed_unmerged={summary.prs_closed_unmerged}, "
            f"avg_hours_pr_created_to_merged={summary.avg_hours_pr_created_to_merged or '-'}, "
            f"min_hours_pr_created_to_merged={summary.min_hours_pr_created_to_merged or '-'}, "
            f"max_hours_pr_created_to_merged={summary.max_hours_pr_created_to_merged or '-'}, "
            f"avg_files_added_per_pr={summary.avg_files_added_per_pr or '-'}, "
            f"avg_files_changed_per_pr={summary.avg_files_changed_per_pr or '-'}"
        )


def _fetch_pr_detail(
    repository: RepositoryRef,
    pull_number: int,
    report_author: str,
) -> tuple[int, Optional[PullRequestRow], list[dict[str, Any]], Optional[str]]:
    try:
        service = PullRequestService(GhClient(), repository)
        row, reviews = build_pull_request_row(
            service, pull_number, report_author=report_author
        )
        return pull_number, row, reviews, None
    except Exception as exc:
        return pull_number, None, [], str(exc)


def _fetch_pr_details(
    *,
    repository: RepositoryRef,
    grouped: list[tuple[str, list[int]]],
    workers: int,
    emit,
    emit_error,
) -> tuple[list[PullRequestRow], dict[int, list[dict[str, Any]]], list[int]]:
    tasks: list[tuple[int, str]] = []
    for author, pr_numbers in grouped:
        for pull_number in pr_numbers:
            tasks.append((pull_number, author))

    total_prs = len(tasks)
    rows: list[PullRequestRow] = []
    reviews_cache: dict[int, list[dict[str, Any]]] = {}
    skipped: list[int] = []

    if total_prs == 0:
        return rows, reviews_cache, skipped

    if workers <= 1:
        emit("Phase 2: fetching pull request details (serial)")
        for index, (pull_number, author) in enumerate(tasks, start=1):
            emit(f"[{index}/{total_prs}] PR #{pull_number} ({author})")
            _, row, reviews, error = _fetch_pr_detail(repository, pull_number, author)
            if error:
                skipped.append(pull_number)
                emit_error(f"Skip PR #{pull_number} ({author}): {error}")
            elif row is not None:
                rows.append(row)
                reviews_cache[pull_number] = reviews
        rows.sort(key=lambda item: item.pr_number)
        skipped.sort()
        return rows, reviews_cache, skipped

    emit(f"Phase 2: fetching pull request details ({workers} workers)")
    completed = 0
    lock = Lock()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_task = {
            executor.submit(_fetch_pr_detail, repository, pull_number, author): (
                pull_number,
                author,
            )
            for pull_number, author in tasks
        }
        for future in as_completed(future_to_task):
            pull_number, author = future_to_task[future]
            _, row, reviews, error = future.result()
            with lock:
                completed += 1
                if error:
                    skipped.append(pull_number)
                    emit_error(f"Skip PR #{pull_number} ({author}): {error}")
                elif row is not None:
                    rows.append(row)
                    reviews_cache[pull_number] = reviews
                emit(f"[{completed}/{total_prs}] PR #{pull_number} ({author})")

    rows.sort(key=lambda item: item.pr_number)
    skipped.sort()
    return rows, reviews_cache, skipped


def run_report(
    config: ReportConfig,
    *,
    log: Optional[RunLog] = None,
    raw_cache_path: Optional[str] = None,
    workers: int = DEFAULT_FETCH_WORKERS,
) -> ReportResult:
    """Collect PR detail rows and per-person summaries for one repository."""
    emit = log.info if log else lambda msg: None
    emit_warn = log.warn if log else lambda msg: None
    emit_error = log.error if log else lambda msg: None

    if workers < 1:
        raise ValueError("--workers must be at least 1")

    client = GhClient()
    service = PullRequestService(client, config.repository)
    start_utc, end_exclusive_utc = window_bounds_utc(
        config.start_date, config.end_date, config.report_tz
    )

    emit(f"Repository: {config.repository.slug}")
    emit(
        f"Report timezone: {config.report_tz.key} — window "
        f"{config.start_date.isoformat()} .. {config.end_date.isoformat()} "
        f"(UTC {iso_utc_z(start_utc)} .. {iso_utc_z(end_exclusive_utc)})"
    )
    if config.merged_only:
        emit("Mode: merged PRs only")
    emit(f"Fetch workers: {workers}")

    emit("Phase 1: discovering pull requests")
    search_warnings: list[str] = []
    try:
        activity_catalog, activity_warnings = build_activity_catalog(
            client,
            config.repository,
            config.start_date,
            config.end_date,
            merged_only=config.merged_only,
        )
        search_warnings.extend(activity_warnings)
        review_catalog, review_warnings = build_review_catalog(
            client,
            config.repository,
            config.start_date,
            config.end_date,
            activity_catalog=activity_catalog,
        )
        search_warnings.extend(review_warnings)
        created_catalog, created_warnings = build_created_in_window_catalog(
            client,
            config.repository,
            config.start_date,
            config.end_date,
        )
        search_warnings.extend(created_warnings)
        merged_catalog, merged_warnings = build_merged_in_window_catalog(
            client,
            config.repository,
            config.start_date,
            config.end_date,
        )
        search_warnings.extend(merged_warnings)
        open_candidate_catalog, open_warnings = build_open_at_month_end_candidate_catalog(
            client,
            config.repository,
            config.start_date,
            config.end_date,
        )
        search_warnings.extend(open_warnings)
    except Exception as exc:
        emit_error(f"GitHub search failed: {exc}")
        raise

    for warning in search_warnings:
        emit_warn(warning)

    authors = sorted({login or "(unknown)" for login in activity_catalog.values()}, key=str.lower)
    emit(
        f"Phase 1 complete: {len(activity_catalog)} activity PR(s), "
        f"{len(created_catalog)} created-in-window PR(s), "
        f"{len(merged_catalog)} merged-in-window PR(s), "
        f"{len(open_candidate_catalog)} open-at-month-end candidate PR(s), "
        f"{len(review_catalog)} PR(s) for review scan, {len(authors)} PR author(s)"
    )
    for author in authors:
        emit(f"  catalog author: {author}")
    if not authors:
        emit_warn("No PRs matched the date window and filters")

    grouped = group_prs_by_user(activity_catalog)
    rows, reviews_cache, skipped = _fetch_pr_details(
        repository=config.repository,
        grouped=grouped,
        workers=workers,
        emit=emit,
        emit_error=emit_error,
    )

    emit("Phase 3: building individual person summary")
    try:
        review_counts = collect_review_counts_by_user(
            service,
            list(review_catalog.keys()),
            start_utc,
            end_exclusive_utc,
            reviews_cache=reviews_cache,
        )
        approval_counts = collect_approval_counts_by_user(
            service,
            list(review_catalog.keys()),
            start_utc,
            end_exclusive_utc,
            reviews_cache=reviews_cache,
        )
    except Exception as exc:
        emit_error(f"Review aggregation failed: {exc}")
        raise

    emit("Phase 3b: authored, merged-in-window, and open-at-month-end counts")
    rows_by_pr = {row.pr_number: row for row in rows}
    try:
        created_pr_states = build_pr_states(
            service,
            created_catalog,
            rows_by_pr,
            workers=workers,
            emit=emit,
            emit_error=emit_error,
            progress_label="created",
        )
        open_pr_states = build_pr_states(
            service,
            open_candidate_catalog,
            rows_by_pr,
            workers=workers,
            emit=emit,
            emit_error=emit_error,
            progress_label="open-candidate",
        )
        merged_pr_states = build_pr_states(
            service,
            merged_catalog,
            rows_by_pr,
            workers=workers,
            emit=emit,
            emit_error=emit_error,
            progress_label="merged",
        )
        authored_counts = counts_authored_in_window(
            created_pr_states,
            start_utc=start_utc,
            end_exclusive_utc=end_exclusive_utc,
        )
        merged_in_month_counts = counts_merged_in_window(
            merged_pr_states,
            start_utc=start_utc,
            end_exclusive_utc=end_exclusive_utc,
        )
        open_at_end_counts = counts_open_at_month_end(
            open_pr_states,
            end_exclusive_utc=end_exclusive_utc,
        )
        closed_unmerged_counts = counts_closed_unmerged_in_window(
            created_pr_states,
            start_inclusive_utc=start_utc,
            end_exclusive_utc=end_exclusive_utc,
        )
        created_pr_states.update(
            {
                number: state
                for number, state in open_pr_states.items()
                if number not in created_pr_states
            }
        )
    except Exception as exc:
        emit_error(f"Authored/open-at-month-end aggregation failed: {exc}")
        raise

    summaries = compute_user_summaries(
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
    emit(
        f"Fetch complete: {len(rows)} detail row(s); {len(summaries)} person row(s); "
        f"skipped {len(skipped)} PR(s)"
    )

    result = ReportResult(
        config=config,
        rows=rows,
        summaries=summaries,
        skipped_pr_numbers=skipped,
        start_utc=start_utc,
        end_exclusive_utc=end_exclusive_utc,
    )

    if log:
        _log_person_coverage(
            log,
            activity_catalog=activity_catalog,
            rows=rows,
            summaries=summaries,
            skipped=skipped,
        )

    if raw_cache_path:
        save_raw_cache(
            raw_cache_path,
            result=result,
            activity_catalog=activity_catalog,
            created_catalog=created_catalog,
            created_pr_states=created_pr_states,
            open_pr_states=open_pr_states,
            merged_pr_states=merged_pr_states,
            review_catalog=review_catalog,
            review_counts_by_user=review_counts,
            approval_counts_by_user=approval_counts,
        )
        emit(f"Raw cache saved: {raw_cache_path}")

    return result
