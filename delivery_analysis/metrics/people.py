from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from delivery_analysis.connectors.bitbucket.normalize import parse_author_raw
from delivery_analysis.teams.reconcile import new_id


@dataclass(frozen=True)
class Scope:
    """What a metric covers: a team's repositories and members, or everything when team_id is None."""

    team_id: Optional[str] = None
    repos: Optional[Tuple[str, ...]] = None
    members: Optional[Dict[str, str]] = None

    def repo_filter(self, column: str) -> Tuple[str, List[str]]:
        if self.repos is None:
            return "1=1", []
        if not self.repos:
            return "0=1", []
        return f"{column} IN ({', '.join('?' for _ in self.repos)})", list(self.repos)


def team_scope(conn: sqlite3.Connection, team_id: Optional[str], include_inactive: bool = False) -> Scope:
    if not team_id:
        return Scope()
    if conn.execute("SELECT 1 FROM team WHERE team_id = ?", (team_id,)).fetchone() is None:
        raise LookupError(f"No team with id {team_id!r}.")
    repos = tuple(
        row["repository_id"]
        for row in conn.execute(
            "SELECT repository_id FROM team_repo WHERE team_id = ? ORDER BY repository_id", (team_id,)
        )
    )
    wanted = ("active", "inactive") if include_inactive else ("active",)
    members = {
        row["person_id"]: row["status"]
        for row in conn.execute("SELECT person_id, status FROM team_member WHERE team_id = ?", (team_id,))
        if row["status"] in wanted
    }
    return Scope(team_id, repos, members)


def actor_key(*candidates: Tuple[str, Optional[str]]) -> Optional[str]:
    """Join (source, account) candidates, best first: 'bitbucket:acc-1|email:a@x.example'."""
    parts = [f"{source}:{value}" for source, value in candidates if value]
    return "|".join(parts) if parts else None


class People:
    """Account and email to person lookups, read once per request."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._person: Dict[str, str] = {}
        for row in conn.execute(
            "SELECT source, account_id, person_id FROM identity WHERE person_id IS NOT NULL"
        ):
            self._person[f"{row['source']}:{row['account_id']}"] = row["person_id"]
        self._names: Dict[str, str] = {}
        self._excluded = set()
        for row in conn.execute("SELECT person_id, display_name, excluded FROM person"):
            self._names[row["person_id"]] = row["display_name"]
            if row["excluded"]:
                self._excluded.add(row["person_id"])

    def resolve(self, key: str) -> Optional[str]:
        for part in key.split("|"):
            person = self._person.get(part)
            if person is not None:
                return person
        return None

    def name(self, person_id: str) -> str:
        return self._names.get(person_id, person_id)

    def is_excluded(self, person_id: str) -> bool:
        return person_id in self._excluded

    def all(self) -> List[Dict[str, str]]:
        return sorted(
            ({"person_id": pid, "name": name} for pid, name in self._names.items() if pid not in self._excluded),
            key=lambda row: row["name"].lower(),
        )


_UNMAPPED_SQL = """
SELECT source, account, COUNT(*) AS activity FROM (
    SELECT source, author_account AS account FROM change_request
    UNION ALL SELECT source, actor_account FROM change_event
    UNION ALL SELECT source, author_account FROM vcs_commit
    UNION ALL SELECT 'bitbucket', substr(name, 10) FROM property
        WHERE record_kind = 'change_request' AND name LIKE 'reviewer:%'
) a
WHERE account IS NOT NULL AND account != ''
  AND NOT EXISTS (
      SELECT 1 FROM identity i
      WHERE i.source = a.source AND i.account_id = a.account AND i.person_id IS NOT NULL
  )
GROUP BY source, account
ORDER BY activity DESC, source, account
LIMIT ?
"""


def _find_display_name(data: Any, account: str) -> Optional[str]:
    if isinstance(data, dict):
        if data.get("account_id") == account and data.get("display_name"):
            return str(data["display_name"])
        values = data.values()
    elif isinstance(data, list):
        values = data
    else:
        return None
    for value in values:
        found = _find_display_name(value, account)
        if found:
            return found
    return None


def _commit_author_name(data: Any, account: str) -> Optional[str]:
    author = data.get("author") if isinstance(data, dict) else None
    if not isinstance(author, dict) or (author.get("user") or {}).get("account_id") != account:
        return None
    name, _ = parse_author_raw(author.get("raw"))
    return name or None


def _name_hint(conn: sqlite3.Connection, source: str, account: str) -> Optional[str]:
    """A display name from stored activity (best), else the name in a commit's author line."""
    pattern = f'%"{account}"%'
    for kind, finder in (("pr_activity", _find_display_name), ("commit", _commit_author_name)):
        for row in conn.execute(
            "SELECT json FROM raw_payload WHERE source = ? AND kind = ? AND json LIKE ? LIMIT 5",
            (source, kind, pattern),
        ).fetchall():
            try:
                found = finder(json.loads(row["json"]), account)
            except ValueError:
                continue
            if found:
                return found
    return None


def unmapped_accounts(conn: sqlite3.Connection, limit: int = 200) -> List[Dict[str, Any]]:
    """Accounts with activity and no person, most active first, with a display-name hint."""
    return [
        {
            "source": row["source"],
            "account": row["account"],
            "activity": row["activity"],
            "name_hint": _name_hint(conn, row["source"], row["account"]),
        }
        for row in conn.execute(_UNMAPPED_SQL, (limit,)).fetchall()
    ]


def set_member_status(conn: sqlite3.Connection, team_id: str, person_id: str, status: str, now: str) -> None:
    """Include or exclude a person on a team as a manual edit that reconcile keeps."""
    if status not in ("active", "excluded"):
        raise ValueError("Status must be active or excluded.")
    if conn.execute("SELECT 1 FROM team WHERE team_id = ?", (team_id,)).fetchone() is None:
        raise LookupError(f"No team with id {team_id!r}.")
    if conn.execute("SELECT 1 FROM person WHERE person_id = ?", (person_id,)).fetchone() is None:
        raise LookupError(f"No person with id {person_id!r}.")
    conn.execute(
        "INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit, pinned, manual) "
        "VALUES (?, ?, ?, ?, NULL, 0, 1) "
        "ON CONFLICT(team_id, person_id) DO UPDATE SET status = excluded.status, manual = 1",
        (team_id, person_id, status, now[:10]),
    )


def map_identity(
    conn: sqlite3.Connection,
    source: str,
    account: str,
    *,
    person_id: Optional[str] = None,
    new_name: Optional[str] = None,
    team_id: Optional[str] = None,
    now: str,
) -> str:
    """Map an account to an existing or new person (a manual mapping), optionally joining a team."""
    account = (account or "").strip()
    if not account:
        raise ValueError("An account is required.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        if person_id:
            if conn.execute("SELECT 1 FROM person WHERE person_id = ?", (person_id,)).fetchone() is None:
                raise LookupError(f"No person with id {person_id!r}.")
        elif new_name and new_name.strip():
            person_id = new_id()
            conn.execute(
                "INSERT INTO person (person_id, display_name, excluded, manual) VALUES (?, ?, 0, 1)",
                (person_id, new_name.strip()),
            )
        else:
            raise ValueError("Choose a person or give a name for a new one.")
        conn.execute(
            "INSERT INTO identity (source, account_id, person_id, manual) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(source, account_id) DO UPDATE SET person_id = excluded.person_id, manual = 1",
            (source, account, person_id),
        )
        if team_id:
            set_member_status(conn, team_id, person_id, "active", now)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return person_id
