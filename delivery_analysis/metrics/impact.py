from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from delivery_analysis.metrics.credit import Credit, Scoped, credit_for, credit_note, first_merges, scoped
from delivery_analysis.metrics.jira import (
    NO_DATE_NOTE, NO_POINTS_NOTE, NO_START_NOTE, OUTSIDE_NOTE, UNASSIGNED_NOTE, _unresolved,
)
from delivery_analysis.metrics.people import Scope, actor_key
from delivery_analysis.metrics.registry import Observations, percentile
from delivery_analysis.metrics.window import Window, hours_between, local_day, week_start

NO_PR_NOTE = (
    "{n} completed issue(s) have no merged linked pull request after they started, "
    "so they have no time to first PR merge."
)
UNLINKED_NOTE = "{n} merged pull request(s) have no issue key in the title or branch."

_MERGED_LINK_SQL = (
    "SELECT c.author_account, c.merged_at, EXISTS ("
    "SELECT 1 FROM link l WHERE l.from_kind = 'change_request' AND l.from_id = c.source_id "
    "AND l.to_kind = 'work_item' AND l.kind = 'implements') AS linked "
    "FROM change_request c WHERE c.source = 'bitbucket' AND c.state = 'MERGED' "
    "AND c.merged_at >= ? AND c.merged_at < ? AND {where}"
)


def _notes(credit: Credit, sc: Scoped, scope: Scope, *, with_credit: bool, with_unassigned: bool = True) -> List[str]:
    """Credit explanation, issues nobody can be credited for (only without a team: under a team they are
    simply not the team's), issues credited outside the team, and done issues with no resolved date."""
    notes: List[str] = []
    explained = credit_note(credit) if with_credit else None
    if explained:
        notes.append(explained)
    if with_unassigned and scope.members is None and sc.unassigned:
        notes.append(UNASSIGNED_NOTE.format(n=len(sc.unassigned)))
    if sc.outside:
        notes.append(OUTSIDE_NOTE.format(n=sc.outside))
    return notes


def _no_date_note(conn: sqlite3.Connection, scope: Scope) -> List[str]:
    missing = _unresolved(conn, scope)
    return [NO_DATE_NOTE.format(n=missing)] if missing else []


def _weeks(window: Window) -> List[date]:
    weeks: List[date] = []
    week = week_start(window.first_day)
    last = window.first_day + timedelta(days=window.days - 1)
    while week <= last:
        weeks.append(week)
        week += timedelta(days=7)
    return weeks


def _week_of(stamp: str, window: Window) -> date:
    return week_start(local_day(stamp, window.tz))


def story_points_weekly(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    credit = credit_for(conn, window)
    sc = scoped(conn, scope, credit)
    points: Dict[date, float] = {week: 0.0 for week in _weeks(window)}
    issues: Dict[date, int] = {week: 0 for week in points}
    unpointed: Dict[date, int] = {week: 0 for week in points}
    for row, fraction in sc.items:
        week = _week_of(row["resolved_at"], window)
        issues[week] = issues.get(week, 0) + 1
        if row["story_points"] is None:
            unpointed[week] = unpointed.get(week, 0) + 1
            continue
        points[week] = points.get(week, 0.0) + row["story_points"] * fraction
    rows = [
        {"week": week.isoformat(), "value": round(points[week], 2), "issues": issues.get(week, 0),
         "unpointed": unpointed.get(week, 0)}
        for week in sorted(points)
    ]
    missing = sum(unpointed.values())
    notes = [NO_POINTS_NOTE.format(n=missing)] if missing else []
    return rows, notes + _notes(credit, sc, scope, with_credit=True) + _no_date_note(conn, scope)


def points_by_type(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    credit = credit_for(conn, window)
    sc = scoped(conn, scope, credit)
    totals: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    unpointed = 0
    for row, fraction in sc.items:
        if row["story_points"] is None:
            unpointed += 1
            continue
        kind = row["type"] or "Unknown"
        totals[kind] = totals.get(kind, 0.0) + row["story_points"] * fraction
        counts[kind] = counts.get(kind, 0) + 1
    rows = [{"part": kind, "value": round(total, 2), "count": counts[kind]} for kind, total in totals.items()]
    rows.sort(key=lambda r: (-r["value"], r["part"]))
    notes = [NO_POINTS_NOTE.format(n=unpointed)] if unpointed else []
    return rows, notes + _notes(credit, sc, scope, with_credit=True) + _no_date_note(conn, scope)


@dataclass
class CycleSet:
    """Completed issues of a scope with their hours, each issue counted once."""

    to_done: List[Tuple[sqlite3.Row, float]] = field(default_factory=list)
    to_pr: List[Tuple[sqlite3.Row, float]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _cycle_set(conn: sqlite3.Connection, scope: Scope, window: Window) -> CycleSet:
    """Team-level cycle time by issue: under a team an issue counts when a team member is credited for it;
    with no team every completed issue counts, assigned or not."""
    credit = credit_for(conn, window)
    sc = scoped(conn, scope, credit)
    rows = [row for row, _ in sc.items] + (sc.unassigned if scope.members is None else [])
    merges = first_merges(conn)
    result = CycleSet()
    never_started = no_pr = 0
    for row in rows:
        hours = hours_between(row["started_at"], row["resolved_at"])
        if hours is None or hours < 0:
            never_started += 1
            continue
        result.to_done.append((row, hours))
        merged = merges.get(row["source_id"])
        to_pr = hours_between(row["started_at"], merged) if merged else None
        if to_pr is None or to_pr < 0:
            no_pr += 1
            continue
        result.to_pr.append((row, to_pr))
    if never_started:
        result.notes.append(NO_START_NOTE.format(n=never_started))
    if no_pr:
        result.notes.append(NO_PR_NOTE.format(n=no_pr))
    result.notes += _notes(credit, sc, scope, with_credit=False, with_unassigned=False)
    return result


def _stats(values: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None
    return round(float(statistics.median(values)), 2), round(float(percentile(values, 85)), 2)


def cycle_time_weekly(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    cycle = _cycle_set(conn, scope, window)
    done: Dict[date, List[float]] = {week: [] for week in _weeks(window)}
    merged: Dict[date, List[float]] = {week: [] for week in done}
    for row, hours in cycle.to_done:
        done.setdefault(_week_of(row["resolved_at"], window), []).append(hours)
    for row, hours in cycle.to_pr:
        merged.setdefault(_week_of(row["resolved_at"], window), []).append(hours)
    rows: List[Dict[str, Any]] = []
    for week in sorted(done):
        median, p85 = _stats(done[week])
        pr_median, pr_p85 = _stats(merged.get(week, []))
        rows.append({
            "week": week.isoformat(), "median": median, "p85": p85, "count": len(done[week]),
            "pr_median": pr_median, "pr_p85": pr_p85, "pr_count": len(merged.get(week, [])),
        })
    return rows, cycle.notes


def cycle_time_summary(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    cycle = _cycle_set(conn, scope, window)
    rows: List[Dict[str, Any]] = []
    for part, pairs in (("In Progress to COMPLETED", cycle.to_done), ("In Progress to first PR merge", cycle.to_pr)):
        median, p85 = _stats([hours for _, hours in pairs])
        rows.append({"part": part, "median": median, "p85": p85, "count": len(pairs)})
    return rows, cycle.notes


def _merged_with_links(conn: sqlite3.Connection, scope: Scope, window: Window) -> List[sqlite3.Row]:
    where, params = scope.repo_filter("c.repository_id")
    return conn.execute(_MERGED_LINK_SQL.format(where=where), [window.start, window.end] + params).fetchall()


def prs_linked_weekly(
    conn: sqlite3.Connection, scope: Scope, window: Window
) -> Tuple[List[Dict[str, Any]], List[str]]:
    linked: Dict[date, int] = {week: 0 for week in _weeks(window)}
    unlinked: Dict[date, int] = {week: 0 for week in linked}
    missing = 0
    for row in _merged_with_links(conn, scope, window):
        week = _week_of(row["merged_at"], window)
        if row["linked"]:
            linked[week] = linked.get(week, 0) + 1
        else:
            unlinked[week] = unlinked.get(week, 0) + 1
            missing += 1
    rows = [
        {"week": week.isoformat(), "linked": linked[week], "unlinked": unlinked.get(week, 0)}
        for week in sorted(linked)
    ]
    return rows, [UNLINKED_NOTE.format(n=missing)] if missing else []


def prs_with_issue_link(conn: sqlite3.Connection, scope: Scope, window: Window) -> Observations:
    obs = Observations()
    missing = 0
    for row in _merged_with_links(conn, scope, window):
        obs.add(actor_key(("bitbucket", row["author_account"])), 1.0 if row["linked"] else 0.0)
        if not row["linked"]:
            missing += 1
    if missing:
        obs.notes.append(UNLINKED_NOTE.format(n=missing))
    return obs
