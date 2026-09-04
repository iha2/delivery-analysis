from __future__ import annotations

import argparse
import os
import sys

from github_analysis.cli.commands import analyze, export
from github_analysis.cli.commands.analyze import MERGED_ONLY_HELP, OUTPUT_FILES_EPILOG
from github_analysis.cli.output_dir import add_output_dir_argument, apply_output_dir
from github_analysis.cli.report_window import (
    add_period_args,
    apply_resolved_window_to_args,
    date_window_note,
    resolve_report_window,
)
from github_analysis.config import DEFAULT_FETCH_WORKERS, default_output_dir
from github_analysis.export.paths import (
    default_detail_path,
    default_summary_path,
    default_xlsx_path,
    paths_from_excel_output,
    run_log_path_from_detail,
)
from github_analysis.repo import resolve_repository


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "run",
        help="Analyze and export Excel in one step",
        description=(
            "Convenience command: runs `analyze` then `export` with default output paths. "
            "Best for monthly manager reports.\n\n"
            f"{date_window_note()}.\n\n"
            "To rebuild Excel from an existing *_raw.json cache, use `analyze --from-cache` "
            "then `export` instead."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"{OUTPUT_FILES_EPILOG}"
            "  {repo}_{start}_to_{end}.xlsx\n\n"
            "Examples:\n"
            "  # All of May 2026 (recommended):\n"
            "  github-analysis run --repo global-services --month 2026-05 --merged-only\n"
            "  # May 15 through month end — separate files from a full-month run:\n"
            "  github-analysis run --repo global-services --start-date 2026-05-15 --end-date 2026-06-01 --merged-only\n"
            "  # Custom Excel base name (sibling TSV, cache, and log share this stem):\n"
            "  github-analysis run --repo global-services --month 2026-05 --merged-only --workers 4 \\\n"
            "    -o ~/Reports/global-services-may-2026.xlsx\n"
            "  # All outputs under a custom directory:\n"
            "  github-analysis run --repo global-services --month 2026-05 --merged-only \\\n"
            "    --output-dir ~/Reports/github-metrics"
        ),
    )
    analyze._add_repo_args(parser)
    add_period_args(parser)
    parser.add_argument(
        "--merged-only",
        action="store_true",
        help=MERGED_ONLY_HELP,
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Excel workbook contains only the Individual Production sheet",
    )
    add_output_dir_argument(parser)
    parser.add_argument(
        "-o",
        "--output",
        metavar="PATH",
        help=(
            "Excel workbook path (.xlsx). When omitted, writes under --output-dir as "
            "{repo}_{start}_to_{end}.xlsx. Also writes sibling files: {stem}.tsv, "
            "{stem}_person_summary.tsv, {stem}_raw.json, {stem}_run.log"
        ),
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

    output_dir = os.path.expanduser(args.output_dir)

    if args.output:
        xlsx_path, summary_path, detail_path = paths_from_excel_output(args.output)
        os.makedirs(os.path.dirname(xlsx_path) or ".", exist_ok=True)
    else:
        os.makedirs(output_dir, exist_ok=True)
        detail_path = default_detail_path(
            repository.name, args.start_date, args.end_date, output_dir=output_dir
        )
        summary_path = default_summary_path(
            repository.name, args.start_date, args.end_date, output_dir=output_dir
        )
        xlsx_path = default_xlsx_path(
            repository.name, args.start_date, args.end_date, output_dir=output_dir
        )

    analyze_args = argparse.Namespace(
        repo=args.repo,
        owner=args.owner,
        month=None,
        start_date=args.start_date,
        end_date=args.end_date,
        timezone=args.timezone,
        output=detail_path,
        summary_output=summary_path,
        no_summary=False,
        merged_only=args.merged_only,
        output_dir=output_dir,
        from_cache=None,
        workers=args.workers,
    )
    exit_code = analyze.run(analyze_args)
    if exit_code != 0:
        return exit_code

    export_args = argparse.Namespace(
        summary=summary_path,
        detail=None if args.summary_only else detail_path,
        output=xlsx_path,
        summary_only=args.summary_only,
    )
    exit_code = export.run(export_args)
    if exit_code == 0:
        log_hint = run_log_path_from_detail(detail_path)
        print(f"Run log: {log_hint}", file=sys.stderr)
    return exit_code
