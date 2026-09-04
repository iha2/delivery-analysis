from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from github_analysis.config import SEARCH_MAX_PAGES
from github_analysis.github.client import GhClient
from github_analysis.models import RepositoryRef

_SEARCH_RESULT_CAP = SEARCH_MAX_PAGES * 100


def _search_truncation_warning(query: str, result_count: int) -> str:
    return (
        f"GitHub search truncated at {result_count} result(s) for query: {query!r} "
        f"(cap {_SEARCH_RESULT_CAP} per query; split the date window)"
    )


def _catalog_from_queries(
    client: GhClient, queries: list[str]
) -> tuple[dict[int, str], list[str]]:
    """Map pull number -> PR creator login (`user` from search; assignees are not used)."""
    catalog: dict[int, str] = {}
    warnings: list[str] = []
    for query in queries:
        items, truncated = client.search_issues(query, max_pages=SEARCH_MAX_PAGES)
        if truncated:
            warnings.append(_search_truncation_warning(query, len(items)))
        for item in items:
            number = item.get("number")
            if number is None:
                continue
            login = ((item.get("user") or {}).get("login")) or ""
            catalog[int(number)] = login
    return catalog, warnings


def _repo_pr_base(repository: RepositoryRef) -> str:
    return f"repo:{repository.slug} is:pr"


def _last_inclusive_day(end_exclusive: date) -> date:
    return end_exclusive - timedelta(days=1)


def _calendar_range(field: str, start_inclusive: date, end_exclusive: date) -> str:
    """GitHub search inclusive date range matching the report calendar window."""
    return f"{field}:{start_inclusive.isoformat()}..{_last_inclusive_day(end_exclusive).isoformat()}"


def build_open_at_month_end_candidate_catalog(
    client: GhClient,
    repository: RepositoryRef,
    start_date: date,
    end_date: date,
) -> tuple[dict[int, str], list[str]]:
    """
    PRs that may have been open at month-end (regardless of when created).

    Candidates include PRs still open today, merged after the window, or closed after
    the window — then timestamp checks confirm the month-end snapshot.
    """
    end = end_date.isoformat()
    start = start_date.isoformat()
    last = _last_inclusive_day(end_date).isoformat()
    base = _repo_pr_base(repository)
    queries = [
        f"{base} is:open created:<{end}",
        f"{base} created:<{end} merged:>={end}",
        f"{base} created:<{end} closed:>={end}",
        f"{base} created:<{start} updated:{start}..{last}",
    ]
    catalog: dict[int, str] = {}
    warnings: list[str] = []
    for query in queries:
        chunk, query_warnings = _catalog_from_queries(client, [query])
        catalog.update(chunk)
        warnings.extend(query_warnings)
    return catalog, warnings


def build_created_in_window_catalog(
    client: GhClient,
    repository: RepositoryRef,
    start_date: date,
    end_date: date,
) -> tuple[dict[int, str], list[str]]:
    """PRs created (opened) in the calendar window — used for authored/open-at-month-end counts."""
    base = _repo_pr_base(repository)
    return _catalog_from_queries(
        client, [f"{base} {_calendar_range('created', start_date, end_date)}"]
    )


def build_merged_in_window_catalog(
    client: GhClient,
    repository: RepositoryRef,
    start_date: date,
    end_date: date,
) -> tuple[dict[int, str], list[str]]:
    """PRs merged in the calendar window — used for prs_merged counts."""
    base = _repo_pr_base(repository)
    return _catalog_from_queries(
        client, [f"{base} is:merged {_calendar_range('merged', start_date, end_date)}"]
    )


def build_activity_catalog(
    client: GhClient,
    repository: RepositoryRef,
    start_date: date,
    end_date: date,
    *,
    merged_only: bool = False,
) -> tuple[dict[int, str], list[str]]:
    base = _repo_pr_base(repository)
    queries = [f"{base} is:merged {_calendar_range('merged', start_date, end_date)}"]
    if not merged_only:
        queries.append(f"{base} {_calendar_range('created', start_date, end_date)}")
    return _catalog_from_queries(client, queries)


def build_review_catalog(
    client: GhClient,
    repository: RepositoryRef,
    start_date: date,
    end_date: date,
    *,
    activity_catalog: dict[int, str],
) -> tuple[dict[int, str], list[str]]:
    base = _repo_pr_base(repository)
    catalog = dict(activity_catalog)
    updated_catalog, warnings = _catalog_from_queries(
        client, [f"{base} {_calendar_range('updated', start_date, end_date)}"]
    )
    catalog.update(updated_catalog)
    return catalog, warnings


def group_prs_by_user(catalog: dict[int, str]) -> list[tuple[str, list[int]]]:
    by_user: dict[str, list[int]] = defaultdict(list)
    for pr_number, login in catalog.items():
        by_user[login or "(unknown)"].append(pr_number)
    return [
        (author, sorted(numbers))
        for author, numbers in sorted(by_user.items(), key=lambda item: item[0].lower())
    ]
