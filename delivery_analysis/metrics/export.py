"""One person's impact numbers as CSV text: the matrix row (metrics) and the rolling series, no HTTP."""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date, tzinfo
from typing import Any, List, Optional

from delivery_analysis.metrics.catalog import BY_NAME
from delivery_analysis.metrics.matrix import people_matrix
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.series import person_series
from delivery_analysis.metrics.window import Window

SECTIONS = ("all", "metrics", "series")
METRIC_HEADER = [
    "person", "metric", "label", "group", "value", "unit", "sample", "rank", "ranked", "confidence",
    "status", "window_start", "window_end",
]
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def cell(value: Any) -> Any:
    """A CSV cell: None is blank, numbers stay numbers, strings are defused against spreadsheet formulas."""
    if value is None:
        return ""
    if isinstance(value, str):
        return "'" + value if value.startswith(_FORMULA_STARTS) else value
    return value


def _write(rows: List[List[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    for row in rows:
        writer.writerow([cell(v) for v in row])
    return out.getvalue()


def _metrics_rows(
    conn: sqlite3.Connection, person_id: str, scope: Scope, window: Window, history_days: int
) -> List[List[Any]]:
    matrix = people_matrix(conn, scope, window, history_days=history_days)
    found = next((r for r in matrix["rows"] if r["person_id"] == person_id), None)
    if found is not None:
        name, cells = found["name"], found["cells"]
    else:
        row = conn.execute("SELECT display_name FROM person WHERE person_id = ?", (person_id,)).fetchone()
        name, cells = (row["display_name"] if row else person_id), {}
    rows: List[List[Any]] = [METRIC_HEADER]
    for column in matrix["columns"]:
        have = cells.get(column["name"]) or {}
        status = "ok" if column["status"] == "ok" else "waiting for " + ", ".join(column["missing"])
        rows.append([
            name, column["name"], column["label"], BY_NAME[column["name"]].group, have.get("value"),
            column["unit"], have.get("sample"), have.get("rank"), have.get("ranked"), have.get("confidence"),
            status, window.start, window.end,
        ])
    return rows


def _series_rows(
    conn: sqlite3.Connection, person_id: str, scope: Scope, series_end: date, window_days: int,
    tz: Optional[tzinfo],
) -> List[List[Any]]:
    data = person_series(
        conn, person_id, scope, end=series_end, window_days=window_days, step_days=7, history_days=180, tz=tz
    )
    keys = list(data["series"])
    rows: List[List[Any]] = [["date", *keys, *[f"team_median_{k}" for k in keys]]]
    for i, day in enumerate(data["dates"]):
        rows.append([day, *[data["series"][k][i] for k in keys], *[data["team_median"][k][i] for k in keys]])
    return rows


def person_csv(
    conn: sqlite3.Connection, person_id: str, scope: Scope, window: Window, *, section: str = "all",
    series_end: date, window_days: int = 30, tz: Optional[tzinfo] = None, history_days: int = 90,
) -> str:
    if section not in SECTIONS:
        raise ValueError(f"section must be one of {', '.join(SECTIONS)}.")
    parts: List[str] = []
    if section in ("all", "metrics"):
        parts.append(_write(_metrics_rows(conn, person_id, scope, window, history_days)))
    if section in ("all", "series"):
        parts.append(_write(_series_rows(conn, person_id, scope, series_end, window_days, tz)))
    return "\r\n".join(parts)
