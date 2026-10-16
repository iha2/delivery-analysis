from __future__ import annotations

import sqlite3
import statistics
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.tokens import load_cohort, window_days
from delivery_analysis.metrics.window import Window, hours_between, week_start
from delivery_analysis.tokens.config import DEFAULT_CONFIG, AttributionConfig


def _pr_evidence(conn: sqlite3.Connection, ticket_id: str) -> Dict[str, Any]:
    prs = conn.execute(
        "SELECT DISTINCT c.source_id, c.author_account, c.created_at, c.merged_at, c.files_changed, c.commit_count "
        "FROM link l JOIN change_request c ON c.source_id = l.from_id "
        "WHERE l.kind = 'implements' AND l.from_kind = 'change_request' AND l.to_kind = 'work_item' AND l.to_id = ?",
        (ticket_id,),
    ).fetchall()
    comments = 0
    hours: List[float] = []
    for pr in prs:
        comments += conn.execute(
            "SELECT COUNT(*) AS n FROM change_event WHERE change_request_id = ? AND type = 'comment' "
            "AND actor_account IS NOT NULL AND (? IS NULL OR actor_account != ?)",
            (pr["source_id"], pr["author_account"], pr["author_account"]),
        ).fetchone()["n"]
        span = hours_between(pr["created_at"], pr["merged_at"])
        if span is not None:
            hours.append(span)
    return {
        "pull_requests": len(prs),
        "files_changed": sum(pr["files_changed"] or 0 for pr in prs),
        "commits": sum(pr["commit_count"] or 0 for pr in prs),
        "review_comments": comments,
        "hours_to_merge": round(statistics.median(hours), 1) if hours else None,
    }


def _person_weekly(conn: sqlite3.Connection, person_id: str, window: Window) -> List[Dict[str, Any]]:
    first, end = window_days(window)
    sums: Dict[date, float] = {}
    for row in conn.execute(
        "SELECT day, SUM(cost_usd) AS cost FROM token_usage WHERE person_id = ? AND day >= ? AND day < ? GROUP BY day",
        (person_id, first, end),
    ):
        week = week_start(date.fromisoformat(row["day"]))
        sums[week] = sums.get(week, 0.0) + row["cost"]
    out = []
    week = week_start(window.first_day)
    last = window.first_day + timedelta(days=window.days - 1)
    while week <= last:
        out.append({"week": week.isoformat(), "cost_usd": round(sums.get(week, 0.0), 2)})
        week += timedelta(days=7)
    return out


def ticket_costs(
    conn: sqlite3.Connection,
    scope: Scope,
    window: Window,
    person_id: Optional[str] = None,
    config: AttributionConfig = DEFAULT_CONFIG,
) -> Dict[str, Any]:
    """Completed tickets in the window with attributed cost, credit and their pull-request evidence."""
    cohort = load_cohort(conn, window)
    people = People(conn)
    tickets: List[Dict[str, Any]] = []
    for key, info in sorted(cohort.tickets.items(), key=lambda item: item[1]["issue_key"]):
        names = cohort.people(key)
        if scope.members is not None and not any(p in scope.members for p in names):
            continue
        if person_id is not None and person_id not in names:
            continue
        cost = sum(cohort.cost.get((key, p), 0.0) for p in names)
        levels: Dict[str, float] = {}
        for p in names:
            for level, value in cohort.levels.get((key, p), {}).items():
                levels[level] = levels.get(level, 0.0) + value
        row: Dict[str, Any] = {
            "key": info["issue_key"], "type": info["type"], "points": info["points"],
            "resolved_at": info["resolved_at"], "cost_usd": round(cost, 2),
            "points_per_usd": round(info["points"] / cost, 4) if cost >= config.ticket_ratio_floor_usd else None,
            "confidence": max(sorted(levels), key=lambda name: levels[name]) if levels else None,
            "people": [
                {"person_id": p, "name": people.name(p), "share": cohort.credit.get(key, {}).get(p, 0.0),
                 "cost_usd": round(cohort.cost.get((key, p), 0.0), 2)}
                for p in names
            ],
        }
        row.update(_pr_evidence(conn, key[1]))
        tickets.append(row)
    out: Dict[str, Any] = {"window": window.to_json(), "tickets": tickets, "notes": list(cohort.notes)}
    if person_id is not None:
        out["cost_weekly"] = _person_weekly(conn, person_id, window)
    return out
