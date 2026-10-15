from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Dict, List, Sequence, Set, Tuple

from delivery_analysis.identity.merge import EmailActivity
from delivery_analysis.sync.runner import shift_cursor

Repo = Tuple[str, str]  # (source, repository_id)


def window_start(now: str, days: int) -> str:
    start = shift_cursor(now, days)
    if start is None:
        raise ValueError(f"{now!r} is not a UTC ISO timestamp")
    return start


def unknown_repos(conn: sqlite3.Connection, repos: Sequence[Repo]) -> List[Repo]:
    """Selected repositories with no stored commits and no repository row (often a typo)."""
    missing: List[Repo] = []
    for source, repository_id in repos:
        known = conn.execute(
            "SELECT 1 FROM vcs_commit WHERE source = ? AND repository_id = ? LIMIT 1",
            (source, repository_id),
        ).fetchone() or conn.execute(
            "SELECT 1 FROM repository WHERE source = ? AND source_id = ? LIMIT 1",
            (source, repository_id),
        ).fetchone()
        if not known:
            missing.append((source, repository_id))
    return missing


def discover_people(
    conn: sqlite3.Connection, repos: Sequence[Repo], since: str
) -> List[EmailActivity]:
    """Everyone who committed to the repositories since `since`, one entry per author email."""
    if not repos:
        return []
    clause = " OR ".join("(source = ? AND repository_id = ?)" for _ in repos)
    params: List[str] = [value for repo in repos for value in repo]
    rows = conn.execute(
        "SELECT source, author_email, author_name, author_account, committed_at "
        f"FROM vcs_commit WHERE ({clause}) AND committed_at >= ? "
        "AND author_email IS NOT NULL AND TRIM(author_email) != ''",
        params + [since],
    ).fetchall()

    found: Dict[str, Dict[str, object]] = {}
    for row in rows:
        email = row["author_email"].strip().lower()
        entry = found.setdefault(
            email, {"names": Counter(), "accounts": set(), "commits": 0, "last": ""}
        )
        name = (row["author_name"] or "").strip()
        if name:
            entry["names"][name] += 1  # type: ignore[index]
        if row["author_account"]:
            entry["accounts"].add((row["source"], row["author_account"]))  # type: ignore[union-attr]
        entry["commits"] += 1  # type: ignore[operator]
        if row["committed_at"] > entry["last"]:  # type: ignore[operator]
            entry["last"] = row["committed_at"]

    activities: List[EmailActivity] = []
    for email in sorted(found):
        entry = found[email]
        accounts: Set[Tuple[str, str]] = entry["accounts"]  # type: ignore[assignment]
        activities.append(
            EmailActivity(
                email=email,
                names=dict(entry["names"]),  # type: ignore[arg-type]
                account_ids=tuple(sorted(accounts)),
                commits=int(entry["commits"]),  # type: ignore[call-overload]
                last_commit=str(entry["last"]),
            )
        )
    return activities
