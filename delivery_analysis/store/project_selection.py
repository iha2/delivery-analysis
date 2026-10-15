from __future__ import annotations

import sqlite3
from typing import Dict, List, Mapping, Optional

CATEGORIES = ("todo", "in_progress", "in_review", "done", "dropped")


def add_project(
    conn: sqlite3.Connection,
    source: str,
    project_key: str,
    project_id: str,
    name: Optional[str],
    story_points_field: Optional[str],
    now: str,
    excluded_types: str = "Epic,Initiative",
) -> None:
    """Select a project. Re-adding keeps the stored points field unless a new one is given."""
    conn.execute(
        "INSERT INTO project_selection "
        "(source, project_key, project_id, name, story_points_field, excluded_types, added_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(source, project_key) DO UPDATE SET project_id = excluded.project_id, "
        "name = excluded.name, "
        "story_points_field = COALESCE(excluded.story_points_field, project_selection.story_points_field)",
        (source, project_key, project_id, name, story_points_field, excluded_types, now),
    )


def get_project(conn: sqlite3.Connection, source: str, project_key: str) -> Optional[Dict[str, str]]:
    row = conn.execute(
        "SELECT source, project_key, project_id, name, story_points_field, excluded_types, added_at "
        "FROM project_selection WHERE source = ? AND project_key = ?",
        (source, project_key),
    ).fetchone()
    return dict(row) if row else None


def list_projects(conn: sqlite3.Connection, source: Optional[str] = None) -> List[Dict[str, str]]:
    sql = (
        "SELECT source, project_key, project_id, name, story_points_field, excluded_types, added_at "
        "FROM project_selection"
    )
    params = ()
    if source is not None:
        sql += " WHERE source = ?"
        params = (source,)
    sql += " ORDER BY source, project_key"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def remove_project(conn: sqlite3.Connection, source: str, project_key: str) -> int:
    """Stop syncing a project. Stored issues and the status map are kept."""
    cursor = conn.execute(
        "DELETE FROM project_selection WHERE source = ? AND project_key = ?", (source, project_key)
    )
    return cursor.rowcount


def set_status(
    conn: sqlite3.Connection, source: str, project_key: str, status_name: str, category: str
) -> None:
    name = status_name.strip()
    if not name:
        raise ValueError("Give the status name to map.")
    if category not in CATEGORIES:
        raise ValueError("A status maps to one of: " + ", ".join(CATEGORIES) + ".")
    conn.execute(
        "INSERT INTO status_mapping (source, project_key, status_name, category) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(source, project_key, status_name) DO UPDATE SET category = excluded.category",
        (source, project_key, name, category),
    )


def seed_statuses(
    conn: sqlite3.Connection, source: str, project_key: str, mapping: Mapping[str, str]
) -> None:
    """Add default mappings without touching rows that already exist (manual choices win)."""
    for name, category in mapping.items():
        if category not in CATEGORIES:
            raise ValueError("A status maps to one of: " + ", ".join(CATEGORIES) + ".")
        conn.execute(
            "INSERT OR IGNORE INTO status_mapping (source, project_key, status_name, category) "
            "VALUES (?, ?, ?, ?)",
            (source, project_key, name, category),
        )


def status_map(conn: sqlite3.Connection, source: str, project_key: str) -> Dict[str, str]:
    rows = conn.execute(
        "SELECT status_name, category FROM status_mapping WHERE source = ? AND project_key = ?",
        (source, project_key),
    ).fetchall()
    return {row["status_name"]: row["category"] for row in rows}


def issue_count(conn: sqlite3.Connection, source: str, project_key: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM work_item WHERE source = ? AND project = ?", (source, project_key)
    ).fetchone()
    return int(row["n"])


def unmapped_seen(conn: sqlite3.Connection, source: str, project_key: str) -> List[str]:
    """Current statuses of synced issues that have no mapping."""
    rows = conn.execute(
        "SELECT DISTINCT status FROM work_item WHERE source = ? AND project = ? AND status IS NOT NULL "
        "AND status NOT IN (SELECT status_name FROM status_mapping WHERE source = ? AND project_key = ?) "
        "ORDER BY status",
        (source, project_key, source, project_key),
    ).fetchall()
    return [row["status"] for row in rows]
