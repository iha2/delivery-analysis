from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Sequence, Set, Tuple

from delivery_analysis.identity.merge import MergedPerson, merge_identities
from delivery_analysis.store.sync_state import list_sync_states
from delivery_analysis.teams.discover import discover_people, window_start

Repo = Tuple[str, str]  # (source, repository_id)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class ReconcileResult:
    team: str
    added: int = 0
    reactivated: int = 0
    inactivated: int = 0
    excluded: int = 0
    duplicates: int = 0
    skipped_inactive_step: bool = False
    messages: List[str] = field(default_factory=list)

    def summary(self) -> str:
        text = (
            f"Team {self.team}: {self.added} added, {self.reactivated} reactivated, "
            f"{self.inactivated} inactive, {self.excluded} excluded, "
            f"{self.duplicates} possible duplicate(s)"
        )
        return text + "".join("; " + message for message in self.messages)


def create_team(
    conn: sqlite3.Connection,
    name: str,
    repos: Sequence[Repo],
    window_days: int = 90,
    *,
    now: str,
    make_id: Callable[[], str] = new_id,
) -> str:
    if conn.execute("SELECT 1 FROM team WHERE name = ?", (name,)).fetchone():
        raise ValueError(f"A team named {name!r} already exists.")
    team_id = make_id()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO team (team_id, name, window_days, created_at) VALUES (?, ?, ?, ?)",
            (team_id, name, window_days, now),
        )
        for source, repository_id in repos:
            conn.execute(
                "INSERT OR IGNORE INTO team_repo (team_id, repository_source, repository_id) "
                "VALUES (?, ?, ?)",
                (team_id, source, repository_id),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return team_id


def _upsert_identity(conn: sqlite3.Connection, source: str, account_id: str, person_id: str) -> None:
    row = conn.execute(
        "SELECT person_id, manual FROM identity WHERE source = ? AND account_id = ?",
        (source, account_id),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO identity (source, account_id, person_id, manual) VALUES (?, ?, ?, 0)",
            (source, account_id, person_id),
        )
    elif not row["manual"] and row["person_id"] != person_id:
        conn.execute(
            "UPDATE identity SET person_id = ? WHERE source = ? AND account_id = ?",
            (person_id, source, account_id),
        )


def _resolve_person(
    conn: sqlite3.Connection, person: MergedPerson, make_id: Callable[[], str]
) -> str:
    marks = ", ".join("?" for _ in person.emails)
    rows = conn.execute(
        "SELECT person_id, manual FROM identity "
        f"WHERE source = 'email' AND person_id IS NOT NULL AND account_id IN ({marks})",
        list(person.emails),
    ).fetchall()
    manual_ids = sorted({row["person_id"] for row in rows if row["manual"]})
    if manual_ids:
        person_id = manual_ids[0]
    else:
        ids = sorted({row["person_id"] for row in rows})
        if ids:
            person_id = ids[0]
        else:
            person_id = make_id()
            conn.execute(
                "INSERT INTO person (person_id, display_name, excluded, manual) VALUES (?, ?, ?, 0)",
                (person_id, person.display_name, 1 if person.is_bot else 0),
            )
    conn.execute(
        "UPDATE person SET display_name = ? WHERE person_id = ? AND manual = 0",
        (person.display_name, person_id),
    )
    return person_id


def _record_member(
    conn: sqlite3.Connection, team_id: str, person_id: str, last_commit: str, now: str,
    result: ReconcileResult,
) -> None:
    excluded = conn.execute(
        "SELECT excluded FROM person WHERE person_id = ?", (person_id,)
    ).fetchone()["excluded"]
    member = conn.execute(
        "SELECT status, manual FROM team_member WHERE team_id = ? AND person_id = ?",
        (team_id, person_id),
    ).fetchone()
    if member is None:
        status = "excluded" if excluded else "active"
        conn.execute(
            "INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit, pinned, manual) "
            "VALUES (?, ?, ?, ?, ?, 0, 0)",
            (team_id, person_id, status, now[:10], last_commit),
        )
        if excluded:
            result.excluded += 1
        else:
            result.added += 1
        return
    status = member["status"]
    if status == "inactive" and not member["manual"] and not excluded:
        status = "active"
        result.reactivated += 1
    conn.execute(
        "UPDATE team_member SET status = ?, "
        "last_commit = CASE WHEN last_commit IS NULL OR last_commit < ? THEN ? ELSE last_commit END "
        "WHERE team_id = ? AND person_id = ?",
        (status, last_commit, last_commit, team_id, person_id),
    )


def reconcile_team(
    conn: sqlite3.Connection,
    team_id: str,
    now: str,
    stale_repos: Iterable[Repo] = (),
    make_id: Callable[[], str] = new_id,
) -> ReconcileResult:
    team = conn.execute(
        "SELECT team_id, name, window_days FROM team WHERE team_id = ?", (team_id,)
    ).fetchone()
    if team is None:
        raise ValueError(f"Unknown team {team_id!r}.")
    result = ReconcileResult(team=team["name"])
    repos: List[Repo] = [
        (row["repository_source"], row["repository_id"])
        for row in conn.execute(
            "SELECT repository_source, repository_id FROM team_repo WHERE team_id = ? "
            "ORDER BY repository_source, repository_id",
            (team_id,),
        )
    ]
    if not repos:
        result.messages.append("no repositories selected, nothing to discover")
        return result

    people, duplicates = merge_identities(
        discover_people(conn, repos, window_start(now, team["window_days"]))
    )
    if not people:
        result.messages.append("no commits in the window, roster unchanged")
        return result

    stale = set(stale_repos)
    skip_inactive = any(repo in stale for repo in repos)
    result.skipped_inactive_step = skip_inactive
    if skip_inactive:
        result.messages.append("a repository is stale, nobody was marked inactive")

    conn.execute("BEGIN IMMEDIATE")
    try:
        seen: Set[str] = set()
        person_of_key = {}
        for person in people:
            person_id = _resolve_person(conn, person, make_id)
            person_of_key[person.key] = person_id
            seen.add(person_id)
            for email in person.emails:
                _upsert_identity(conn, "email", email, person_id)
            for source, account_id in person.account_ids:
                _upsert_identity(conn, source, account_id, person_id)
            _record_member(conn, team_id, person_id, person.last_commit, now, result)

        if not skip_inactive:
            actives = conn.execute(
                "SELECT person_id FROM team_member "
                "WHERE team_id = ? AND status = 'active' AND manual = 0 AND pinned = 0",
                (team_id,),
            ).fetchall()
            for row in actives:
                if row["person_id"] not in seen:
                    conn.execute(
                        "UPDATE team_member SET status = 'inactive' WHERE team_id = ? AND person_id = ?",
                        (team_id, row["person_id"]),
                    )
                    result.inactivated += 1

        for duplicate in duplicates:
            a = person_of_key.get(duplicate.email_a)
            b = person_of_key.get(duplicate.email_b)
            if a and b and a != b:
                first, second = sorted((a, b))
                cursor = conn.execute(
                    "INSERT INTO possible_duplicate (person_a, person_b, reason) VALUES (?, ?, ?) "
                    "ON CONFLICT(person_a, person_b) DO NOTHING",
                    (first, second, duplicate.reason),
                )
                result.duplicates += cursor.rowcount
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return result


def reconcile_all(
    conn: sqlite3.Connection, now: str, stale_repos: Iterable[Repo] = ()
) -> List[str]:
    stale = set(stale_repos)
    lines: List[str] = []
    for row in conn.execute("SELECT team_id FROM team ORDER BY name").fetchall():
        lines.append(reconcile_team(conn, row["team_id"], now, stale).summary())
    return lines


def stale_repo_keys(conn: sqlite3.Connection) -> Set[Repo]:
    """(connector, scope) of every failed source.

    Convention for connectors: a repository scope string equals the repository's `source_id`,
    and a connector's name equals the `source` of its records.
    """
    return {(state["connector"], state["scope"]) for state in list_sync_states(conn) if state["stale"]}
