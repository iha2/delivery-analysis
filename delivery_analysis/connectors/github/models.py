from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RepositoryRef:
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class ReportConfig:
    repository: RepositoryRef
    start_date: date
    end_date: date  # exclusive
    report_tz: ZoneInfo
    merged_only: bool = False
    include_summary: bool = True


@dataclass
class PullRequestRow:
    author: str
    branch: str
    pr_number: int
    pr_url: str
    branch_start: Optional[datetime]
    pr_created: Optional[datetime]
    first_draft: Optional[datetime]
    ready_for_review: Optional[datetime]
    first_feedback: Optional[datetime]
    approved: Optional[datetime]
    merged: Optional[datetime]
    closed_at: Optional[datetime]
    approved_by: str = ""
    notes: str = ""
    pr_files_total: int = 0
    pr_files_added: int = 0
    pr_files_modified: int = 0
    pr_files_removed: int = 0
    pr_commits_total: int = 0
    pr_commits_before_pr_open: Optional[int] = None
    pr_commits_after_pr_open: Optional[int] = None


@dataclass
class UserSummary:
    """Per-person production metrics (one row per GitHub login)."""

    user: str
    prs_merged: int
    prs_reviewed: int
    prs_approved: int
    prs_authored: int
    prs_open: int
    prs_closed_unmerged: int
    avg_files_added_per_pr: str
    avg_files_changed_per_pr: str
    min_hours_pr_created_to_merged: str = ""
    max_hours_pr_created_to_merged: str = ""
    avg_hours_pr_created_to_merged: str = ""


@dataclass
class ReportResult:
    config: ReportConfig
    rows: list[PullRequestRow] = field(default_factory=list)
    summaries: list[UserSummary] = field(default_factory=list)
    skipped_pr_numbers: list[int] = field(default_factory=list)
    start_utc: Optional[datetime] = None
    end_exclusive_utc: Optional[datetime] = None
