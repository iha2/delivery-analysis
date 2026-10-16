from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

TicketKey = Tuple[str, str]  # (work_item.source, work_item.source_id)


def day_of(timestamp: Optional[str]) -> Optional[date]:
    """The UTC date of a stored UTC ISO timestamp (`YYYY-MM-DDTHH:MM:SSZ`) or a bare date."""
    if not timestamp:
        return None
    return date.fromisoformat(timestamp[:10])


@dataclass(frozen=True)
class Candidate:
    """A ticket that may receive part of one person-day's cost."""

    ticket: TicketKey
    evidence: float  # the person's weighted evidence on this ticket on that day
    known: bool  # the person has evidence on this ticket on some day (False: related only as assignee)


@dataclass(frozen=True)
class Allocation:
    """One row of a person-day split. `ticket` is None for the unattributed row."""

    ticket: Optional[TicketKey]
    cost_usd: float
    weight: Optional[float]
    evidence: Optional[float]
    method: str
    confidence: Optional[str]
    reason: Optional[str] = None


@dataclass
class TicketInfo:
    key: TicketKey
    issue_key: str
    project: str
    type: str
    eligible: bool  # may be a candidate (not Epic or Initiative)
    status_category: Optional[str]
    assignee_person: Optional[str]
    story_points: Optional[float]
    counts_for_impact: bool
    started_at: Optional[str]
    resolved_at: Optional[str]
    transitions: List[Tuple[str, Optional[str]]] = field(default_factory=list)  # (UTC time, category)
    merges: List[str] = field(default_factory=list)  # merged_at of linked pull requests
    parent: Optional[TicketKey] = None  # the parent issue, for a sub-task


class RebuildError(RuntimeError):
    """The rebuild found an inconsistency and changed nothing."""
