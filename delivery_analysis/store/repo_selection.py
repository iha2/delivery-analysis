from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional, Tuple

_MATCH = (
    "repository_id = ? OR lower(slug) = lower(?) OR lower(workspace || '/' || slug) = lower(?)"
)


def add_repo(
    conn: sqlite3.Connection, source: str, repository_id: str, workspace: str, slug: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO repo_selection (source, repository_id, workspace, slug, added_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(source, repository_id) DO UPDATE SET workspace = excluded.workspace, slug = excluded.slug",
        (source, repository_id, workspace, slug, now),
    )


def list_selected(conn: sqlite3.Connection, source: Optional[str] = None) -> List[Dict[str, str]]:
    sql = "SELECT source, repository_id, workspace, slug, added_at FROM repo_selection"
    params: Tuple[str, ...] = ()
    if source is not None:
        sql += " WHERE source = ?"
        params = (source,)
    sql += " ORDER BY workspace, slug"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def remove_repo(conn: sqlite3.Connection, source: str, text: str) -> int:
    cursor = conn.execute(
        f"DELETE FROM repo_selection WHERE source = ? AND ({_MATCH})", (source, text, text, text)
    )
    return cursor.rowcount


def resolve(conn: sqlite3.Connection, source: str, text: str) -> str:
    """The stored repository id for a UUID, slug, or workspace/slug; otherwise the text unchanged."""
    row = conn.execute(
        f"SELECT repository_id FROM repo_selection WHERE source = ? AND ({_MATCH}) "
        "ORDER BY repository_id LIMIT 1",
        (source, text, text, text),
    ).fetchone()
    return row["repository_id"] if row else text


def detail_progress(conn: sqlite3.Connection, repository_id: str) -> Tuple[int, int]:
    """(pull requests whose detail is current, pull requests known) for one repository."""
    pattern = repository_id + "#%"
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM property "
        "WHERE record_kind = 'change_request' AND name = 'updated_on' AND record_id LIKE ?",
        (pattern,),
    ).fetchone()["n"]
    done = conn.execute(
        "SELECT COUNT(*) AS n FROM property u JOIN property d "
        "ON d.record_kind = 'change_request' AND d.record_id = u.record_id AND d.name = 'detail_updated_on' "
        "WHERE u.record_kind = 'change_request' AND u.name = 'updated_on' AND u.record_id LIKE ? "
        "AND d.value = u.value",
        (pattern,),
    ).fetchone()["n"]
    return done, total
