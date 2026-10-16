from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from delivery_analysis.metrics.people import People, Scope, actor_key
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window, hours_between, weekly

UNASSIGNED_NOTE = "{n} completed issue(s) have no assignee and are not attributed to anyone."
NO_START_NOTE = "{n} completed issue(s) never entered In Progress, so they have no cycle time."
NO_POINTS_NOTE = "{n} completed issue(s) have no story points and are not counted."

_DONE_SQL = (
    "SELECT w.source_id, w.assignee_account, w.started_at, w.resolved_at, w.story_points "
    "FROM work_item w "
    "JOIN property c ON c.record_kind = 'work_item' AND c.record_id = w.source_id "
    "AND c.name = 'counts_for_impact' AND c.value = '1' "
    "WHERE w.source = 'jira' AND w.status_category = 'done' "
    "AND w.resolved_at >= ? AND w.resolved_at < ? ORDER BY w.resolved_at"
)


def _done(conn: sqlite3.Connection, window: Window) -> List[sqlite3.Row]:
    return conn.execute(_DONE_SQL, (window.start, window.end)).fetchall()


def _key(account: Optional[str]) -> Optional[str]:
    """Jira and Bitbucket share one account id, so either identity can resolve the person."""
    return actor_key(("jira", account), ("bitbucket", account))


def issues_done(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    unassigned = 0
    for row in _done(conn, window):
        key = _key(row["assignee_account"])
        if key is None:
            unassigned += 1
            continue
        obs.add(key)
    if unassigned:
        obs.notes.append(UNASSIGNED_NOTE.format(n=unassigned))
    return obs


def cycle_time(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    never_started = unassigned = 0
    for row in _done(conn, window):
        hours = hours_between(row["started_at"], row["resolved_at"])
        if hours is None or hours < 0:
            never_started += 1
            continue
        key = _key(row["assignee_account"])
        if key is None:
            unassigned += 1
            continue
        obs.add(key, hours)
    if never_started:
        obs.notes.append(NO_START_NOTE.format(n=never_started))
    if unassigned:
        obs.notes.append(UNASSIGNED_NOTE.format(n=unassigned))
    return obs


def story_points_done(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    unpointed = unassigned = 0
    for row in _done(conn, window):
        if row["story_points"] is None:
            unpointed += 1
            continue
        key = _key(row["assignee_account"])
        if key is None:
            unassigned += 1
            continue
        obs.add(key, row["story_points"])
    if unpointed:
        obs.notes.append(NO_POINTS_NOTE.format(n=unpointed))
    if unassigned:
        obs.notes.append(UNASSIGNED_NOTE.format(n=unassigned))
    return obs


def issues_done_weekly(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Completed issues per local week; under a team only issues of its members count."""
    people = People(conn) if scope.members is not None else None
    stamps: List[str] = []
    for row in _done(conn, window):
        if people is not None:
            key = _key(row["assignee_account"])
            person = people.resolve(key) if key else None
            if person not in scope.members:
                continue
        stamps.append(row["resolved_at"])
    return weekly(window, stamps), []
