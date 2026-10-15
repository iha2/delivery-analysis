# Architecture

## Package layout

```
github-analysis/
├── pyproject.toml
├── run_monthly_report.sh
├── github_pr_timeline_report.py   # legacy → analyze
├── export_report_xlsx.py          # legacy → export
├── github_analysis/               # compatibility shims (old import paths)
└── delivery_analysis/
    ├── core/time_utils.py         # date windows, timestamps
    └── connectors/github/
        ├── config.py              # timezone, default org, API limits
        ├── models.py              # ReportConfig, PullRequestRow, UserSummary
        ├── repo.py                # parse --repo
        ├── client.py, preflight.py, pulls.py  # GhClient, preflight, pulls
        ├── search.py              # Phase 1 PR discovery
        ├── pr_builder.py, reviews.py, summaries.py, authored_activity.py  # analysis
        ├── raw_store.py           # _raw.json read/write
        └── runner.py              # run_report() orchestration
```

The old `github_analysis` paths are compatibility shims that alias to these modules; CLI commands, export, and logging still live under `github_analysis/`.

## Data flow

```
CLI command
  → connectors/github/runner.py   (discover PRs, fetch details, summarize)
  → connectors/github/ analysis modules (per-PR and per-person metrics)
  → export/                (TSV and/or Excel)
```

## Pipeline phases

| Phase | Module | What happens |
|-------|--------|----------------|
| Preflight | `connectors/github/preflight.py` | `gh auth status`, repo access check |
| Phase 1 | `connectors/github/search.py` | GitHub search → PR number catalog |
| Phase 2 | `connectors/github/pr_builder.py` | Fetch PR detail (parallel via `--workers`) |
| Phase 3 | `connectors/github/reviews.py`, `summaries.py` | Review counts, person rollups |
| Phase 3b | `connectors/github/authored_activity.py` | Open-at-window-end snapshot |
| Write | `github_analysis/export/`, `connectors/github/raw_store.py` | TSV, `_raw.json`, Excel |

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

Phase 2 uses `ThreadPoolExecutor` in `connectors/github/runner.py`. Each worker gets its own `GhClient`. Results are merged and sorted by PR number after the pool finishes.

## Catalog search

`connectors/github/search.py` builds Phase 1 queries with GitHub **calendar date ranges**:

```
merged:2026-05-01..2026-05-31
```

Ranges align with `--start-date` and the day before `--end-date`. ISO timestamp qualifiers (`merged:>=2026-05-01T04:00:00Z`) are unreliable in GitHub search and must not be used.

## Configuration (`connectors/github/config.py`)

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
