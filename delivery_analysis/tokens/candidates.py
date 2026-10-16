from __future__ import annotations

from datetime import date
from typing import Collection, Iterable, List, Mapping, Optional, Sequence, Tuple

from delivery_analysis.tokens.config import DEFAULT_CONFIG, AttributionConfig
from delivery_analysis.tokens.types import Candidate, TicketKey, day_of

Interval = Tuple[date, Optional[date]]  # inclusive; end None means still open


def active_intervals(transitions: Sequence[Tuple[str, Optional[str]]], merges: Sequence[str]) -> List[Interval]:
    """Spans in an in_progress status, each cut at the first linked merge inside it."""
    events = [(when, 0, category) for when, category in transitions] + [(when, 1, None) for when in merges]
    events.sort(key=lambda event: (event[0], event[1]))
    spans: List[Interval] = []
    start: Optional[str] = None
    current: Optional[str] = None
    for when, kind, category in events:
        if kind == 1:
            if start is not None and when >= start:
                spans.append((day_of(start), day_of(when)))
                start = None
            continue
        if category == "in_progress" and current != "in_progress":
            start = when
        elif category != "in_progress" and current == "in_progress" and start is not None:
            spans.append((day_of(start), day_of(when)))
            start = None
        current = category
    if start is not None:
        spans.append((day_of(start), None))
    return spans


def _span_start(day: date, intervals: Sequence[Interval], today: date) -> Optional[date]:
    for start, end in intervals:
        if start <= day <= (end or today):
            return start
    return None


def candidates_for_day(
    day: date,
    today: date,
    assigned: Iterable[TicketKey],
    evidence: Mapping[TicketKey, Mapping[date, float]],
    intervals: Mapping[TicketKey, Sequence[Interval]],
    eligible: Collection[TicketKey],
    config: AttributionConfig = DEFAULT_CONFIG,
) -> List[Candidate]:
    """The person's candidate tickets on `day`: evidence that day, or a live span they relate to."""
    found: List[Candidate] = []
    for ticket in sorted(set(assigned) | set(evidence)):
        if ticket not in eligible:
            continue
        days = evidence.get(ticket, {})
        known = any(value > 0 for value in days.values())
        today_evidence = days.get(day, 0.0)
        if today_evidence > 0:
            found.append(Candidate(ticket, today_evidence, True))
            continue
        start = _span_start(day, intervals.get(ticket, ()), today)
        if start is None:
            continue
        last = max([d for d, value in days.items() if value > 0 and d <= day] + [start])
        if (day - last).days > config.idle_days:
            continue
        found.append(Candidate(ticket, 0.0, known))
    return found
