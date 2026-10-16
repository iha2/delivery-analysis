from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Mapping, Set, Tuple

from delivery_analysis.tokens.accounts import AccountMap
from delivery_analysis.tokens.config import DEFAULT_CONFIG, AttributionConfig
from delivery_analysis.tokens.types import TicketInfo, TicketKey, day_of


@dataclass
class EvidenceIndex:
    by_person: Dict[str, Dict[TicketKey, Dict[date, float]]] = field(default_factory=dict)
    untracked: Set[Tuple[str, date]] = field(default_factory=set)

    def add(self, person: str, ticket: TicketKey, day: date, weight: float) -> None:
        days = self.by_person.setdefault(person, {}).setdefault(ticket, {})
        days[day] = days.get(day, 0.0) + weight

    def for_person(self, person: str) -> Dict[TicketKey, Dict[date, float]]:
        return self.by_person.get(person, {})

    def totals(self) -> Dict[Tuple[TicketKey, str], float]:
        return {
            (ticket, person): sum(days.values())
            for person, tickets in self.by_person.items()
            for ticket, days in tickets.items()
        }


def _links(conn: sqlite3.Connection, from_kind: str, tickets: Mapping[TicketKey, TicketInfo]) -> Dict[str, Set[TicketKey]]:
    out: Dict[str, Set[TicketKey]] = {}
    for row in conn.execute(
        "SELECT from_id, to_id FROM link WHERE kind = 'implements' AND from_kind = ? AND to_kind = 'work_item'",
        (from_kind,),
    ):
        key = ("jira", row["to_id"])
        if key in tickets:
            out.setdefault(row["from_id"], set()).add(key)
    return out


def load_evidence(
    conn: sqlite3.Connection,
    accounts: AccountMap,
    tickets: Mapping[TicketKey, TicketInfo],
    config: AttributionConfig = DEFAULT_CONFIG,
) -> EvidenceIndex:
    """What each person did on each ticket on each UTC day, joined to tickets only through `link` rows."""
    index = EvidenceIndex()
    by_pr = _links(conn, "change_request", tickets)
    by_commit = _links(conn, "vcs_commit", tickets)
    merges = {
        row["record_id"]
        for row in conn.execute("SELECT record_id FROM property WHERE record_kind = 'vcs_commit' AND name = 'is_merge'")
    }
    for row in conn.execute(
        "SELECT source_id, author_account, author_email, committed_at, change_request_id FROM vcs_commit"
    ):
        if row["source_id"] in merges:
            continue
        person = accounts.commit_author(row["author_account"], row["author_email"])
        day = day_of(row["committed_at"])
        if person is None or day is None:
            continue
        keys = by_pr.get(row["change_request_id"] or "", set()) | by_commit.get(row["source_id"], set())
        if not keys:
            index.untracked.add((person, day))
            continue
        for key in keys:
            index.add(person, key, day, config.commit_weight)
    for row in conn.execute("SELECT source, source_id, author_account, created_at FROM change_request"):
        keys = by_pr.get(row["source_id"])
        person = accounts.person(row["source"], row["author_account"])
        day = day_of(row["created_at"])
        if keys and person and day:
            for key in keys:
                index.add(person, key, day, config.pr_created_weight)
    types = tuple(config.pr_event_types)
    if types:
        marks = ", ".join("?" for _ in types)
        for row in conn.execute(
            f"SELECT source, change_request_id, actor_account, occurred_at FROM change_event WHERE type IN ({marks})",
            types,
        ):
            keys = by_pr.get(row["change_request_id"] or "")
            person = accounts.person(row["source"], row["actor_account"])
            day = day_of(row["occurred_at"])
            if keys and person and day:
                for key in keys:
                    index.add(person, key, day, config.pr_event_weight)
    for row in conn.execute(
        "SELECT work_item_id, actor_account, occurred_at FROM work_item_transition WHERE source = 'jira'"
    ):
        key = ("jira", row["work_item_id"])
        person = accounts.person("jira", row["actor_account"])
        day = day_of(row["occurred_at"])
        if key in tickets and person and day:
            index.add(person, key, day, config.transition_weight)
    return index
