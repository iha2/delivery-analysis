from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from github_analysis.github.pulls import PullRequestService
from github_analysis.time_utils import parse_github_ts


def _reviewers_in_window_by_state(
    reviews: list[dict[str, Any]],
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
    *,
    approved_only: bool = False,
) -> set[str]:
    """Distinct reviewer logins for reviews submitted in the window."""
    reviewers: set[str] = set()
    for review in reviews:
        if approved_only and (review.get("state") or "").upper() != "APPROVED":
            continue
        submitted = parse_github_ts(review.get("submitted_at"))
        if submitted is None:
            continue
        if submitted < start_inclusive_utc or submitted >= end_exclusive_utc:
            continue
        login = ((review.get("user") or {}).get("login")) or ""
        if login:
            reviewers.add(login)
    return reviewers


def reviewers_in_window(
    reviews: list[dict[str, Any]],
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
) -> set[str]:
    return _reviewers_in_window_by_state(
        reviews, start_inclusive_utc, end_exclusive_utc, approved_only=False
    )


def approvers_in_window(
    reviews: list[dict[str, Any]],
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
) -> set[str]:
    return _reviewers_in_window_by_state(
        reviews, start_inclusive_utc, end_exclusive_utc, approved_only=True
    )


def _collect_counts_by_user(
    service: PullRequestService,
    pull_numbers: list[int],
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
    *,
    reviews_cache: Optional[dict[int, list[dict[str, Any]]]] = None,
    approved_only: bool,
) -> dict[str, int]:
    cache = reviews_cache if reviews_cache is not None else {}
    counts: dict[str, set[int]] = defaultdict(set)
    picker = approvers_in_window if approved_only else reviewers_in_window
    for pull_number in sorted(set(pull_numbers)):
        if pull_number not in cache:
            cache[pull_number] = service.reviews(pull_number)
        for login in picker(cache[pull_number], start_inclusive_utc, end_exclusive_utc):
            counts[login].add(pull_number)
    return {login: len(prs) for login, prs in counts.items()}


def collect_review_counts_by_user(
    service: PullRequestService,
    pull_numbers: list[int],
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
    *,
    reviews_cache: Optional[dict[int, list[dict[str, Any]]]] = None,
) -> dict[str, int]:
    """Distinct PRs where the person submitted any review in the window."""
    return _collect_counts_by_user(
        service,
        pull_numbers,
        start_inclusive_utc,
        end_exclusive_utc,
        reviews_cache=reviews_cache,
        approved_only=False,
    )


def collect_approval_counts_by_user(
    service: PullRequestService,
    pull_numbers: list[int],
    start_inclusive_utc: datetime,
    end_exclusive_utc: datetime,
    *,
    reviews_cache: Optional[dict[int, list[dict[str, Any]]]] = None,
) -> dict[str, int]:
    """Distinct PRs where the person submitted an APPROVED review in the window."""
    return _collect_counts_by_user(
        service,
        pull_numbers,
        start_inclusive_utc,
        end_exclusive_utc,
        reviews_cache=reviews_cache,
        approved_only=True,
    )
