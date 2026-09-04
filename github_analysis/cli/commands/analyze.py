from __future__ import annotations

import argparse
import os
import sys

from github_analysis.cache.raw_store import load_raw_cache
from github_analysis.cli.output_dir import add_output_dir_argument, apply_output_dir
from github_analysis.cli.report_window import (
    add_period_args,
    apply_resolved_window_to_args,
    date_window_note,
    resolve_report_window,
)
from github_analysis.config import DEFAULT_GITHUB_OWNER, DEFAULT_FETCH_WORKERS, OUTPUT_DIR_ENV_VAR, default_output_dir
from github_analysis.export.paths import (
    default_detail_path,
    sibling_paths_from_detail,
    summary_path_from_detail,
)
from github_analysis.export.tsv import write_detail_tsv, write_summary_tsv
from github_analysis.github.preflight import run_preflight
from github_analysis.logging.run_log import RunLog
from github_analysis.models import ReportConfig
from github_analysis.pipeline.runner import run_report
from github_analysis.repo import resolve_repository

MERGED_ONLY_HELP = (
    "PR detail sheet: merged-in-window PRs only. Person summary still includes "
    "authored, open-at-window-end, closed-unmerged, and review counts"
)

FROM_CACHE_HELP = (
    "Skip GitHub fetch; rebuild TSV from *_raw.json. Metrics use the cache's repo "
    "and date window; --repo and --month (or --start-date/--end-date) affect output "
    "paths only. --workers is ignored"
)

OUTPUT_FILES_EPILOG = (
    "Output files (default names include start and end dates):\n"
    f"  {{repo}}_{{start}}_to_{{end}}.tsv\n"
    f"  {{repo}}_{{start}}_to_{{end}}_person_summary.tsv\n"
    f"  {{repo}}_{{start}}_to_{{end}}_raw.json  (written on fresh fetch only)\n"
    f"  {{repo}}_{{start}}_to_{{end}}_run.log\n"
            f"  Default directory: {default_output_dir()} "
            f"(see --output-dir and {OUTPUT_DIR_ENV_VAR})\n"
)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "analyze",
        help="Fetch GitHub data and write TSV reports",
        description=(
            "Analyze pull-request activity for one repository and write tab-separated reports. "
            "Produces a per-person summary and optional per-PR detail file.\n\n"
            f"{date_window_note()}."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_examples(),
    )
    _add_repo_args(parser)
    add_period_args(parser)
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help=(
            f"Detail TSV path. Default: {{output-dir}}/{{repo}}_{{start}}_to_{{end}}.tsv "
            "(date range in the name; sibling summary, cache, and log files share this stem). "
            "Use - for stdout."
        ),
    )
    parser.add_argument(
        "--summary-output",
        metavar="PATH",
        help="Person-level summary TSV path. Default: detail path with _person_summary suffix.",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip the per-person summary file",
    )
    parser.add_argument(
        "--merged-only",
        action="store_true",
        help=MERGED_ONLY_HELP,
    )
    add_output_dir_argument(parser)
    parser.add_argument(
        "--from-cache",
        metavar="PATH",
        help=FROM_CACHE_HELP,
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_FETCH_WORKERS,
        metavar="N",
        help=(
            f"Parallel workers for Phase 2 PR detail fetch (default: {DEFAULT_FETCH_WORKERS}). "
            "Use 1 for serial fetch."
        ),
    )
    parser.set_defaults(handler=run)


def _add_repo_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo",
        required=True,
        help="Repository: HTTPS/SSH URL, owner/name, or short name",
    )
    parser.add_argument(
        "--owner",
        default="",
        help=f"Org/user when --repo is a short name only (default: {DEFAULT_GITHUB_OWNER!r})",
    )


def _examples() -> str:
    return (
        f"{OUTPUT_FILES_EPILOG}\n"
        "Examples:\n"
        "  # All of May 2026 (shorthand):\n"
        "  github-analysis analyze --repo global-services --month 2026-05 --merged-only\n"
        "  # Same window with explicit dates:\n"
        "  github-analysis analyze --repo global-services --start-date 2026-05-01 --end-date 2026-06-01\n"
        "  # May 15 through month end (separate output files from a full-month run):\n"
        "  github-analysis analyze --repo global-services --start-date 2026-05-15 --end-date 2026-06-01 --merged-only\n"
        "  # Rebuild TSV from cache (pass --month or dates for output naming):\n"
        "  github-analysis analyze --from-cache ~/Documents/global-services_2026-05-01_to_2026-06-01_raw.json \\\n"
        "    --repo global-services --month 2026-05\n\n"
        "Large repos: GitHub search returns at most 1,000 matches per query. "
        "Split the date window if the run log warns about truncation."
    )


def _resolve_detail_path(args: argparse.Namespace, repository_name: str) -> str | None:
    output_dir = os.path.expanduser(args.output_dir)
    if args.output is None:
        return default_detail_path(
            repository_name, args.start_date, args.end_date, output_dir=output_dir
        )
    if args.output == "-":
        return None
    return os.path.expanduser(args.output)


def run(args: argparse.Namespace) -> int:
    apply_output_dir(args)
    try:
        repository = resolve_repository(args.repo, args.owner)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        start_date, end_date, report_tz = resolve_report_window(args)
        apply_resolved_window_to_args(args, start_date, end_date, report_tz)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if getattr(args, "workers", DEFAULT_FETCH_WORKERS) < 1:
        print("Error: --workers must be at least 1", file=sys.stderr)
        return 2

    detail_path = _resolve_detail_path(args, repository.name)
    if detail_path:
        paths = sibling_paths_from_detail(detail_path)
        log_path = paths["run_log"]
        raw_cache_path = paths["raw_cache"]
    else:
        log_path = None
        raw_cache_path = None

    config = ReportConfig(
        repository=repository,
        start_date=start_date,
        end_date=end_date,
        report_tz=report_tz,
        merged_only=args.merged_only,
        include_summary=not args.no_summary,
    )

    if detail_path and log_path:
        with RunLog(log_path) as log:
            return _execute(args, config, detail_path, raw_cache_path, log)
    return _execute(args, config, detail_path, raw_cache_path, None)


def _execute(
    args: argparse.Namespace,
    config: ReportConfig,
    detail_path: str | None,
    raw_cache_path: str | None,
    log: RunLog | None,
) -> int:
    emit = log.info if log else lambda msg: None
    emit_error = log.error if log else lambda msg: print(f"Error: {msg}", file=sys.stderr)

    try:
        if getattr(args, "from_cache", None):
            cache_path = os.path.expanduser(args.from_cache)
            emit(f"Loading raw cache: {cache_path}")
            result = load_raw_cache(cache_path)
            config = result.config
        else:
            if log and not run_preflight(config.repository, log):
                return 1
            result = run_report(
                config,
                log=log,
                raw_cache_path=raw_cache_path,
                workers=args.workers,
            )
    except Exception as exc:
        emit_error(str(exc))
        return 1

    if detail_path is None:
        write_detail_tsv(result.rows, sys.stdout, config)
        if not args.no_summary:
            emit_error("Person summary is not written when detail output is stdout (-o -).")
        return 0

    os.makedirs(os.path.dirname(detail_path) or ".", exist_ok=True)
    emit(f"Writing detail TSV: {detail_path}")
    with open(detail_path, "w", encoding="utf-8") as detail_handle:
        write_detail_tsv(result.rows, detail_handle, config)

    if args.no_summary:
        emit("Skipped person summary (--no-summary)")
        return 0

    if args.summary_output:
        summary_path = os.path.expanduser(args.summary_output)
    else:
        summary_path = summary_path_from_detail(detail_path)

    emit(f"Writing person summary TSV: {summary_path}")
    with open(summary_path, "w", encoding="utf-8") as summary_handle:
        write_summary_tsv(result.summaries, summary_handle, config)

    if log:
        log.info(f"Outputs written under: {os.path.dirname(detail_path) or '.'}")
        log.info(f"  detail: {detail_path}")
        log.info(f"  person summary: {summary_path}")
        if raw_cache_path and not getattr(args, "from_cache", None):
            log.info(f"  raw cache: {raw_cache_path}")
        log.info(f"  run log: {log.path}")
    return 0
