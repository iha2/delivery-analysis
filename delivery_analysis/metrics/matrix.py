from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from delivery_analysis.metrics.catalog import METRICS
from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.registry import PER_PERSON, run_metric
from delivery_analysis.metrics.window import Window

UNMAPPED_NAME = "Unmapped accounts"


def _cell(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: row.get(key) for key in ("value", "sample", "ranked", "rank", "confidence")}


def people_matrix(
    conn: sqlite3.Connection, scope: Scope, window: Window, *, history_days: int = 90
) -> Dict[str, Any]:
    """Every per-person metric as one person-by-metric table; all numbers come from run_metric."""
    people = People(conn)
    columns: List[Dict[str, Any]] = []
    names: Dict[str, str] = {}
    cells: Dict[str, Dict[str, Any]] = {}
    unmapped: Dict[str, Any] = {}
    notes: List[str] = []
    waiting: Dict[str, int] = {}
    for metric in (m for m in METRICS if m.kind == PER_PERSON):
        result = run_metric(conn, metric, scope, window, people, history_days=history_days)
        columns.append({
            "name": metric.name, "label": result["label"], "unit": result["unit"], "better": result["better"],
            "description": result["description"], "needs": result["needs"], "status": result["status"],
            "missing": result["missing"],
        })
        for source in result["missing"]:
            waiting[source] = waiting.get(source, 0) + 1
        if result["status"] != "ok":
            continue
        for row in result["rows"]:
            if row["person_id"] is None:
                unmapped[metric.name] = _cell(row)
            else:
                names[row["person_id"]] = row["name"]
                cells.setdefault(row["person_id"], {})[metric.name] = _cell(row)
        for note in result["notes"]:
            if note not in notes:
                notes.append(note)
    rows: List[Dict[str, Any]] = [
        {"person_id": pid, "name": names[pid], "cells": cells[pid]}
        for pid in sorted(names, key=lambda pid: (names[pid].lower(), pid))
    ]
    if unmapped:
        rows.append({"person_id": None, "name": UNMAPPED_NAME, "cells": unmapped})
    for source, count in waiting.items():
        verb = "is" if count == 1 else "are"
        notes.append(f"{count} metric{'' if count == 1 else 's'} {verb} waiting for {source} data.")
    return {"window": window.to_json(), "columns": columns, "rows": rows, "notes": notes}
