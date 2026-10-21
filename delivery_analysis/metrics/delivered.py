from __future__ import annotations

import sqlite3
from typing import Mapping, Optional, Sequence, Tuple

DELIVERED_STATUSES: Tuple[str, ...] = (
    "Dev Done", "Ready for Release", "Ready for UAT", "UAT", "UAT Passed", "COMPLETED",
)
ENV_VAR = "DELIVERED_STATUSES"

# Databases that never ran derive_delivered keep the old meaning: done and resolved.
DELIVERED_AT_SQL = "COALESCE(w.delivered_at, CASE WHEN w.status_category = 'done' THEN w.resolved_at END)"


def delivered_statuses(environ: Optional[Mapping[str, str]] = None) -> Tuple[str, ...]:
    """The statuses that count as delivered: the env var (comma-separated) when set, else the default."""
    raw = (environ or {}).get(ENV_VAR) or ""
    names = tuple(name.strip() for name in raw.split(",") if name.strip())
    return names or DELIVERED_STATUSES


def derive_delivered(conn: sqlite3.Connection, statuses: Optional[Sequence[str]] = None) -> int:
    """Set work_item.delivered_at for every Jira item; returns how many items are delivered.

    An item is delivered when its current status is in the delivered set or its status category is done.
    It gets the earliest transition into any delivered status, else its resolved date. Every other Jira
    item (regressed, dropped, still open) gets NULL; DELIVERED_AT_SQL's fallback only serves databases
    that never ran this.
    """
    names = tuple(statuses) if statuses is not None else DELIVERED_STATUSES
    marks = ",".join("?" for _ in names) or "NULL"
    with conn:
        conn.execute(
            "UPDATE work_item SET delivered_at = CASE WHEN status IN (" + marks + ") OR status_category = 'done' THEN COALESCE("
            "(SELECT MIN(t.occurred_at) FROM work_item_transition t WHERE t.work_item_id = work_item.source_id "
            "AND t.source = work_item.source AND t.to_status IN (" + marks + ") AND t.occurred_at IS NOT NULL), "
            "work_item.resolved_at) END WHERE source = 'jira'",
            names + names,
        )
    return conn.execute(
        "SELECT COUNT(*) FROM work_item WHERE source = 'jira' AND delivered_at IS NOT NULL"
    ).fetchone()[0]
