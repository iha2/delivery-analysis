#!/usr/bin/env bash
# Run the standard CEDT repos and build a combined Excel workbook.
#
# Repos: global-services, global-user-services, polaris-turbo, org-manager, places-proxy
# Team tabs: config/teams.yaml (agency rosters)
#
# Usage:
#   ./scripts/run_cedt_trio.sh START END
#   ./scripts/run_cedt_trio.sh START END --output-dir ~/Reports/github
#   ./scripts/run_cedt_trio.sh 2026-07-01 2026-08-01 --output-dir ~/Reports/github-metrics combined-2026-07.xlsx
#
# Output layout:
#   Without --output-dir: {GITHUB_ANALYSIS_RESULTS|~/github-analysis-results}/{START}_to_{END}/
#   With --output-dir DIR: files go directly in DIR (exact run folder; no extra nesting)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

usage() {
  echo "Usage: $0 START END [OUTPUT_DIR] [COMBINED_XLSX_NAME]" >&2
  echo "       $0 START END [--output-dir DIR] [--combined-name FILE]" >&2
  echo "  START/END: YYYY-MM-DD (END is exclusive)" >&2
  echo "  Default output: ~/github-analysis-results/{START}_to_{END}/" >&2
  echo "  --output-dir: exact run folder (no date subdir appended)" >&2
  exit 2
}

OUT_BASE="${GITHUB_ANALYSIS_RESULTS:-$HOME/github-analysis-results}"
OUT_DIR=""
COMBINED_NAME=""
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      [[ $# -ge 2 ]] || usage
      OUT_DIR="$2"
      shift 2
      ;;
    --combined-name)
      [[ $# -ge 2 ]] || usage
      COMBINED_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    --)
      shift
      POSITIONAL+=("$@")
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      ;;
    *)
      POSITIONAL+=("$1")
      shift
      ;;
  esac
done

[[ ${#POSITIONAL[@]} -ge 2 ]] || usage

START="${POSITIONAL[0]}"
END="${POSITIONAL[1]}"
if [[ ${#POSITIONAL[@]} -ge 3 ]]; then
  OUT_DIR="${POSITIONAL[2]}"
fi
if [[ ${#POSITIONAL[@]} -ge 4 ]]; then
  COMBINED_NAME="${POSITIONAL[3]}"
fi

STEM_SUFFIX="${START}_to_${END}"
if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="${OUT_BASE}/${STEM_SUFFIX}"
fi
if [[ -z "$COMBINED_NAME" ]]; then
  COMBINED_NAME="combined-${STEM_SUFFIX}.xlsx"
fi

mkdir -p "$OUT_DIR"

echo "==> uv sync"
uv sync --group excel

run_one() {
  local repo="$1"
  local workers="$2"
  local stem="${repo}-${STEM_SUFFIX}"
  echo "==> github-analysis run: $repo"
  uv run github-analysis run \
    --repo "$repo" \
    --start-date "$START" \
    --end-date "$END" \
    --merged-only \
    --workers "$workers" \
    --output-dir "$OUT_DIR" \
    -o "$OUT_DIR/${stem}.xlsx"
}

run_one global-services 4
run_one global-user-services 3
run_one polaris-turbo 4
run_one org-manager 3
run_one places-proxy 3

COMBINED="$OUT_DIR/$COMBINED_NAME"
echo "==> combine person summaries -> $COMBINED"
uv run python scripts/combine_person_summaries.py \
  --input-dir "$OUT_DIR" \
  --stem-suffix "$STEM_SUFFIX" \
  -o "$COMBINED"

echo "Done. Outputs in $OUT_DIR"
