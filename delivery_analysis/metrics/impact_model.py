"""Per-person impact = delivery + participation, in story points.

Each completed issue's points are shared out by evidence on its linked pull requests: the PR author earns
delivery evidence (1 per linked PR plus 1 per commit on it by the commit author), everyone else earns
participation evidence (1 per comment or approval). With no evidence the assignee delivers all of it.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Dict, List, Optional

from delivery_analysis.metrics import bitbucket as bb
from delivery_analysis.metrics import tokens as tk
from delivery_analysis.metrics.credit import actor_for, completed_issues
from delivery_analysis.metrics.people import People, Scope, actor_key
from delivery_analysis.metrics.registry import Observations
from delivery_analysis.metrics.window import Window, hours_between

Shares = Dict[str, Dict[str, Dict[str, float]]]

OUTSIDE_NOTE = "{points:g} impact point(s) went to people outside this team and are not counted."

_PRS_SQL = (
    "SELECT DISTINCT l.to_id AS issue_id, c.source_id AS pr_id, c.author_account AS author "
    "FROM link l JOIN change_request c ON c.source = 'bitbucket' AND c.source_id = l.from_id "
    "WHERE l.kind = 'implements' AND l.from_kind = 'change_request' AND l.to_kind = 'work_item'"
)
_COMMITS_SQL = (
    "SELECT change_request_id AS pr_id, author_account, author_email FROM vcs_commit "
    "WHERE source = 'bitbucket' AND change_request_id IS NOT NULL"
)
_EVENTS_SQL = (
    "SELECT change_request_id AS pr_id, actor_account FROM change_event WHERE source = 'bitbucket' "
    "AND type IN ('comment', 'approved') AND actor_account IS NOT NULL AND actor_account != ''"
)
_MERGES_SQL = (
    "SELECT l.to_id AS issue_id, c.merged_at FROM link l JOIN change_request c ON c.source = 'bitbucket' "
    "AND c.source_id = l.from_id WHERE l.kind = 'implements' AND l.from_kind = 'change_request' "
    "AND l.to_kind = 'work_item' AND c.state = 'MERGED' AND c.merged_at IS NOT NULL"
)


def _cohort(conn: sqlite3.Connection, window: Window) -> List[sqlite3.Row]:
    return [row for row in completed_issues(conn, window) if row["story_points"] is not None]


def impact_shares(conn: sqlite3.Connection, window: Window) -> Shares:
    """{issue_id: {actor_key: {"delivery": points, "participation": points}}} for the window's cohort."""
    cohort = _cohort(conn, window)
    wanted = {row["source_id"] for row in cohort}
    prs: Dict[str, Dict[str, Optional[str]]] = defaultdict(dict)  # issue -> pr -> author account
    for row in conn.execute(_PRS_SQL):
        if row["issue_id"] in wanted:
            prs[row["issue_id"]][row["pr_id"]] = row["author"] or None
    authors = {pr_id: author for by_pr in prs.values() for pr_id, author in by_pr.items()}
    commits: Dict[str, List[Optional[str]]] = defaultdict(list)
    for row in conn.execute(_COMMITS_SQL):
        if row["pr_id"] in authors:
            email = (row["author_email"] or "").strip().lower() or None
            commits[row["pr_id"]].append(
                actor_key(("jira", row["author_account"]), ("bitbucket", row["author_account"]), ("email", email))
            )
    events: Dict[str, List[Optional[str]]] = defaultdict(list)
    for row in conn.execute(_EVENTS_SQL):
        if row["pr_id"] in authors and row["actor_account"] != authors[row["pr_id"]]:
            events[row["pr_id"]].append(actor_for(row["actor_account"]))
    out: Shares = {}
    for issue in cohort:
        issue_id, points = issue["source_id"], float(issue["story_points"])
        delivery: Dict[str, float] = defaultdict(float)
        participation: Dict[str, float] = defaultdict(float)
        for pr_id, author in prs.get(issue_id, {}).items():
            if author:
                delivery[actor_for(author)] += 1
            for key in commits.get(pr_id, []):
                if key:
                    delivery[key] += 1
            for key in events.get(pr_id, []):
                if key:
                    participation[key] += 1
        total = sum(delivery.values()) + sum(participation.values())
        if total > 0:
            out[issue_id] = {
                key: {
                    "delivery": points * delivery.get(key, 0.0) / total,
                    "participation": points * participation.get(key, 0.0) / total,
                }
                for key in set(delivery) | set(participation)
            }
            continue
        key = actor_for(issue["assignee_account"])
        out[issue_id] = {key: {"delivery": points, "participation": 0.0}} if key else {}
    return out


def _counts(people: People, scope: Scope, key: str) -> bool:
    if scope.members is None:
        return True
    person = people.resolve(key)
    return person is not None and person in scope.members


def _points(conn: sqlite3.Connection, scope: Scope, window: Window, parts: tuple) -> Observations:
    people = People(conn)
    obs = Observations()
    outside = 0.0
    for shares in impact_shares(conn, window).values():
        for key, share in shares.items():
            value = sum(share[part] for part in parts)
            if value <= 0:
                continue
            if _counts(people, scope, key):
                obs.add(key, value)
            else:
                outside += value
    if outside > 1e-9:
        obs.notes.append(OUTSIDE_NOTE.format(points=round(outside, 2)))
    return obs


def impact_points(conn, scope: Scope, window: Window) -> Observations:
    return _points(conn, scope, window, ("delivery", "participation"))


def delivery_points(conn, scope: Scope, window: Window) -> Observations:
    return _points(conn, scope, window, ("delivery",))


def participation_points(conn, scope: Scope, window: Window) -> Observations:
    return _points(conn, scope, window, ("participation",))


def impact_per_dollar(conn, scope: Scope, window: Window) -> Observations:
    """Impact points over Claude cost (the cost_spent source), summed per person by the ratio aggregate."""
    obs = impact_points(conn, scope, window)
    ratio = Observations(notes=list(obs.notes))
    for key, values in obs.by_actor.items():
        for value in values:
            ratio.add_pair(key, value, 0.0, 1)
    cost = tk.cost_spent(conn, scope, window)
    for key, values in cost.by_actor.items():
        ratio.add_pair(key, 0.0, sum(values), 0)
    ratio.notes.extend(note for note in cost.notes if note not in ratio.notes)
    return ratio


def delivery_speed(conn, scope: Scope, window: Window) -> Observations:
    """Hours from an issue's start to the first linked PR merged after it, for each person who delivered."""
    people = People(conn)
    merges: Dict[str, List[str]] = defaultdict(list)
    for row in conn.execute(_MERGES_SQL):
        merges[row["issue_id"]].append(row["merged_at"])
    started = {row["source_id"]: row["started_at"] for row in _cohort(conn, window)}
    obs = Observations()
    for issue_id, shares in impact_shares(conn, window).items():
        start = started.get(issue_id)
        after = [m for m in merges.get(issue_id, []) if start and m > start]
        if not after:
            continue
        hours = hours_between(start, min(after))
        for key, share in shares.items():
            if share["delivery"] > 0 and _counts(people, scope, key):
                obs.add(key, hours)
    return obs


def durability(conn, scope: Scope, window: Window) -> Observations:
    """Delivered points on issues that were never reopened, over all delivered points."""
    people = People(conn)
    reopened = {
        row["record_id"] for row in conn.execute(
            "SELECT record_id, value FROM property WHERE record_kind = 'work_item' AND name = 'reopen_count'"
        ) if str(row["value"]).strip() not in ("", "0")
    }
    obs = Observations()
    for issue_id, shares in impact_shares(conn, window).items():
        for key, share in shares.items():
            if share["delivery"] > 0 and _counts(people, scope, key):
                kept = 0.0 if issue_id in reopened else share["delivery"]
                obs.add_pair(key, kept, share["delivery"], 1)
    return obs


def review_responsiveness(conn, scope: Scope, window: Window) -> Observations:
    """Hours from a pull request's creation to the person's first review event on it, per PR reviewed."""
    where, params = scope.repo_filter("c.repository_id")
    rows = conn.execute(
        "SELECT e.actor_account AS account, c.created_at AS created, MIN(e.occurred_at) AS first, "
        "MAX(CASE WHEN e.occurred_at >= ? AND e.occurred_at < ? THEN 1 ELSE 0 END) AS in_window "
        "FROM change_event e JOIN change_request c ON c.source = e.source AND c.source_id = e.change_request_id "
        "WHERE e.source = 'bitbucket' AND e.type IN ('comment', 'approved') AND e.actor_account IS NOT NULL "
        "AND (c.author_account IS NULL OR e.actor_account != c.author_account) "
        f"AND {where} GROUP BY e.actor_account, e.change_request_id",
        [window.start, window.end] + params,
    ).fetchall()
    obs = Observations(notes=bb._detail_note(conn, scope))
    for row in rows:
        hours = hours_between(row["created"], row["first"])
        if row["in_window"] and hours is not None and hours >= 0:
            obs.add(actor_key(("bitbucket", row["account"])), hours)
    return obs


def review_follow_through(conn, scope: Scope, window: Window) -> Observations:
    return bb.review_response_rate(conn, scope, window)
