# Architecture

## Package layout

```
github-analysis/
├── pyproject.toml
├── run_monthly_report.sh
├── github_pr_timeline_report.py   # legacy → analyze
├── export_report_xlsx.py          # legacy → export
└── github_analysis/
    ├── config.py                  # timezone, default org, API limits
    ├── models.py                  # ReportConfig, PullRequestRow, UserSummary
    ├── repo.py                    # parse --repo
    ├── time_utils.py              # date windows, timestamps
    ├── cli/commands/              # analyze, export, run
    ├── github/                    # GhClient, preflight, pulls
    ├── catalog/search.py          # Phase 1 PR discovery
    ├── analysis/                  # pr_builder, reviews, summaries
    ├── cache/raw_store.py         # _raw.json read/write
    ├── export/                    # paths, tsv, xlsx
    └── pipeline/runner.py         # run_report() orchestration
```

## Data flow

```
CLI command
  → pipeline/runner.py     (discover PRs, fetch details, summarize)
  → analysis/              (per-PR and per-person metrics)
  → export/                (TSV and/or Excel)
```

## Pipeline phases

| Phase | Module | What happens |
|-------|--------|----------------|
| Preflight | `github/preflight.py` | `gh auth status`, repo access check |
| Phase 1 | `catalog/search.py` | GitHub search → PR number catalog |
| Phase 2 | `analysis/pr_builder.py` | Fetch PR detail (parallel via `--workers`) |
| Phase 3 | `analysis/reviews.py`, `summaries.py` | Review counts, person rollups |
| Phase 3b | `analysis/authored_activity.py` | Open-at-window-end snapshot |
| Write | `export/`, `cache/raw_store.py` | TSV, `_raw.json`, Excel |

## Phase 2 — REST calls per PR

Each PR triggers about six `gh api` calls:

| Call | Endpoint |
|------|----------|
| Metadata | `GET /pulls/{n}` |
| Commits | `GET /pulls/{n}/commits` (paginated) |
| Files | `GET /pulls/{n}/files` (paginated) |
| Events | `GET /issues/{n}/events` |
| Reviews | `GET /pulls/{n}/reviews` |
| Comments | `GET /issues/{n}/comments` |

Phase 2 uses `ThreadPoolExecutor` in `pipeline/runner.py`. Each worker gets its own `GhClient`. Results are merged and sorted by PR number after the pool finishes.

## Catalog search

`catalog/search.py` builds Phase 1 queries with GitHub **calendar date ranges**:

```
merged:2026-05-01..2026-05-31
```

Ranges align with `--start-date` and the day before `--end-date`. ISO timestamp qualifiers (`merged:>=2026-05-01T04:00:00Z`) are unreliable in GitHub search and must not be used.

## Configuration (`config.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `REPORT_TZ` | `America/New_York` | Calendar dates and report timestamps |
| `DEFAULT_GITHUB_OWNER` | org slug | Short `--repo` names |
| `DEFAULT_OUTPUT_DIR` | `~/github-analysis-results` | Built-in default (under user home; created on first run) |
| `GITHUB_ANALYSIS_RESULTS` | — | Env var override for output folder (CLI `--output-dir` wins when set) |
| `DEFAULT_FETCH_WORKERS` | `4` | Default `--workers` |
| `GH_API_TIMEOUT_SEC` | `90` | Per-request timeout |
| `GH_API_RETRIES` | `4` | Retries on 429, 502, timeouts |
| `SEARCH_MAX_PAGES` | `20` | Search pagination (GitHub hard cap: 1,000 results) |
| `API_LIST_PAGES_MAX` | `100` | Max commit/file list pages per PR |
