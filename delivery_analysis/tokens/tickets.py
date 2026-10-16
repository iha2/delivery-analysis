from __future__ import annotations

import sqlite3
from typing import Dict, Set, Tuple

from delivery_analysis.tokens.accounts import AccountMap
from delivery_analysis.tokens.types import TicketInfo, TicketKey

DEFAULT_EXCLUDED_TYPES = frozenset({"Epic", "Initiative"})


def _excluded_types(conn: sqlite3.Connection) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    for row in conn.execute("SELECT project_key, excluded_types FROM project_selection WHERE source = 'jira'"):
        out[row["project_key"]] = set(DEFAULT_EXCLUDED_TYPES) | {
            t.strip() for t in (row["excluded_types"] or "").split(",") if t.strip()
        }
    return out


def load_tickets(conn: sqlite3.Connection, accounts: AccountMap) -> Dict[TicketKey, TicketInfo]:
    """Jira work items with status categories over time and the merge times of linked pull requests."""
    excluded = _excluded_types(conn)
    categories: Dict[Tuple[str, str], str] = {
        (row["project_key"], row["status_name"]): row["category"]
        for row in conn.execute("SELECT project_key, status_name, category FROM status_mapping WHERE source = 'jira'")
    }
    impact = {
        row["record_id"]
        for row in conn.execute(
            "SELECT record_id FROM property WHERE record_kind = 'work_item' AND name = 'counts_for_impact' AND value = '1'"
        )
    }
    tickets: Dict[TicketKey, TicketInfo] = {}
    for row in conn.execute(
        "SELECT source, source_id, key, project, type, status_category, assignee_account, story_points, "
        "started_at, resolved_at FROM work_item WHERE source = 'jira'"
    ):
        key = (row["source"], row["source_id"])
        project = row["project"] or ""
        kind = row["type"] or ""
        tickets[key] = TicketInfo(
            key=key,
            issue_key=row["key"] or row["source_id"],
            project=project,
            type=kind,
            eligible=kind not in excluded.get(project, set(DEFAULT_EXCLUDED_TYPES)),
            status_category=row["status_category"],
            assignee_person=accounts.person("jira", row["assignee_account"]),
            story_points=row["story_points"],
            counts_for_impact=row["source_id"] in impact,
            started_at=row["started_at"],
            resolved_at=row["resolved_at"],
        )
    for row in conn.execute(
        "SELECT work_item_id, to_status, occurred_at FROM work_item_transition "
        "WHERE source = 'jira' AND occurred_at IS NOT NULL ORDER BY occurred_at, source_id"
    ):
        info = tickets.get(("jira", row["work_item_id"]))
        if info is not None:
            info.transitions.append((row["occurred_at"], categories.get((info.project, row["to_status"]))))
    for row in conn.execute(
        "SELECT l.to_id AS to_id, c.merged_at AS merged_at FROM link l "
        "JOIN change_request c ON c.source_id = l.from_id "
        "WHERE l.kind = 'implements' AND l.from_kind = 'change_request' AND l.to_kind = 'work_item' "
        "AND c.merged_at IS NOT NULL ORDER BY c.merged_at"
    ):
        info = tickets.get(("jira", row["to_id"]))
        if info is not None:
            info.merges.append(row["merged_at"])
    for row in conn.execute(
        "SELECT from_id, to_id FROM link WHERE kind = 'parent' AND from_kind = 'work_item' AND to_kind = 'work_item'"
    ):
        info = tickets.get(("jira", row["from_id"]))
        if info is not None and ("jira", row["to_id"]) in tickets:
            info.parent = ("jira", row["to_id"])
    return tickets
