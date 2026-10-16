from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

TicketKey = Tuple[str, str]


@dataclass(frozen=True)
class Credit:
    ticket: TicketKey
    person_id: str
    share: float
    evidence: float
    method: str  # "evidence_share" or "assignee"


def roll_up_evidence(
    evidence_totals: Mapping[Tuple[TicketKey, str], float],
    parents: Mapping[TicketKey, Optional[TicketKey]],
) -> Dict[Tuple[TicketKey, str], float]:
    """Move each sub-task's evidence onto its top-level ancestor so the parent's credit follows who did the work."""

    def top(ticket: TicketKey) -> TicketKey:
        seen = {ticket}
        while parents.get(ticket) and parents[ticket] not in seen:
            ticket = parents[ticket]  # type: ignore[assignment]
            seen.add(ticket)
        return ticket

    out: Dict[Tuple[TicketKey, str], float] = {}
    for (ticket, person), value in evidence_totals.items():
        key = (top(ticket), person)
        out[key] = out.get(key, 0.0) + value
    return out


def compute_credit(
    evidence_totals: Mapping[Tuple[TicketKey, str], float],
    assignees: Mapping[TicketKey, Optional[str]],
) -> Tuple[List[Credit], int]:
    """Each person's share of a ticket's evidence over all days; no evidence gives the assignee 100%."""
    by_ticket: Dict[TicketKey, Dict[str, float]] = {}
    for (ticket, person), value in evidence_totals.items():
        if value > 0:
            people = by_ticket.setdefault(ticket, {})
            people[person] = people.get(person, 0.0) + value
    credits: List[Credit] = []
    uncredited = 0
    for ticket in sorted(set(assignees) | set(by_ticket)):
        people = by_ticket.get(ticket)
        if people:
            total = sum(people.values())
            for person in sorted(people):
                credits.append(
                    Credit(ticket, person, round(people[person] / total, 6), round(people[person], 6), "evidence_share")
                )
        elif assignees.get(ticket):
            credits.append(Credit(ticket, str(assignees[ticket]), 1.0, 0.0, "assignee"))
        else:
            uncredited += 1
    return credits, uncredited
