# GitHub Team Metrics

Pull **per-person engineering metrics** from any GitHub repository you can access: merged PRs, reviews, file-change averages, and optional PR-level detail. Output is Excel and TSV for managers and team leads.

Uses the [GitHub CLI](https://cli.github.com/) (`gh`) for API access. See [Install and setup](#install-and-setup) for prerequisites, token setup, and verification.

**Platform guides:** [macOS (MacBook)](#macos-macbook--setup-and-monthly-report) · [Windows](#windows--setup-and-monthly-report)

---

## Monthly combined workbook (CEDT)

**Primary deliverable each month:** `{output-dir}/YYYY-MM/combined-YYYY-MM.xlsx` (default base: `~/github-analysis-results/` — see [Output directory configuration](#output-directory-configuration))

Each run writes into its **own subdirectory** under the results base (monthly: `YYYY-MM/`; partial windows: `{START}_to_{END}/`).

That workbook has:

| Sheet | Contents |
|-------|----------|
| **Totals** | All staff rollup — banner **All Staff Metrics**, same formatting as team tabs; one row per GitHub user across all five repos |
| **Team tabs** (e.g. **TresPi**) | One sheet per agency in [`config/teams.yaml`](config/teams.yaml) — roster filtered from Totals (see [Agency / team tabs](#agency--team-tabs)) |
| **global-services** | Person metrics for that repo |
| **global-user-services** | Person metrics for that repo |
| **polaris-turbo** | Person metrics for that repo |
| **org-manager** | Person metrics for that repo |
| **places-proxy** | Person metrics for that repo |

Sheet order in the combined workbook: **Totals** → **team tabs** (config order) → **repo tabs**.

The monthly script **fetches raw data from GitHub** for all five CEDT repos, writes per-repo Excel/TSV/cache files, then **builds the combined workbook** automatically. Expect **15–30 minutes** depending on API volume.

### Agency / team tabs

Agency (vendor) teams get their own sheets in the combined Excel. Rosters live in [`config/teams.yaml`](config/teams.yaml) — **edit that file only**; no code changes are required to add or update teams. JSON is also supported (same schema).

#### Sheet layout

| Row | Content |
|-----|---------|
| 1 | **`team_banner`** text (merged across columns), e.g. `TresPi Staff Metrics` |
| 2 | Column headers (`staff_name`, `user`, PR metrics, …) |
| 3+ | One row per roster member (config order), metrics taken from **Totals** |

Members with no activity in the window still appear with zero counts. GitHub login matching is **case-insensitive**.

#### Config fields

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | Yes | Excel **sheet tab** title (max 31 characters; avoid `: \ / ? * [ ]`) |
| `team_banner` | No | Banner text in **row 1** of the sheet. Defaults to `name` if omitted |
| `members` | Yes | Non-empty list of people on that team |
| `members[].name` | Yes | Display name → `staff_name` column |
| `members[].user` | Yes | GitHub login → matched against Totals `user` |

#### Example — add another team

Append another entry under `teams:` in [`config/teams.yaml`](config/teams.yaml):

```yaml
teams:
  - name: TresPi
    team_banner: "TresPi Staff Metrics"
    members:
      - name: Alexandra Ortiz
        user: AlexsOrtiz
      - name: Brandon Velasquez
        user: brandon-trespi
      # …

  - name: AcmeAgency
    team_banner: "Acme Agency Staff Metrics"
    members:
      - name: Jane Doe
        user: jane-doe-gh
      - name: Sam Lee
        user: samlee
```

That produces two team sheets after Totals: **TresPi** and **AcmeAgency**, each with its own header banner and roster.

#### After editing the roster

- **Next monthly / partial run** — team tabs are built automatically from `config/teams.yaml`.
- **Rebuild Excel only** (person summaries already fetched) — see [Rebuild combined Excel only](#rebuild-combined-excel-only-no-github-fetch). Use `--no-teams` to skip team tabs, or `--teams-config PATH` for a different file.

### One-time setup

Complete [Install and setup](#install-and-setup) once: `uv`, `gh`, PAT or `gh auth login`, clone this repo, `uv sync --group excel`.

Verify before your first monthly run:

```bash
gh auth status
gh repo view Customer-Engagement-Digital-Technology/global-services
```

### Each month — run in Terminal

Replace `YYYY-MM` with the calendar month you are reporting (e.g. `2026-07` for all of July 2026).

| Platform | Instructions |
|----------|----------------|
| **MacBook (macOS)** | [macOS guide — monthly report](#macos-macbook--setup-and-monthly-report) |
| **Windows** | [Windows guide — monthly report](#windows--setup-and-monthly-report) |

Generic command (macOS Terminal or Windows Git Bash), run from **wherever you cloned this repo**:

```bash
cd /path/to/github-analysis
./scripts/run_monthly.sh YYYY-MM
```

**Example — July 2026:**

```bash
./scripts/run_monthly.sh 2026-07
```

When it finishes, open the combined workbook in your configured output folder (default):

```text
~/github-analysis-results/2026-07/combined-2026-07.xlsx
```

On Windows (PowerShell): `%USERPROFILE%\github-analysis-results\2026-07\combined-2026-07.xlsx`

**Dry-run** (prints the date window and output paths without fetching):

```bash
./scripts/run_monthly.sh 2026-07 --dry-run
```

**Custom output folder** — `--output-dir` overrides `GITHUB_ANALYSIS_RESULTS` for this run:

```bash
./scripts/run_monthly.sh 2026-07 --output-dir ~/Reports/github-metrics
```

See [Output directory configuration](#output-directory-configuration).

### What the monthly script creates

All files land in a **per-run subdirectory** under the results base (default `~/github-analysis-results/YYYY-MM/`; see [Output directory configuration](#output-directory-configuration)):

| File | Purpose |
|------|---------|
| `combined-YYYY-MM.xlsx` | **Final deliverable** — Totals + team tabs + five repo tabs |
| `{repo}-YYYY-MM-01_to_YYYY-MM-NN.xlsx` | Per-repo Excel (Individual Production + PR Detail) |
| `{repo}-…_person_summary.tsv` | Person rollup for that repo (input to Totals) |
| `{repo}-….tsv` | PR-level detail |
| `{repo}-…_raw.json` | Cache — re-export without re-fetching GitHub |
| `{repo}-…_run.log` | Progress and errors — **read this first if a run fails** |

Repos analyzed (production defaults):

| Repo | Parallel workers |
|------|------------------|
| `global-services` | 4 |
| `global-user-services` | 3 |
| `polaris-turbo` | 4 |
| `org-manager` | 3 |
| `places-proxy` | 3 |

Flags applied automatically: **`--merged-only`**, US Eastern (`America/New_York`), half-open date window.

### Partial month (not a full calendar month)

```bash
cd /path/to/github-analysis
./scripts/run_cedt_trio.sh START END
```

`END` is **exclusive** — for June 1–23 inclusive use `2026-06-01` and `2026-06-24`.

Produces `~/github-analysis-results/START_to_END/combined-START_to_END.xlsx` (or under `--output-dir` if you pass an exact run folder).

### Rebuild combined Excel only (no GitHub fetch)

If per-repo `*_person_summary.tsv` files already exist:

```bash
cd /path/to/github-analysis
uv run python scripts/combine_person_summaries.py \
  --input-dir ~/github-analysis-results/2026-07-01_to_2026-08-01 \
  --stem-suffix "2026-07-01_to_2026-08-01" \
  -o ~/github-analysis-results/2026-07-01_to_2026-08-01/combined-2026-07.xlsx
```

Team tabs load from `config/teams.yaml` by default (`--no-teams` to skip; `--teams-config PATH` to override).

Human runbook: [docs/monthly-runbook.md](docs/monthly-runbook.md) (links back here). **Using Cursor or another AI assistant?** See [AGENTS.md](AGENTS.md).

### Not comfortable with Terminal?

Ask an assistant (or a colleague) to run the monthly script for you after [one-time setup](#install-and-setup). You only need to complete **GitHub login** (`gh auth login`) if prompted. The report file will be in your output folder (default `~/github-analysis-results/YYYY-MM/combined-YYYY-MM.xlsx`).

**Open the file:**
- **macOS:** Finder → **Go → Go to Folder…** → `~/github-analysis-results`
- **Windows:** File Explorer address bar → `%USERPROFILE%\github-analysis-results`
- **Linux:** file manager → `~/github-analysis-results`

---

## Single-repo quick start

**Prerequisites:** [uv](https://docs.astral.sh/uv/), [GitHub CLI 2.30+](https://cli.github.com/) authenticated with a **personal access token (PAT)** or `gh auth login`, and read access to the target repo. See [Install and setup](#install-and-setup) for PAT scope, SSO, and verification.

```bash
git clone https://github.com/iha2/github-analysis.git
cd github-analysis
uv sync --group excel

uv run github-analysis run \
  --repo global-services \
  --month 2026-05 \
  --merged-only \
  --workers 4
```

| Flag | Meaning |
|------|---------|
| `--month` | Full calendar month (`YYYY-MM`) — sets start/end dates automatically |
| `--timezone` | IANA timezone for calendar dates (default `America/New_York`) |
| `--start-date` | First calendar day **included** (use instead of `--month` for partial windows) |
| `--end-date` | First calendar day **excluded** — with `--month 2026-05`, same as `2026-05-01` .. `2026-06-01` |
| `--merged-only` | PR detail sheet: merged PRs only; person summary still includes authored, open, and review counts |
| `--workers` | Parallel fetch threads (default `4`) |
| `-o` | Excel path; sibling TSV, cache, and log share the same base name |

**Outputs** — default base name `{repo}_{start}_to_{end}` (date range in every filename; omit `-o` to use this pattern):

| File | Purpose |
|------|---------|
| `.xlsx` | Excel — **Individual Production** + **PR Detail** sheets (`run` only) |
| `_person_summary.tsv` | One row per person |
| `.tsv` | One row per pull request |
| `_raw.json` | Cache for `--from-cache` rebuilds |
| `_run.log` | Auth checks, progress, errors — **read this first if a run fails** |

Example: `global-services_2026-05-15_to_2026-06-01_run.log` for May 15–31 does not overwrite a full-month `..._2026-05-01_to_2026-06-01.*` report.

---

## macOS (MacBook) — setup and monthly report

One-time setup, then one command each month. No `~/Dev` folder required — use any path you prefer.

### One-time setup (Mac)

1. Open **Terminal** (Applications → Utilities → Terminal).

2. Install tools:

```bash
# GitHub CLI (if you use Homebrew)
brew install gh

# uv (Python runner for this project)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Restart Terminal, then:
uv --version
gh --version
```

3. Clone and install the project (example path — change if you like):

```bash
git clone https://github.com/iha2/github-analysis.git ~/Projects/github-analysis
cd ~/Projects/github-analysis
uv sync --group excel
```

4. Sign in to GitHub:

```bash
gh auth login
gh auth status
gh repo view Customer-Engagement-Digital-Technology/global-services
```

5. *(Optional)* Set a custom report folder in `~/.zshrc`:

```bash
export GITHUB_ANALYSIS_RESULTS=~/Documents/GitHubReports
mkdir -p "$GITHUB_ANALYSIS_RESULTS"
```

If you skip step 5, reports go to **`~/github-analysis-results/`** (created automatically).

### Each month (Mac)

```bash
cd ~/Projects/github-analysis    # your clone path
./scripts/run_monthly.sh 2026-07
```

Allow **10–20 minutes**. When it finishes, open:

```text
~/github-analysis-results/2026-07/combined-2026-07.xlsx
```

(or `$GITHUB_ANALYSIS_RESULTS/combined-2026-07.xlsx` if you set the env var)

**Finder:** **Go → Go to Folder…** → paste `~/github-analysis-results` → double-click `combined-2026-07.xlsx`.

**Dry-run:** `./scripts/run_monthly.sh 2026-07 --dry-run`

**Custom folder for one month:** `./scripts/run_monthly.sh 2026-07 --output-dir ~/Desktop/july-check`

---

## Windows — setup and monthly report

One-time setup, then one command each month. Default output: **`%USERPROFILE%\github-analysis-results`**.

### One-time setup (Windows)

1. Open **PowerShell** (or **Git Bash** for the monthly shell script).

2. Install tools — pick one method for each:

**GitHub CLI** — [Installer](https://cli.github.com/) or:

```powershell
winget install --id GitHub.cli
```

**uv** — see [uv Windows install](https://docs.astral.sh/uv/getting-started/installation/), then restart the terminal and run `uv --version`.

3. Clone and install (example path):

```powershell
git clone https://github.com/iha2/github-analysis.git $HOME\github-analysis
cd $HOME\github-analysis
uv sync --group excel
uv run github-analysis --version
```

4. Sign in to GitHub:

```powershell
gh auth login
gh auth status
gh repo view Customer-Engagement-Digital-Technology/global-services
```

5. *(Optional)* Set a custom report folder for the current PowerShell session:

```powershell
$env:GITHUB_ANALYSIS_RESULTS = "$HOME\Documents\GitHubReports"
New-Item -ItemType Directory -Force -Path $env:GITHUB_ANALYSIS_RESULTS
```

To persist, add that line to your [PowerShell profile](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_profiles).

If you skip step 5, reports go to **`%USERPROFILE%\github-analysis-results`** (created automatically).

### Each month (Windows)

**Recommended:** **Git Bash** (installed with [Git for Windows](https://git-scm.com/download/win)):

```bash
cd ~/github-analysis          # your clone path
./scripts/run_monthly.sh 2026-07
```

Allow **10–20 minutes**. When it finishes, open:

```text
C:\Users\YourName\github-analysis-results\combined-2026-07.xlsx
```

**File Explorer:** click the address bar → paste `%USERPROFILE%\github-analysis-results` → open `combined-2026-07.xlsx`.

**Dry-run:** `./scripts/run_monthly.sh 2026-07 --dry-run`

**Custom folder for one month:** `./scripts/run_monthly.sh 2026-07 --output-dir "$HOME/Documents/july-check"`

**PowerShell-only (no Git Bash):** use the CLI directly for a single repo, or install Git Bash/WSL for the full monthly multi-repo script. Example single-repo run:

```powershell
cd $HOME\github-analysis
uv run github-analysis run --repo global-services --month 2026-07 --merged-only --output-dir "$env:USERPROFILE\github-analysis-results"
```

For the full five-repo **combined** workbook without bash, use **Git Bash** and `./scripts/run_monthly.sh` as above.

---

## Install and setup (reference)

Everything needed before your first report. **Start with the platform guides:** [macOS (MacBook)](#macos-macbook--setup-and-monthly-report) · [Windows](#windows--setup-and-monthly-report).

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| [uv](https://docs.astral.sh/uv/) | latest | Python runtime and project dependencies |
| [GitHub CLI](https://cli.github.com/) (`gh`) | 2.30+ | All GitHub API calls — **must be installed and authenticated** |
| **GitHub PAT or `gh auth login`** | — | Token with **`repo`** scope (classic) or fine-grained read on pull requests + contents |
| GitHub account | — | Read access to the repository you will analyze |

Default report output: **`~/github-analysis-results`** (macOS/Linux) or **`%USERPROFILE%\github-analysis-results`** (Windows). See [Output directory configuration](#output-directory-configuration).

### 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS / Linux
```

Restart your shell or ensure `~/.local/bin` is on your `PATH`. Windows: see [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Install GitHub CLI (`gh`)

The tool does **not** call the GitHub REST API directly — every fetch goes through `gh api`. You must install and authenticate `gh` separately.

**macOS (Homebrew):**

```bash
brew install gh
gh --version    # expect 2.30 or newer
```

**Other platforms:** [cli.github.com](https://cli.github.com/) (Windows installer, Linux packages, etc.).

### 3. Clone the project and install dependencies

```bash
git clone https://github.com/iha2/github-analysis.git
cd github-analysis
uv sync --group excel
uv run github-analysis --version    # expect 2.0.0
```

`uv sync` installs Python 3.9+ automatically. The `excel` group adds `openpyxl` for `.xlsx` output.

### 4. Authenticate with GitHub

Reports need a token that can **read** the target repository (including private org repos).

**Option A — interactive login (typical for local use):**

```bash
gh auth login
```

Choose: **GitHub.com** → **HTTPS** → authenticate via **browser** or **paste a token**. For private repositories, ensure the token has **`repo`** scope (classic PAT) or equivalent read access (fine-grained PAT).

**Option B — personal access token (PAT):**

1. Create a token at [github.com/settings/tokens](https://github.com/settings/tokens):
   - **Classic PAT:** enable the **`repo`** scope (full control of private repositories is not required — read is enough).
   - **Fine-grained PAT:** grant read access to **Contents** and **Pull requests** for the target repository (or org).
2. Log in with the token:

```bash
gh auth login --with-token <<< "ghp_YOUR_TOKEN_HERE"
```

**Organization SSO:** If your org enforces SAML SSO (e.g. `Customer-Engagement-Digital-Technology`), authorize the token for that org under GitHub → **Settings** → **Applications** → **Authorized OAuth Apps** / **Personal access tokens**.

**CI / automation:** Set `GH_TOKEN` or `GITHUB_TOKEN` in the environment before running `gh` or this tool — `gh` picks either variable automatically.

### 5. Verify setup

Run these before a large report. All should succeed without errors:

```bash
gh auth status
gh api user --jq .login
gh repo view Customer-Engagement-Digital-Technology/global-services   # or your target repo
uv run github-analysis --version
```

`gh auth status` should show a logged-in account with `Token scopes` including `repo` (or sufficient fine-grained permissions). If `gh repo view` returns 404, fix token scope or SSO authorization before running a report.

Each run also performs a **preflight** check (auth + repo read access) and writes the result to `_run.log`.

---

## Output directory configuration

All report files (Excel, TSV, JSON cache, run log) are written to one **output directory**. Filenames include the repo and date window; only the folder is configurable.

### Precedence (highest wins)

| Priority | Setting | Example |
|----------|---------|---------|
| 1 | **`--output-dir`** on the command line | `--output-dir ~/Reports/github-metrics` |
| 2 | **`GITHUB_ANALYSIS_RESULTS`** environment variable | `export GITHUB_ANALYSIS_RESULTS=~/Reports/github-metrics` |
| 3 | Built-in default | `~/github-analysis-results` (your home directory; folder is created if missing) |

**If both the environment variable and `--output-dir` are set, the CLI flag wins** for that run.

### Platforms and paths

- **macOS, Linux, and Windows** are supported (`uv` and `gh` on each platform).
- **You do not need a `~/Dev` directory.** Clone this repo anywhere (e.g. `~/Projects/github-analysis`, `C:\Users\you\github-analysis`).
- **Default report output** is **`~/github-analysis-results`** on macOS/Linux, or **`%USERPROFILE%\github-analysis-results`** on Windows. The tool creates the folder on first run.
- **Pick any output folder** with `GITHUB_ANALYSIS_RESULTS` or `--output-dir` (team share, Documents, Desktop, etc.).
- **Monthly shell scripts** (`run_monthly.sh`, `run_cedt_trio.sh`) require **bash** — built-in on macOS/Linux; on Windows use **Git Bash**, **WSL**, or run the equivalent `uv run github-analysis` commands from README.

**Windows — set output folder (PowerShell, persistent for session):**

```powershell
$env:GITHUB_ANALYSIS_RESULTS = "$HOME\Documents\GitHubReports"
New-Item -ItemType Directory -Force -Path $env:GITHUB_ANALYSIS_RESULTS
```

**Windows — one-off CLI override:**

```powershell
uv run github-analysis run --repo global-services --month 2026-07 --merged-only `
  --output-dir "$HOME\Documents\GitHubReports"
```

### Environment variable (persistent default)

Set once in your shell profile so every run uses the same folder without repeating `--output-dir`:

```bash
export GITHUB_ANALYSIS_RESULTS=~/Reports/github-metrics
mkdir -p "$GITHUB_ANALYSIS_RESULTS"
```

Then:

```bash
uv run github-analysis run --repo global-services --month 2026-07 --merged-only
# writes under ~/Reports/github-metrics/
```

Monthly scripts honor the same variable:

```bash
./scripts/run_monthly.sh 2026-07
# combined-2026-07.xlsx and per-repo files under $GITHUB_ANALYSIS_RESULTS
```

### CLI flag (one-off override)

Override the env var for a single command:

```bash
uv run github-analysis run --repo global-services --month 2026-07 --merged-only \
  --output-dir ~/Desktop/july-spot-check
```

Monthly scripts:

```bash
./scripts/run_monthly.sh 2026-07 --output-dir ~/Desktop/july-spot-check
./scripts/run_cedt_trio.sh 2026-06-01 2026-06-24 --output-dir ~/Reports/github-metrics
```

### `-o` / `--output` (explicit file path)

When you pass `-o path/to/report.xlsx`, sibling TSV, cache, and log files are written next to that Excel file. **`--output-dir` applies when `-o` is omitted** (auto-named files).

### CLI help

```bash
uv run github-analysis --help
uv run github-analysis run --help
uv run github-analysis analyze --help
```

---

## Commands

| Command | Description |
|---------|-------------|
| **`run`** | Fetch from GitHub and write Excel + TSV + cache (recommended) |
| **`analyze`** | Fetch and write TSV + cache only |
| **`export`** | Build Excel from existing TSV files |

All commands: `uv run github-analysis <command> --help`

### CLI options

| Option | Commands | Description |
|--------|----------|-------------|
| `--repo` | analyze, run | HTTPS URL, `owner/name`, or short name (uses default org in `config.py`) |
| `--owner` | analyze, run | Org when `--repo` is a short name only |
| `--month` | analyze, run | Full calendar month (`YYYY-MM`); cannot combine with `--start-date` / `--end-date` |
| `--timezone` | analyze, run | IANA timezone for dates and timestamps (default `America/New_York`) |
| `--start-date` | analyze, run | Start inclusive (`YYYY-MM-DD`); required unless `--month` is set |
| `--end-date` | analyze, run | End exclusive (`YYYY-MM-DD`); required unless `--month` is set |
| `--merged-only` | analyze, run | Detail sheet: merged PRs only (see [Monthly metrics](#monthly-metrics)) |
| `--workers` | analyze, run | Parallel fetch threads (default `4`; use `3` or `1` under rate pressure) |
| `-o`, `--output` | run | Excel path (`.xlsx`); writes sibling TSV files |
| `-o`, `--output` | analyze | Detail TSV path (`-` = stdout) |
| `-o`, `--output` | export | Excel path (required) |
| `--output-dir` | analyze, run | Folder for auto-named TSV, Excel, cache, log. **Overrides `GITHUB_ANALYSIS_RESULTS`.** See [Output directory configuration](#output-directory-configuration). |
| `--from-cache` | analyze | Rebuild TSV from `{name}_raw.json` without GitHub fetch |
| `--summary-output` | analyze | Custom path for person summary TSV |
| `--no-summary` | analyze | Skip person summary TSV |
| `--summary` | export | Input person summary TSV (required) |
| `--detail` | export | Input PR detail TSV (optional second sheet) |
| `--summary-only` | export, run | Excel with Individual Production sheet only |

### Repository formats

| Format | Example |
|--------|---------|
| HTTPS URL | `https://github.com/Customer-Engagement-Digital-Technology/global-services.git` |
| Owner/name | `Customer-Engagement-Digital-Technology/global-services` |
| Short name | `global-services` |

### Date windows

Reports use a **half-open** calendar window in the report timezone (`--timezone`, default `America/New_York`):

```
start <= event time < end   (end date is exclusive)
```

**Shorthand for a full calendar month:**

```bash
--month 2026-05    # same as --start-date 2026-05-01 --end-date 2026-06-01
```

Use `--start-date` and `--end-date` instead of `--month` for partial windows (e.g. May 15–31).

| Flag | Boundary | Meaning |
|------|----------|---------|
| `--month` | Full month | Sets start to the 1st and end to the 1st of the next month |
| `--start-date` | **Inclusive** (`>=`) | First calendar day **included** — activity from **00:00** in `--timezone` |
| `--end-date` | **Exclusive** (`<`) | First calendar day **excluded** — window ends the instant **before** 00:00 on this date |

**Important:** The end date uses **strict less-than**, not less-than-or-equal. A PR merged at **June 1 00:00** in the report timezone is **not** in a May report (`--month 2026-05` or `--end-date 2026-06-01`).

**Example — all of May 2026:**

| | Value |
|--|-------|
| `--month` | `2026-05` |
| equivalent dates | `2026-05-01` .. `2026-06-01` |
| **Includes** | May 1 00:00:00 through May 31 23:59:59 (in `--timezone`) |
| **Excludes** | June 1 and later |

Every metric (merged, authored, reviews, `prs_open` snapshot at month-end) uses this same window. GitHub search queries use the equivalent inclusive calendar range (`2026-05-01..2026-05-31` for the example above).

**More examples:**

| Period | `--month` or dates | Last day included |
|--------|-------------------|-------------------|
| All of May 2026 | `--month 2026-05` | May 31 |
| One week (May 1–7) | `2026-05-01` .. `2026-05-08` | May 7 |
| May 15–31 | `2026-05-15` .. `2026-06-01` | May 31 |
| Q1 2026 | `2026-01-01` .. `2026-04-01` | March 31 |

### Common workflows

**Auto-named files** (no `-o`):

```bash
uv run github-analysis run \
  --repo global-services \
  --month 2026-05 \
  --merged-only --workers 4
# → ~/github-analysis-results/global-services_2026-05-01_to_2026-06-01.xlsx (+ siblings)
```

**Five repos + combined workbook** — use the [monthly script](#each-month--run-in-terminal) or `scripts/run_cedt_trio.sh`.

**Analyze then export separately:**

```bash
uv run github-analysis analyze \
  --repo global-services \
  --start-date 2026-05-01 --end-date 2026-06-01 \
  --merged-only --workers 4 \
  -o ~/github-analysis-results/global-services-may-2026.tsv

uv run github-analysis export \
  --summary ~/github-analysis-results/global-services-may-2026_person_summary.tsv \
  --detail ~/github-analysis-results/global-services-may-2026.tsv \
  -o ~/github-analysis-results/global-services-may-2026.xlsx
```

**Rebuild from cache** (no GitHub fetch; person summary recomputed from cached timestamps):

```bash
uv run github-analysis analyze \
  --from-cache ~/github-analysis-results/global-services-may-2026_raw.json \
  --repo global-services \
  --start-date 2026-05-01 --end-date 2026-06-01 \
  --merged-only \
  -o ~/github-analysis-results/global-services-may-2026.tsv
```

**Monitor a run** (log path matches your `--start-date` and `--end-date`; written as soon as the run starts):

```bash
tail -f ~/github-analysis-results/global-services_2026-05-15_to_2026-06-01_run.log
```

---

## How a run works

| Phase | What happens |
|-------|----------------|
| Preflight | Verify `gh` auth and repo access |
| Phase 1 | Search for PRs in the date window |
| Phase 2 | Fetch each PR (metadata, commits, files, reviews) — **dominates runtime** |
| Phase 3 | Roll up per-person metrics |
| Phase 3b | Resolve PRs still open at window end |
| Write | TSV, cache, Excel |

Progress appears in `_run.log` as `[42/492] PR #317 (author)`. Files are written only after Phase 2 finishes. A busy month (~500 merged PRs) typically takes **6–10 minutes** with 4 workers.

---

## GitHub API limits

| Limit | Value | Affects |
|-------|-------|---------|
| REST quota | 5,000 requests/hour | ~6 calls per merged PR in Phase 2–3 |
| Search results | 1,000 matches per query | Phase 1 discovery |

**Check quota before a large run:**

```bash
gh api rate_limit --jq '.resources.core | "remaining=\(.remaining) reset=\(.reset)"'
```

Prefer **`remaining > 1,000`** before a full-month report on a busy repo. Quota resets hourly (`date -r RESET` on macOS).

**If a run fails**, open `_run.log`:

| Log message | Action |
|-------------|--------|
| `API rate limit exceeded` | Wait for reset; re-run one repo with `--workers 3` |
| Many `Skip PR #…` with rate-limit errors | Incomplete — re-run after reset |
| `Only the first 1000 search results are available` | Split the calendar window (e.g. two half-months); distinct `-o` paths |
| Missing `Fetch complete` or `skipped` > 0 | Do not use for production — re-run |

**Practices:** one full-month fetch per repo per hour; use `--from-cache` to rebuild Excel without re-fetching; shorter date windows for trial runs.

---

## Output columns

### Individual Production (`_person_summary.tsv`)

| Column | Description |
|--------|-------------|
| `user` | GitHub login |
| `prs_authored` | PRs **opened** in the calendar window (merged or not) |
| `prs_merged` | Their PRs **merged** in the window (any open date, including carry-over) |
| `prs_open` | Their PRs **still unmerged at window end** (any open date) |
| `prs_closed_unmerged` | PRs **they opened in the window** and **closed without merge** before window end |
| `prs_reviewed` | Distinct PRs with any review submitted in the window |
| `prs_approved` | Distinct PRs with an APPROVED review in the window |
| `avg_files_added_per_pr` | Mean new files per PR in the detail report |
| `avg_files_changed_per_pr` | Mean modified/renamed files per detail-row PR |
| `min/max/avg_hours_pr_created_to_merged` | Hours from PR open to merge (merged-in-window only; excludes `prs_open`) |

**PR count columns for PRs opened in the window** reconcile as:

For PRs **opened in the window only**, at window end each falls into exactly one outcome bucket:

`prs_authored` ≈ (window-opened PRs merged in window) + (window-opened PRs still open at end) + `prs_closed_unmerged`

**`prs_merged` and `prs_open` are not subsets of `prs_authored`** — they include carry-over PRs opened before the window, so column totals do not sum this way.

Example for May 2026 (`2026-05-01` .. `2026-06-01`):

| Scenario | `prs_authored` | `prs_merged` | `prs_open` | `prs_closed_unmerged` |
|----------|----------------|--------------|------------|------------------------|
| Opened May 31, merged in June | 1 | 0 | 1 | 0 |
| Opened May 15, merged May 20 | 1 | 1 | 0 | 0 |
| Opened in April, merged in May | 0 | 1 | 0 | 0 |
| Opened in April, still open May 31 | 0 | 0 | 1 | 0 |
| Opened May 10, closed without merge May 12 | 1 | 0 | 0 | 1 |
| Opened 8 in May; all 5 merges are among those 8; 2 still open; 1 closed unmerged | 8 | 5 | 2 | 1 |

Merge-cycle hours and file averages come from **detail report rows** only (merged PRs when `--merged-only`). Review counts use review `submitted_at`, not merge date.

### PR Detail (`.tsv`, header on row 3)

| Column | Description |
|--------|-------------|
| `pr_creator` | Who opened the PR |
| `pr_number`, `pr_url`, `head_branch` | PR identity |
| `branch_start` | First commit on the branch |
| `pr_created` | When the PR was opened |
| `first_draft`, `ready_for_review` | Draft / ready-for-review timestamps |
| `first_feedback`, `approved`, `approved_by` | Review timeline |
| `merged` | Merge timestamp (blank if not merged) |
| `*_hours_since_branch` | Elapsed hours from branch start |
| `hours_pr_created_to_*` | Elapsed hours from PR open |
| `pr_files_total/addded/modified/removed` | File counts |
| `pr_commits_total/before_pr_open/after_pr_open` | Commit counts |
| `notes` | Warnings (truncation, catalog mismatch, etc.) |

Timestamps use the report timezone as ISO-8601 with offset.

**Opening files:** open `.xlsx` directly. For TSV in Excel, import with Tab delimiter; rows 1–2 of the detail file are notes.

---

## Monthly metrics

With **`--merged-only`** (recommended for monthly manager reports):

- **PR detail sheet** — only PRs merged in the calendar window
- **Person summary** — still computes `prs_authored`, `prs_open`, `prs_closed_unmerged`, and review counts via separate searches

A PR counts toward **`prs_open`** at window end if it existed, had not merged, and was not closed without merge before window end — regardless of when it was opened.

A PR counts toward **`prs_closed_unmerged`** if they opened it in the window and it was closed without merge before window end.

---

## Attribution rules

| Metric | Counted as | Not used |
|--------|------------|----------|
| PR author | GitHub `user` on the pull request | Assignees, merge committer |
| Reviewer | Formal review with `submitted_at` in window | Comments without a review |
| Approver | Review with `state: APPROVED` | LGTM comments alone |
| File averages | Mean over detail-report PRs | — |
| Merge cycle time | PRs merged in the window | Still-open PRs, late merges |

---

## Configuration

Edit `github_analysis/config.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `DEFAULT_REPORT_TZ_NAME` / `--timezone` | `America/New_York` | Calendar dates and timestamps (override per run) |
| `DEFAULT_GITHUB_OWNER` | `Customer-Engagement-Digital-Technology` | Org for short `--repo` names |
| `DEFAULT_OUTPUT_DIR` | `~/Dev/github-analysis-results` | Default output folder when env var unset |
| `GITHUB_ANALYSIS_RESULTS` | — | Environment variable override for output folder (see [Output directory](#output-directory)) |
| `DEFAULT_FETCH_WORKERS` | `4` | Default `--workers` |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `uv` / `gh` not found | Complete [Install and setup](#install-and-setup) steps 1–2; ensure both are on `PATH` |
| `gh auth status` fails | Step 4: `gh auth login` or `gh auth login --with-token`; set `GH_TOKEN` for CI |
| `401` / `403` / `404` on org repo | PAT needs `repo` scope (classic) or read Contents + Pull requests (fine-grained); authorize org SSO |
| `openpyxl is required` | `uv sync --group excel` |
| Empty report | Widen dates; confirm activity in the window |
| Very slow / stuck at `[N/M]` | Normal for large months; wait or check `_run.log` |
| Rate limit / search cap | See [GitHub API limits](#github-api-limits) |

```bash
uv run github-analysis --version
gh auth status
gh repo view OWNER/REPO
```

---

## Limits

- One repository per run
- GitHub search: max **1,000 results per query** — split long date ranges if needed
- Reviews/comments: first 100 items per PR for timing
- Files/commits: up to 10,000 per PR (truncation noted in `notes`)

---

## For contributors

See [docs/](docs/README.md) for architecture and CLI extension notes.

## Delivery analytics app (new)

A local app that syncs delivery data into one SQLite file and shows it in the browser. The monthly GitHub report above is unchanged.

| Command | What it does |
|---------|--------------|
| `uv run delivery-analysis serve` | Start the app on `http://127.0.0.1:8000` (local only) and open the browser. Add `--no-browser` to skip opening it |
| `uv run delivery-analysis sync [--source NAME]` | Sync configured sources into the database. With none configured it says so |
| `uv run delivery-analysis doctor` | Show which credential variables (`ATLASSIAN`, `ANTHROPIC`, `ANTHROPIC_ADMIN`) are present. Names only, never values |

The database is `delivery.sqlite` in the output folder (`GITHUB_ANALYSIS_RESULTS`, default `~/github-analysis-results`). Credentials come from environment variables or a git-ignored `.env` in the repo root.
