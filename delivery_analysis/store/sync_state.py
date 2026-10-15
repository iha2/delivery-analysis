from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional


def get_cursor(conn: sqlite3.Connection, connector: str, scope: str) -> Optional[str]:
    row = conn.execute(
        "SELECT cursor FROM sync_state WHERE connector = ? AND scope = ?", (connector, scope)
    ).fetchone()
    return row["cursor"] if row else None


def set_cursor(conn: sqlite3.Connection, connector: str, scope: str, cursor: str) -> None:
    """Move the cursor. Does not manage the transaction; call it inside the batch's transaction."""
    conn.execute(
        "INSERT INTO sync_state (connector, scope, cursor) VALUES (?, ?, ?) "
        "ON CONFLICT(connector, scope) DO UPDATE SET cursor = excluded.cursor",
        (connector, scope, cursor),
    )


def save_state(
    conn: sqlite3.Connection,
    connector: str,
    scope: str,
    *,
    status: str,
    error: Optional[str],
    records: int,
    now: str,
) -> None:
    """Record run health. Leaves the stored cursor untouched."""
    conn.execute(
        "INSERT INTO sync_state (connector, scope, last_run, status, error, records) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(connector, scope) DO UPDATE SET "
        "last_run = excluded.last_run, status = excluded.status, "
        "error = excluded.error, records = excluded.records",
        (connector, scope, now, status, error, records),
    )


def clear_state(conn: sqlite3.Connection, connector: str, scope: str) -> None:
    """Delete one health row. Does not manage the transaction."""
    conn.execute("DELETE FROM sync_state WHERE connector = ? AND scope = ?", (connector, scope))


def list_sync_states(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT connector, scope, cursor, last_run, status, error, records "
        "FROM sync_state ORDER BY connector, scope"
    ).fetchall()
    states = [dict(row) for row in rows]
    for state in states:
        state["stale"] = state["status"] == "failed"
    return states
