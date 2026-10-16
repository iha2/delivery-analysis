from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from delivery_analysis.metrics.credit import credit_for
from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.window import Window, weekly


def _marks(values: List[str]) -> str:
    return ", ".join("?" for _ in values) if values else "NULL"


def person_detail(conn: sqlite3.Connection, person_id: str, window: Window, scope: Scope = Scope()) -> Dict[str, Any]:
    person = conn.execute(
        "SELECT person_id, display_name, excluded FROM person WHERE person_id = ?", (person_id,)
    ).fetchone()
    if person is None:
        raise LookupError(f"No person with id {person_id!r}.")
    identities = conn.execute(
        "SELECT source, account_id FROM identity WHERE person_id = ? ORDER BY source, account_id", (person_id,)
    ).fetchall()
    accounts = [row["account_id"] for row in identities if row["source"] == "bitbucket"]
    emails = [row["account_id"] for row in identities if row["source"] == "email"]
    where, params = scope.repo_filter("c.repository_id")
    repo_join = "LEFT JOIN repository r ON r.source = c.source AND r.source_id = c.repository_id"

    pull_requests = conn.execute(
        f"SELECT c.number, c.title, c.state, c.created_at, c.merged_at, r.name AS repository "
        f"FROM change_request c {repo_join} WHERE c.source = 'bitbucket' "
        f"AND c.author_account IN ({_marks(accounts)}) AND c.created_at < ? "
        f"AND (c.state = 'OPEN' OR COALESCE(c.merged_at, c.closed_at, c.created_at) >= ?) AND {where} "
        "ORDER BY c.created_at DESC LIMIT 200",
        accounts + [window.end, window.start] + params,
    ).fetchall()
    reviews_given = conn.execute(
        f"SELECT c.number, c.title, r.name AS repository, e.type, e.occurred_at FROM change_event e "
        f"JOIN change_request c ON c.source = e.source AND c.source_id = e.change_request_id {repo_join} "
        f"WHERE e.source = 'bitbucket' AND e.actor_account IN ({_marks(accounts)}) "
        "AND e.type IN ('comment', 'approved') "
        "AND (c.author_account IS NULL OR c.author_account != e.actor_account) "
        f"AND e.occurred_at >= ? AND e.occurred_at < ? AND {where} ORDER BY e.occurred_at DESC LIMIT 200",
        accounts + [window.start, window.end] + params,
    ).fetchall()
    reviewer_names = [f"reviewer:{account}" for account in accounts]
    reviews_pending = conn.execute(
        f"SELECT c.number, c.title, r.name AS repository, c.created_at FROM property p "
        f"JOIN change_request c ON c.source = 'bitbucket' AND c.source_id = p.record_id {repo_join} "
        f"WHERE p.record_kind = 'change_request' AND p.name IN ({_marks(reviewer_names)}) "
        f"AND p.value = 'pending' AND c.state = 'OPEN' AND {where} ORDER BY c.created_at",
        reviewer_names + params,
    ).fetchall()
    commit_where, commit_params = scope.repo_filter("v.repository_id")
    stamps = conn.execute(
        f"SELECT v.committed_at FROM vcs_commit v WHERE v.source = 'bitbucket' "
        f"AND (v.author_account IN ({_marks(accounts)}) OR lower(v.author_email) IN ({_marks(emails)})) "
        "AND v.committed_at >= ? AND v.committed_at < ? "
        "AND NOT EXISTS (SELECT 1 FROM property p WHERE p.record_kind = 'vcs_commit' "
        " AND p.record_id = v.source_id AND p.name = 'is_merge') "
        f"AND {commit_where}",
        accounts + emails + [window.start, window.end] + commit_params,
    ).fetchall()
    issues_done: Optional[List[Dict[str, Any]]] = None
    if conn.execute("SELECT 1 FROM work_item WHERE source = 'jira' LIMIT 1").fetchone() is not None:
        credit = credit_for(conn, window)
        people = People(conn)
        issues_done = []
        for row in reversed(credit.issues):  # credit.issues is oldest first
            share = sum(
                part for key, part in (credit.shares.get(row["source_id"]) or {}).items()
                if people.resolve(key) == person_id
            )
            if share:
                issues_done.append({
                    "key": row["key"], "type": row["type"], "points": row["story_points"],
                    "resolved_at": row["resolved_at"], "share": round(share, 2),
                    "basis": "pull request" if row["source_id"] in credit.by_pr else "assignee",
                })
        issues_done = issues_done[:200]
    result = {
        "person": {
            "person_id": person["person_id"],
            "name": person["display_name"],
            "excluded": bool(person["excluded"]),
            "accounts": accounts,
            "emails": emails,
        },
        "window": window.to_json(),
        "pull_requests": [dict(row) for row in pull_requests],
        "reviews_given": [dict(row) for row in reviews_given],
        "reviews_pending": [dict(row) for row in reviews_pending],
        "commits_weekly": weekly(window, (row["committed_at"] for row in stamps)),
    }
    if issues_done is not None:
        result["issues_done"] = issues_done
    return result
