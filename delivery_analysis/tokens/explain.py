from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List


def find_person(conn: sqlite3.Connection, text: str) -> str:
    """A person id from an id or a display name (case-insensitive, must be unique)."""
    value = (text or "").strip()
    row = conn.execute("SELECT person_id FROM person WHERE person_id = ?", (value,)).fetchone()
    if row is not None:
        return row["person_id"]
    matches = conn.execute(
        "SELECT person_id FROM person WHERE lower(display_name) = lower(?)", (value,)
    ).fetchall()
    if len(matches) == 1:
        return matches[0]["person_id"]
    if not matches:
        raise LookupError(f"No person with id or name {value!r}.")
    raise LookupError(f"More than one person is named {value!r}; use the person id.")


def explain(conn: sqlite3.Connection, person_id: str, day: str) -> Dict[str, Any]:
    usage = [
        {"model": r["model"], "purpose": r["purpose"], "cost_usd": round(r["cost_usd"], 6)}
        for r in conn.execute(
            "SELECT model, purpose, cost_usd FROM token_usage WHERE person_id = ? AND day = ? ORDER BY model, purpose",
            (person_id, day),
        )
    ]
    rows = conn.execute(
        "SELECT ta.work_item_id, w.key AS key, ta.cost_usd, ta.weight, ta.evidence, ta.method, ta.confidence, "
        "ta.reason, ta.inputs FROM token_attribution ta LEFT JOIN work_item w "
        "ON w.source = ta.work_item_source AND w.source_id = ta.work_item_id "
        "WHERE ta.person_id = ? AND ta.day = ? ORDER BY ta.cost_usd DESC, ta.work_item_id",
        (person_id, day),
    ).fetchall()
    return {
        "person_id": person_id,
        "day": day,
        "usage": usage,
        "rows": [
            {"key": r["key"], "cost_usd": round(r["cost_usd"], 6), "weight": r["weight"], "evidence": r["evidence"],
             "method": r["method"], "confidence": r["confidence"], "reason": r["reason"]}
            for r in rows
        ],
        "inputs": json.loads(rows[0]["inputs"]) if rows else None,
    }


def explain_lines(data: Dict[str, Any]) -> List[str]:
    out = [f"{data['person_id']} on {data['day']} (UTC)"]
    if not data["usage"]:
        out.append("  No Claude cost stored for this day.")
        return out
    for u in data["usage"]:
        out.append(f"  cost {u['model']} {u['purpose']}: ${u['cost_usd']:.2f}")
    if not data["rows"]:
        out.append("  Not attributed (today, outside the attribution window, or no Jira data).")
        return out
    for r in data["rows"]:
        target = r["key"] or f"unattributed ({r['reason']})"
        detail = "" if r["key"] is None else f", weight {r['weight']}, evidence {r['evidence']}"
        out.append(f"  -> {target}: ${r['cost_usd']:.2f}, {r['method']}, {r['confidence'] or '-'}{detail}")
    inputs = data["inputs"] or {}
    for c in inputs.get("candidates", []):
        how = "evidence that day" if c["evidence"] else ("seen before" if c["known"] else "assignee only")
        out.append(f"  candidate {c['key']}: {how}")
    if inputs.get("untracked_commits"):
        out.append("  Commits that day were on no ticket.")
    return out
