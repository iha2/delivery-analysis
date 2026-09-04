# Metrics review — findings and recommendations

**Review date:** 2026-06-01  
**Scope:** Person-summary metrics semantics, code quality, documentation accuracy, and gaps between the two.

---

## Executive summary

The core snapshot logic in `authored_activity.py` (`is_open_at_month_end`, `is_closed_unmerged_in_window`) and the half-open window in `window_bounds_utc()` **match intended business semantics**. Count helpers built on those functions are structurally correct.

Verification against May 2026 production caches (`global-services`, `global-user-services`, `polaris-turbo`) and manual tracing for `monika-sbd` confirms window-opened PR reconciliation holds. GitHub search cross-check for authored PRs matched exactly.

**Main risks are operational, not algorithmic:**

1. GitHub search **1,000-result cap** with no runtime warning in code.
2. **`prs_merged` depends on Phase 2 detail rows** (activity catalog), not an independent merged catalog + state fetch — skipped or truncated fetches can undercount merges.
3. **Stale `summaries` embedded in older `_raw.json` caches** (pre-`prs_closed_unmerged`) — `--from-cache` recomputes correctly, but reading cached summaries directly is misleading.
4. **README reconciliation formula is incorrect** as written and contradicts its own example table.

No automated tests exist today. Documentation in `export/tsv.py` is mostly accurate; README needs the reconciliation fix called out in the handoff.

---

## 1. Metrics verdict (per column)

| Column | Verdict | Evidence |
|--------|---------|----------|
| `prs_authored` | **Correct** | `counts_authored_in_window()` filters `created_pr_states` with `start_utc <= pr_created < end_exclusive_utc`. Uses `build_created_in_window_catalog()` + Phase 3b state resolution, not detail rows alone. `monika-sbd` / global-services: 2 authored PRs (#525, #528) match `gh search` (`created:2026-05-01..2026-05-31`, author filter). |
| `prs_merged` | **Acceptable with caveats** | `counts_merged_in_window_from_rows()` correctly filters `merged` timestamp in `[start, end)`. Carry-over merges work when present in activity catalog and fetched (e.g. `shubhamsbd`: merged=8 > authored=7 in global-services). **Caveat:** population is Phase 2 detail rows only; skipped PRs or search truncation on the merged query are not recovered via Phase 3b. |
| `prs_open` | **Correct** (catalog completeness dependent) | `is_open_at_month_end()` matches handoff §8. Open-candidate catalog uses four complementary searches; timestamp filter in Phase 3b is correct. `monika-sbd` / global-services: PR #528 (open at end) counted; PR #525 (closed unmerged) excluded from open. Carry-over confirmed (`antoniwan`: authored=0, open=1). |
| `prs_closed_unmerged` | **Correct** | `is_closed_unmerged_in_window()` matches handoff §8. PR #525 correctly bucketed for `monika-sbd`. Mutually exclusive with `prs_open` at window end for the same PR. |
| `prs_reviewed` | **Correct** (by code inspection) | `reviews.py` counts distinct PRs per reviewer using `submitted_at in [start, end)`. Comments without formal review objects excluded. |
| `prs_approved` | **Correct** (by code inspection) | Same as reviewed, filtered to `state == APPROVED`. |
| `avg_files_*` | **Correct semantics, documented mismatch** | Mean over user's **detail rows** (activity catalog), not all authored PRs. Under `--merged-only`, averages are over merged-in-window PRs only — acceptable if documented (README does mention this). |
| Merge-cycle hours | **Correct semantics, documented mismatch** | `_merge_cycle_stats()` filters to PRs merged in window; excludes still-open PRs. Same population caveat as file averages. |

### Window-opened reconciliation (validated)

For window-opened PRs only, the identity from handoff §1 holds in production data:

| Repo | User | authored | merged+open+closed_um | Match |
|------|------|----------|------------------------|-------|
| global-services | monika-sbd | 2 | 0+1+1 = 2 | Yes |
| global-user-services | monika-sbd | 3 | 3+0+0 = 3 | Yes |
| polaris-turbo | monika-sbd | 10 | 9+0+1 = 10 | Yes |

---

## 2. Gap list

### 2.1 Search truncation (high severity for large repos)

- `SEARCH_MAX_PAGES = 20` → max 1,000 results per query (`config.py`).
- `GhClient.search_issues()` paginates but **does not detect or log truncation** (unlike `paginate_list()`, which sets a `truncated` flag).
- May 2026 caches are well under the cap (largest created catalog: polaris-turbo 294). No truncation in these runs, but polaris-turbo `created` (294) vs `activity` (238) shows catalogs diverge by design — not a bug.
- **Risk:** Silent undercount if any single Phase 1 query exceeds 1,000 matches.

### 2.2 `prs_merged` population vs other counts (medium)

| Metric | Data source |
|--------|-------------|
| `prs_authored`, `prs_open`, `prs_closed_unmerged` | Dedicated catalogs + Phase 3b state fetches |
| `prs_merged` | Phase 2 detail rows (`activity_catalog` only) |

If a merged-in-window PR is in the activity catalog but Phase 2 skips it, `prs_merged` undercounts while Phase 3b could have resolved its state for other paths. No skipped PRs in the three May 2026 caches (`skipped_pr_numbers: []`), so not observed in production artifacts reviewed.

### 2.3 Stale summaries in `_raw.json` (medium)

Recomputing global-services from cache (`--from-cache`) produced **8 mismatches**, all on `prs_closed_unmerged`: cached value `0`, recomputed correct value (1–4). The cached `summaries` array was written before `prs_closed_unmerged` was implemented; `load_raw_cache()` recomputes from `created_pr_states` when present.

**Impact:** Excel/TSV produced at original run time may have `prs_closed_unmerged=0` for everyone. Re-export from cache fixes it.

### 2.4 `--from-cache` fallback for `open_pr_states` (low–medium)

```python
# cache/raw_store.py
if not open_pr_states:
    open_pr_states = created_pr_states
```

Older caches without `open_pr_states` will **understate `prs_open`** for carry-over PRs (opened before window, still open at end). Current May 2026 caches include `open_pr_states`.

### 2.5 Open-at-end candidate catalog (low, unproven gap)

The four-query strategy in `build_open_at_month_end_candidate_catalog()` appears sufficient for scenarios analyzed (pre-window create + no in-window activity + closed/merged after window covered by `closed:>=end` / `merged:>=end`). No counterexample found in production data. Formal proof not attempted; recommend a unit-test matrix of synthetic timestamps.

### 2.6 Author attribution (low)

- Phase 1 catalog stores search `user.login`.
- Detail rows and Phase 3b fetches use live API `user.login`.
- `pr_builder.py` records `catalog_author_mismatch:{catalog_login}` in `notes` when they differ. No mismatches flagged in reviewed caches.

### 2.7 Observability gaps

- Search truncation not logged.
- Phase 3b skip messages go to run log (`Skip created PR #…` / `Skip open-candidate PR #…`) — adequate for audit if log is retained.
- `_log_person_coverage()` warns on catalog authors with no detail rows; does not warn when `open_pr_states` fetch count < `open_candidate_catalog` size.

---

## 3. Documentation patch list

### 3.1 README — reconciliation formula (required)

**Location:** README.md, “PR count columns for PRs opened in the window reconcile as”

**Problem:** Current formula uses column totals:

```
prs_authored ≈ prs_merged + prs_open + prs_closed_unmerged
```

`prs_merged` and `prs_open` include carry-over PRs (opened before the window). The example table on the next lines already contradicts this (e.g. “Opened in April, still open May 31 → authored=0, open=1”).

**Recommended replacement:**

> For PRs **opened in the window only**, at window end each falls into exactly one bucket:
>
> `prs_authored ≈ (window-opened PRs merged in window) + (window-opened PRs still open at end) + prs_closed_unmerged`
>
> **`prs_merged` and `prs_open` are not subsets of `prs_authored`** — they can exceed it when counting carry-over PRs opened before the window.

### 3.2 README — example row “Opened 8 in May; merged 5…” (required)

Clarify that the 5 merges must all be among the 8 window-opened PRs, or split into two examples (one with carry-over merges inflating `prs_merged`).

### 3.3 README — date windows (no change needed)

README “Date windows” section accurately describes half-open semantics and matches `window_bounds_utc()` (verified: May window = `2026-05-01 04:00 UTC` .. `2026-06-01 04:00 UTC` for Eastern).

### 3.4 `export/tsv.py` footnotes (minor)

Person-summary header is largely correct and **better than README** on open-at-end semantics. Minor tweak suggested:

- Current: `prs_merged = PRs they authored that merged`
- Prefer: `prs_merged = PRs they authored that merged in the calendar window (any open date, including carry-over)`

Aligns with README column table and removes ambiguity.

### 3.5 `architecture.md` Phase 3b (minor)

Add that Phase 3b uses **separate catalogs**:

- `build_created_in_window_catalog()` → `prs_authored`, `prs_closed_unmerged`
- `build_open_at_month_end_candidate_catalog()` → `prs_open` candidates

Currently only labels Phase 3b as “Open-at-window-end snapshot” without mentioning the created catalog path.

### 3.6 Terminology (optional)

Code and logs use `open_at_month_end` / “month-end” for arbitrary windows (e.g. one-week reports). Consider “open at window end” in user-facing docs; code rename optional.

---

## 4. Code patch list (prioritized)

### P1 — Log search truncation warnings

**File:** `github_analysis/github/client.py` — `search_issues()`

Compare `len(items)` to `total_count` from the search API response (or detect `page == max_pages` with full page). Emit a run-log warning when results are capped. README already documents the 1,000 limit; code should surface it.

### P1 — Fix README reconciliation (docs only)

See §3.1. Highest user-facing impact.

### P2 — Unify `prs_merged` data path

**Options (pick one):**

1. **Remove dead code:** Delete unused `counts_merged_in_window()` in `authored_activity.py`, **or**
2. **Harden merged counts:** Build a `merged_in_window_catalog` (already part of `build_activity_catalog` query 1) and resolve states in Phase 3b, using `counts_merged_in_window(merged_pr_states, …)` instead of detail rows. Recovers merges when Phase 2 detail fetch fails but Phase 3b state fetch succeeds.

Current runner uses only `counts_merged_in_window_from_rows()` — the `counts_merged_in_window()` on `pr_states` dict is **dead code**.

### P2 — Recompute summaries on cache load always

`load_raw_cache()` already recomputes when `created_pr_states` exists. Consider **never trusting** embedded `summaries` in cache (always recompute) and optionally strip `summaries` from save payload to avoid stale reads.

### P3 — Add unit tests

No test files exist. Recommended module: `tests/test_authored_activity.py`, `tests/test_time_utils.py`.

| Test case | Function |
|-----------|----------|
| Pre-window create, open at end | `is_open_at_month_end` → True |
| Pre-window create, merged in window | `is_open_at_month_end` → False |
| Opened in window, closed unmerged in window | `is_closed_unmerged_in_window` → True |
| Opened in window, still open at end | `is_closed_unmerged_in_window` → False; `is_open_at_month_end` → True |
| Event exactly at `end_exclusive_utc` | boundary behavior documented |
| DST spring/fall boundaries | `window_bounds_utc()` |
| Window-opened reconciliation | synthetic `pr_states` fixture |

### P3 — `compute_user_summaries()` legacy fallback

When `authored_in_month_by_user is None`, fallback uses `len(detail_rows)` for authored and `len(detail_rows) - merged` for open — incorrect for production semantics. Consider raising if Phase 3b counts are missing rather than silently using legacy math.

---

## 5. Verification performed

### Step A — Recompute from cache

```bash
uv run github-analysis analyze \
  --from-cache ~/Documents/global-services-may-2026_raw.json \
  --repo global-services \
  --start-date 2026-05-01 --end-date 2026-06-01 \
  -o /tmp/gs-verify.tsv
```

24 users compared; **8 mismatches**, all `prs_closed_unmerged` (cached 0 vs recomputed correct). All other columns matched.

### Step B — Spot-check `monika-sbd`

| Repo | authored | merged | open | closed_unmerged | Reconciliation |
|------|----------|--------|------|-----------------|----------------|
| global-services | 2 | 0 | 1 | 1 | 0+1+1 = 2 ✓ |
| global-user-services | 3 | 3 | 0 | 0 | 3+0+0 = 3 ✓ |
| polaris-turbo | 10 | 9 | 0 | 1 | 9+0+1 = 10 ✓ |

global-services PR trace:

| PR | created (UTC) | merged | closed (UTC) | Bucket |
|----|---------------|--------|--------------|--------|
| #525 | 2026-05-26 | — | 2026-05-27 | `prs_closed_unmerged` |
| #528 | 2026-05-27 | — | — | `prs_open` |

### Step C — GitHub API cross-check

```bash
gh api "search/issues?q=repo:Customer-Engagement-Digital-Technology/global-services+is:pr+author:monika-sbd+created:2026-05-01..2026-05-31"
# total_count: 2 — matches prs_authored
```

### Step D — Search cap audit

| Repo | Max catalog size | Under 1,000? |
|------|------------------|--------------|
| global-services | created: 206 | Yes |
| global-user-services | created: 53 | Yes |
| polaris-turbo | created: 294, review: 311 | Yes |

No truncation observed in May 2026 artifacts.

---

## 6. Checklist results (from handoff §3–§4)

| Item | Result |
|------|--------|
| Half-open interval consistent | **Pass** — all count helpers use `>= start`, `< end_exclusive` |
| README date windows | **Pass** |
| Boundary at `--end-date 00:00 Eastern` excluded | **Pass** (by `window_bounds_utc` design) |
| `prs_authored` uses created catalog | **Pass** |
| `prs_merged` carry-over | **Pass** (when in activity catalog + fetched) |
| `prs_open` snapshot logic | **Pass** |
| Open candidate catalog completeness | **Pass** (no counterexample found; not formally proven) |
| `prs_closed_unmerged` mutual exclusivity with open | **Pass** |
| Review counts distinct PRs, `submitted_at` window | **Pass** (code inspection) |
| `--from-cache` recomputation | **Pass** (with stale-summary caveat) |
| Detail vs summary population mismatch documented | **Partial** — README mentions detail rows for averages; could be clearer for `prs_merged` |
| Dead `counts_merged_in_window()` | **Confirmed unused** |
| Automated tests | **None** |
| Search cap warning in code | **Fail** — not implemented |

---

## 7. Recommended next steps

1. **Patch README** reconciliation section and example table (§3.1–3.2).
2. **Add search truncation warning** in `GhClient.search_issues()` (P1).
3. **Re-export May 2026 reports** from cache if `prs_closed_unmerged` was consumed from original run output.
4. **Add unit tests** for `authored_activity.py` and `time_utils.py` (P3).
5. **Remove or wire up** `counts_merged_in_window()` — avoid two parallel implementations.
6. **Update `architecture.md`** to document separate Phase 1 catalogs for created vs open-candidate PRs.

---

## Appendix — core logic confirmation

The implementation matches handoff §8 verbatim:

```python
# github_analysis/analysis/authored_activity.py

def is_open_at_month_end(..., end_exclusive_utc):
    if pr_created is None or pr_created >= end_exclusive_utc: return False
    if merged_at is not None and merged_at < end_exclusive_utc: return False
    if closed_at is not None and closed_at < end_exclusive_utc: return False
    return True

def is_closed_unmerged_in_window(..., start_inclusive_utc, end_exclusive_utc):
    if pr_created is None or pr_created < start_inclusive_utc or pr_created >= end_exclusive_utc: return False
    if merged_at is not None: return False
    if closed_at is None or closed_at >= end_exclusive_utc: return False
    return True
```

Remaining correctness risk is **catalog completeness and search truncation**, not the count-helper structure.
