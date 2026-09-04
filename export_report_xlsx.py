#!/usr/bin/env python3
"""Legacy wrapper — use: uv run github-analysis export ..."""

from github_analysis.cli.main import main

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] not in {
        "analyze",
        "export",
        "run",
        "-h",
        "--help",
        "--version",
    }:
        sys.argv.insert(1, "export")
    raise SystemExit(main())
