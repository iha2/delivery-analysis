#!/usr/bin/env bash
# Unattended monthly CEDT multi-repo report + combined Excel.
#
# Usage:
#   ./scripts/run_monthly.sh 2026-07
#   ./scripts/run_monthly.sh 2026-07 --output-dir ~/Reports/github
#   ./scripts/run_monthly.sh 2026-07 --dry-run
#
# Output directory: --output-dir or GITHUB_ANALYSIS_RESULTS (default ~/github-analysis-results)

set -euo pipefail

usage() {
  echo "Usage: $0 YYYY-MM [--output-dir DIR] [--dry-run]" >&2
  echo "  YYYY-MM       calendar month to report (e.g. 2026-07)" >&2
  echo "  --output-dir  folder for all report files" >&2
  echo "                  (overrides GITHUB_ANALYSIS_RESULTS when set)" >&2
  exit 2
}

OUT_BASE="${GITHUB_ANALYSIS_RESULTS:-$HOME/github-analysis-results}"
MONTH=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      [[ $# -ge 2 ]] || usage
      OUT_BASE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      ;;
    --)
      shift
      MONTH="${1:-}"
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      ;;
    *)
      if [[ -z "$MONTH" ]]; then
        MONTH="$1"
        shift
      else
        echo "Unexpected argument: $1" >&2
        usage
      fi
      ;;
  esac
done

[[ -n "$MONTH" ]] || usage

if ! [[ "$MONTH" =~ ^[0-9]{4}-(0[1-9]|1[0-2])$ ]]; then
  echo "Error: MONTH must be YYYY-MM (e.g. 2026-07)" >&2
  exit 2
fi

START="${MONTH}-01"

if END=$(date -j -f "%Y-%m-%d" -v+1m "${START}" "+%Y-%m-%d" 2>/dev/null); then
  :
elif END=$(date -d "${START} +1 month" "+%Y-%m-%d" 2>/dev/null); then
  :
else
  END=$(python3 -c "
from datetime import date
y, m = map(int, '${MONTH}'.split('-'))
if m == 12:
    print(date(y + 1, 1, 1))
else:
    print(date(y, m + 1, 1))
")
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$(cd "$SCRIPT_DIR/.." && pwd)"
# One directory per monthly run under the results base
OUT_DIR="${OUT_BASE}/${MONTH}"
COMBINED="combined-${MONTH}.xlsx"
TRIO="${TOOL}/scripts/run_cedt_trio.sh"

echo "Monthly CEDT report"
echo "  Window (Eastern, half-open): ${START} .. ${END}"
echo "  Output directory: ${OUT_DIR}"
echo "  Final Excel: ${OUT_DIR}/${COMBINED}"
echo "  Tool: ${TOOL}"

if [[ ! -x "$TRIO" ]]; then
  chmod +x "$TRIO" 2>/dev/null || true
fi
if [[ ! -f "$TRIO" ]]; then
  echo "Error: missing ${TRIO}" >&2
  exit 2
fi

if $DRY_RUN; then
  echo "(dry-run — not executing)"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "Error: gh not found — install GitHub CLI and run gh auth login" >&2
  exit 2
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "Error: gh not authenticated — run: gh auth login" >&2
  exit 2
fi

exec bash "$TRIO" "$START" "$END" --output-dir "$OUT_DIR" --combined-name "$COMBINED"
