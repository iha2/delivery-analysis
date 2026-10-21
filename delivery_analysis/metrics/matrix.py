from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from delivery_analysis.metrics.catalog import BY_NAME, METRICS
from delivery_analysis.metrics.people import People, Scope
from delivery_analysis.metrics.registry import PER_PERSON, run_metric
from delivery_analysis.metrics.window import Window

UNMAPPED_NAME = "Unmapped accounts"


GROUP_ORDER = ("impact", "delivery", "participation")


def _matrix_metrics():
    """Per-person metrics of the impact model's groups, grouped in order, then in catalog order."""
    out = [m for group in GROUP_ORDER for m in METRICS if m.kind == PER_PERSON and m.group == group]
    # The ratio's denominator sits right beside it; cost_spent keeps its own (activity) group in the catalog.
    at = next(i for i, m in enumerate(out) if m.name == "impact_per_dollar") + 1
    out.insert(at, BY_NAME["cost_spent"])
    return out


def _cell(row: Dict[str, Any]) -> Dict[str, Any]:
    cell = {key: row.get(key) for key in ("value", "sample", "ranked", "rank", "confidence")}
    return {**cell, "reason": row.get("unranked_reason")}


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
    for metric in _matrix_metrics():
        result = run_metric(conn, metric, scope, window, people, history_days=history_days)
        columns.append({
            "name": metric.name, "label": result["label"], "unit": result["unit"], "better": result["better"],
            "description": result["description"], "needs": result["needs"], "status": result["status"],
            "missing": result["missing"], "group": "impact" if metric.name == "cost_spent" else metric.group,
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
