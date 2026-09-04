from __future__ import annotations

import argparse
import sys
from pathlib import Path

from github_analysis.export.xlsx import export_workbook


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "export",
        help="Convert TSV reports to Excel (.xlsx)",
        description=(
            "Export person summary and PR detail TSV files from `analyze` into a single Excel workbook."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  github-analysis export \\\n"
            "    --summary ~/Documents/global-services_2026-05-01_to_2026-06-01_person_summary.tsv \\\n"
            "    --detail ~/Documents/global-services_2026-05-01_to_2026-06-01.tsv \\\n"
            "    -o ~/Documents/global-services_2026-05-01_to_2026-06-01.xlsx\n"
            "  github-analysis export --summary summary.tsv --summary-only -o team.xlsx"
        ),
    )
    parser.add_argument(
        "--summary",
        required=True,
        metavar="PATH",
        help="Person-level summary TSV from `analyze` (*_person_summary.tsv)",
    )
    parser.add_argument(
        "--detail",
        metavar="PATH",
        help="PR detail TSV from `analyze` (adds a second worksheet)",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="PATH",
        help="Output .xlsx path",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Write only the Individual Production sheet (ignore --detail)",
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    summary_path = Path(args.summary)
    detail_path = Path(args.detail) if args.detail else None
    output_path = Path(args.output)

    if not summary_path.is_file():
        print(f"Error: summary file not found: {summary_path}", file=sys.stderr)
        return 2
    if detail_path is not None and not detail_path.is_file():
        print(f"Error: detail file not found: {detail_path}", file=sys.stderr)
        return 2

    include_detail = detail_path is not None and not args.summary_only
    export_workbook(
        summary_path=summary_path,
        detail_path=detail_path,
        output_path=output_path,
        include_detail=include_detail,
    )
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0
