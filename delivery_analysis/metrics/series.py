"""Rolling-window history of one person's impact numbers, for the Person page charts.

Each point is the metric over the `window_days` ending on that date, computed by `run_metric` on the same
code path as the rankings (with the previous-window comparison switched off, which does not change a value).
"""
from __future__ import annotations

import sqlite3
import statistics
from dataclasses import replace
from datetime import date, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional

from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.registry import run_metric
from delivery_analysis.metrics.window import make_window

METRIC_OF = {
    "impact": "impact_points", "delivery": "delivery_points", "participation": "participation_points",
    "impact_per_dollar": "impact_per_dollar", "prs_reviewed": "prs_reviewed", "review_value": "review_value",
    "delivery_speed": "delivery_speed", "durability": "durability",
}
KEYS = tuple(METRIC_OF) + ("penalty",)


def _dates(end: date, step_days: int, history_days: int) -> List[date]:
    count = history_days // step_days
    return [end - timedelta(days=step_days * n) for n in range(count, -1, -1)]


def _median(values: List[float]) -> Optional[float]:
    return round(float(statistics.median(values)), 4) if values else None


def _penalties(conn: sqlite3.Connection, people: People, start: str, end: str) -> List[tuple]:
    out = []
    for row in conn.execute(
        "SELECT actor_key, resolved_at, penalty FROM impact_share WHERE penalty != 0 "
        "AND resolved_at >= ? AND resolved_at < ?", (start, end),
    ):
        person = people.resolve(row["actor_key"])
        if person is not None:
            out.append((person, row["resolved_at"], row["penalty"]))
    return out


def person_series(
    conn: sqlite3.Connection, person_id: str, scope: Scope, *, end: date, window_days: int = 30,
    step_days: int = 7, history_days: int = 180, tz: Optional[tzinfo] = None,
) -> Dict[str, Any]:
    tz = tz or timezone.utc
    people = People(conn)
    days = _dates(end, step_days, history_days)
    windows = [make_window(f"{window_days}d", tz, day) for day in days]
    series: Dict[str, List[Optional[float]]] = {key: [] for key in KEYS}
    medians: Dict[str, List[Optional[float]]] = {key: [] for key in KEYS}
    notes: List[str] = []
    impact_ok = False
    members = list(scope.members) if scope.members is not None else [row["person_id"] for row in people.all()]
    metrics = {key: replace(BY_NAME[name], windowed=False) for key, name in METRIC_OF.items()}
    for window in windows:
        for key, metric in metrics.items():
            result = run_metric(conn, metric, scope, window, people)
            ok = result["status"] == "ok"
            if key == "impact":
                impact_ok = ok
                notes = list(result["notes"]) if ok else []
            rows = [row for row in result["rows"] if row["person_id"] is not None] if ok else []
            mine = next((row["value"] for row in rows if row["person_id"] == person_id), None)
            if ok and mine is None and metric.aggregate == "sum":
                mine = 0.0
            series[key].append(mine)
            if ok and metric.aggregate == "sum":  # everyone in scope counts, with 0 when they have no value
                have = {row["person_id"]: row["value"] for row in rows}
                medians[key].append(_median([have.get(member) or 0.0 for member in members]))
            else:
                medians[key].append(_median([row["value"] for row in rows if row["value"] is not None]))
    first, last = windows[0].start, windows[-1].end
    shares = _penalties(conn, people, first, last) if impact_ok else []
    for window in windows:
        totals = {member: 0.0 for member in members}
        for person, resolved, penalty in shares:
            if window.start <= resolved < window.end and person in totals:
                totals[person] += penalty
        series["penalty"].append(round(totals.get(person_id, 0.0), 2) if impact_ok else None)
        medians["penalty"].append(_median(list(totals.values())) if impact_ok and totals else None)
    return {
        "dates": [day.isoformat() for day in days], "window_days": window_days,
        "series": series, "team_median": medians, "notes": notes,
    }
