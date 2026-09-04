#!/usr/bin/env bash
# Monthly GitHub metrics: analyze + Excel export in one step.
#
# Usage:
#   ./run_monthly_report.sh global-services 2026-05-01 2026-06-01
#   ./run_monthly_report.sh global-services 2026-05-01 2026-06-01 --merged-only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REPO="${1:?repo required}"
START="${2:?start-date required (YYYY-MM-DD)}"
END="${3:?end-date required (YYYY-MM-DD, exclusive)}"
shift 3

echo "==> uv sync"
uv sync --group excel

echo "==> github-analysis run"
uv run github-analysis run \
  --repo "$REPO" \
  --start-date "$START" \
  --end-date "$END" \
  "$@"
