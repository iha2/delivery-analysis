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
