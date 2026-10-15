from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

# Calendar dates for reports are interpreted in this timezone (DST-aware).
DEFAULT_REPORT_TZ_NAME = "America/New_York"
REPORT_TZ = ZoneInfo(DEFAULT_REPORT_TZ_NAME)

# Used when --repo is a short name without owner.
DEFAULT_GITHUB_OWNER = "Customer-Engagement-Digital-Technology"

# Default output directory under the user's home folder (created on first run if missing).
# Override with GITHUB_ANALYSIS_RESULTS or --output-dir. No ~/Dev path is required.
DEFAULT_OUTPUT_DIR = str(Path.home() / "github-analysis-results")

# Override default output directory without passing --output-dir on every command.
OUTPUT_DIR_ENV_VAR = "GITHUB_ANALYSIS_RESULTS"


def default_output_dir() -> str:
    """Output directory from GITHUB_ANALYSIS_RESULTS, else DEFAULT_OUTPUT_DIR."""
    import os

    env = os.environ.get(OUTPUT_DIR_ENV_VAR, "").strip()
    if env:
        return os.path.expanduser(env)
    return DEFAULT_OUTPUT_DIR


def resolve_output_dir(cli_value: str | None = None) -> str:
    """
    Resolve output directory precedence:
      1. --output-dir on the CLI (cli_value) when provided
      2. GITHUB_ANALYSIS_RESULTS environment variable
      3. DEFAULT_OUTPUT_DIR
    """
    import os

    if cli_value is not None and str(cli_value).strip():
        return os.path.expanduser(str(cli_value).strip())
    return default_output_dir()


OUTPUT_DIR_HELP = (
    f"Directory for report files (TSV, Excel, cache, log). "
    f"Precedence: this flag, then ${OUTPUT_DIR_ENV_VAR}, then {DEFAULT_OUTPUT_DIR}"
)

# GitHub API client settings
GH_API_TIMEOUT_SEC = 90
GH_API_RETRIES = 4
GH_API_RETRY_BASE_SEC = 2
API_LIST_PAGES_MAX = 100  # × 100 items/page
SEARCH_MAX_PAGES = 20

# Parallel PR detail fetch (Phase 2). 4 is a balance of speed vs GitHub rate limits.
DEFAULT_FETCH_WORKERS = 4
