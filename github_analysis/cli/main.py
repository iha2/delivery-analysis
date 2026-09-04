from __future__ import annotations

import argparse
import sys

from github_analysis import __version__
from github_analysis.config import OUTPUT_DIR_ENV_VAR, default_output_dir
from github_analysis.cli.commands import COMMAND_REGISTRARS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github-analysis",
        description=(
            "Analyze GitHub pull-request activity by individual contributor.\n\n"
            "Requires GitHub CLI (`gh`) authenticated with read access to the target repo.\n\n"
            "Commands:\n"
            "  analyze   Fetch data from GitHub and write TSV reports\n"
            "  export    Convert TSV reports to Excel\n"
            "  run       Analyze + export in one step\n\n"
            "Output directory (all commands that write files):\n"
            f"  Precedence: --output-dir  →  ${OUTPUT_DIR_ENV_VAR}  →  built-in default\n"
            f"  Default resolved path: {default_output_dir()}\n\n"
            "Run `github-analysis <command> --help` for command-specific options.\n"
            "Column definitions and date-window details: README.md in the repo."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Quick start (all of May 2026, merged PRs only, US Eastern):\n"
            "  uv run github-analysis run --repo global-services --month 2026-05 --merged-only\n\n"
            "Custom output folder:\n"
            "  export GITHUB_ANALYSIS_RESULTS=~/Reports/github-metrics\n"
            "  uv run github-analysis run --repo global-services --month 2026-05 --merged-only\n\n"
            "Default output names include the date range, e.g.\n"
            f"  {default_output_dir()}/global-services_2026-05-01_to_2026-06-01.xlsx"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="<command>",
        required=False,
    )
    for register in COMMAND_REGISTRARS:
        register(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error(f"command {args.command!r} has no handler")
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
