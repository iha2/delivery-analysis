"""Who a team's medians are measured against: a saved subset of its active members, or the whole active team."""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Sequence


def _active(conn: sqlite3.Connection, team_id: str) -> Dict[str, str]:
    if conn.execute("SELECT 1 FROM team WHERE team_id = ?", (team_id,)).fetchone() is None:
        raise LookupError(f"No team with id {team_id!r}.")
    return {
        row["person_id"]: row["display_name"]
        for row in conn.execute(
            "SELECT m.person_id, p.display_name FROM team_member m JOIN person p ON p.person_id = m.person_id "
            "WHERE m.team_id = ? AND m.status = 'active' AND p.excluded = 0 ORDER BY lower(p.display_name)",
            (team_id,),
        )
    }


def get_group(conn: sqlite3.Connection, team_id: str) -> Optional[List[str]]:
    """The saved people who are still active members, or None when the whole team counts."""
    active = _active(conn, team_id)
    saved = {row["person_id"] for row in conn.execute(
        "SELECT person_id FROM comparison_member WHERE team_id = ?", (team_id,))}
    group = [person for person in active if person in saved]
    return group or None


def set_group(conn: sqlite3.Connection, team_id: str, person_ids: Sequence[str]) -> None:
    active = _active(conn, team_id)
    chosen = list(dict.fromkeys(person_ids))
    if not chosen:
        raise ValueError("Pick at least one person, or reset to the whole team.")
    unknown = [person for person in chosen if person not in active]
    if unknown:
        raise ValueError("Only active members of this team can be picked: " + ", ".join(unknown) + ".")
    with conn:
        conn.execute("DELETE FROM comparison_member WHERE team_id = ?", (team_id,))
        conn.executemany("INSERT INTO comparison_member (team_id, person_id) VALUES (?, ?)",
                         [(team_id, person) for person in chosen])


def reset_group(conn: sqlite3.Connection, team_id: str) -> None:
    _active(conn, team_id)
    with conn:
        conn.execute("DELETE FROM comparison_member WHERE team_id = ?", (team_id,))


def options(conn: sqlite3.Connection, team_id: str) -> Dict[str, Any]:
    active = _active(conn, team_id)
    group = get_group(conn, team_id)
    chosen = set(group) if group is not None else set(active)
    return {
        "team_id": team_id, "custom": group is not None,
        "people": [{"person_id": person, "name": name, "selected": person in chosen} for person, name in active.items()],
    }
