#!/usr/bin/env python3
"""Legacy wrapper — use: uv run delivery-analysis analyze ..."""

from github_analysis.cli.main import main

if __name__ == "__main__":
    import sys

    # github_pr_timeline_report.py --repo ...  ->  delivery-analysis analyze --repo ...
    if len(sys.argv) > 1 and sys.argv[1] not in {
        "analyze",
        "export",
        "run",
        "-h",
        "--help",
        "--version",
    }:
        sys.argv.insert(1, "analyze")
    raise SystemExit(main())
