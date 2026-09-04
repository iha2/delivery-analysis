from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from github_analysis.config import API_LIST_PAGES_MAX
from github_analysis.github.client import GhClient
from github_analysis.models import RepositoryRef
from github_analysis.time_utils import parse_github_ts


class PullRequestService:
    """Fetch pull-request resources for one repository."""

    def __init__(self, client: GhClient, repository: RepositoryRef) -> None:
        self._client = client
        self._repository = repository

    def _path(self, suffix: str) -> str:
        return f"/repos/{self._repository.owner}/{self._repository.name}{suffix}"

    def detail(self, pull_number: int) -> dict[str, Any]:
        return self._client.get(self._path(f"/pulls/{pull_number}"))

    def commits(self, pull_number: int) -> tuple[list[dict[str, Any]], bool]:
        return self._client.paginate_list(
            self._path(f"/pulls/{pull_number}/commits"),
            max_pages=API_LIST_PAGES_MAX,
        )

    def files(self, pull_number: int) -> tuple[list[dict[str, Any]], bool]:
        return self._client.paginate_list(
            self._path(f"/pulls/{pull_number}/files"),
            max_pages=API_LIST_PAGES_MAX,
        )

    def reviews(self, pull_number: int) -> list[dict[str, Any]]:
        return self._client.get_list(self._path(f"/pulls/{pull_number}/reviews"))

    def issue_events(self, pull_number: int) -> list[dict[str, Any]]:
        return self._client.get_list(self._path(f"/issues/{pull_number}/events"))

    def issue_comments(self, pull_number: int) -> list[dict[str, Any]]:
        return self._client.get_list(self._path(f"/issues/{pull_number}/comments"))


def commit_timestamp(commit_payload: dict[str, Any]) -> Optional[datetime]:
    commit = commit_payload.get("commit") or {}
    authored = commit.get("author") or {}
    raw = authored.get("date") or (commit.get("committer") or {}).get("date")
    if not raw:
        return None
    return parse_github_ts(raw)


def branch_start_from_commits(commits: list[dict[str, Any]]) -> Optional[datetime]:
    best: Optional[datetime] = None
    for commit in commits:
        ts = commit_timestamp(commit)
        if ts and (best is None or ts < best):
            best = ts
    return best


def commits_before_after_open(
    commits: list[dict[str, Any]], pr_open: Optional[datetime]
) -> tuple[Optional[int], Optional[int]]:
    if pr_open is None:
        return None, None
    before = 0
    after = 0
    for commit in commits:
        ts = commit_timestamp(commit)
        if ts is None:
            after += 1
        elif ts < pr_open:
            before += 1
        else:
            after += 1
    return before, after


def file_counts(files: list[dict[str, Any]]) -> tuple[int, int, int, int]:
    added = removed = modified = 0
    for file_row in files:
        status = (file_row.get("status") or "").lower()
        if status == "added":
            added += 1
        elif status == "removed":
            removed += 1
        else:
            modified += 1
    return len(files), added, modified, removed
