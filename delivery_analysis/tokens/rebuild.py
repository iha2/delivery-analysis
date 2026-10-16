from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from delivery_analysis.tokens.accounts import AccountMap
from delivery_analysis.tokens.allocate import allocate
from delivery_analysis.tokens.candidates import active_intervals, candidates_for_day
from delivery_analysis.tokens.config import ALGO_VERSION, DEFAULT_CONFIG, AttributionConfig
from delivery_analysis.tokens.credit import Credit, compute_credit, roll_up_evidence
from delivery_analysis.tokens.evidence import load_evidence
from delivery_analysis.tokens.tickets import load_tickets
from delivery_analysis.tokens.types import RebuildError, TicketKey
from delivery_analysis.tokens.usage import PersonUsage, check_usage_reconciles, derive_usage, write_usage

CENT = 0.01


@dataclass
class RebuildSummary:
    usage_rows: int = 0
    usage_usd: float = 0.0
    people_with_cost: int = 0
    unmapped_actors: int = 0
    unmapped_usd: float = 0.0
    attribution_ran: bool = False
    attributed_usd: float = 0.0
    unattributed_usd: Dict[str, float] = field(default_factory=dict)
    tickets_without_points: int = 0
    tickets_without_credit: int = 0
    first_day: Optional[str] = None
    last_day: Optional[str] = None

    def lines(self) -> List[str]:
        if not self.usage_rows and not self.unmapped_actors:
            return ["Claude usage: nothing stored yet."]
        out = [f"Claude cost: ${self.usage_usd:.2f} across {self.people_with_cost} people."]
        if self.unmapped_actors:
            out.append(
                f"Unmapped Claude users: {self.unmapped_actors}, ${self.unmapped_usd:.2f} "
                "(map them on the Teams screen)."
            )
        if not self.attribution_ran:
            out.append("Attribution skipped: no Jira issues are synced yet.")
            return out
        unattributed = sum(self.unattributed_usd.values())
        reasons = ", ".join(f"{name} ${value:.2f}" for name, value in sorted(self.unattributed_usd.items()))
        span = f" from {self.first_day} to {self.last_day}" if self.first_day else ""
        out.append(
            f"Attributed ${self.attributed_usd:.2f} to tickets{span}; unattributed ${unattributed:.2f}"
            + (f" ({reasons})" if reasons else "") + "."
        )
        out.append(
            f"Completed tickets without story points: {self.tickets_without_points}. "
            f"Completed tickets with no credit: {self.tickets_without_credit}."
        )
        return out


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ticket_text(ticket: TicketKey) -> str:
    return f"{ticket[0]}:{ticket[1]}"


def _write(
    conn: sqlite3.Connection,
    accounts: AccountMap,
    usage_rows: Sequence[PersonUsage],
    attribution: Sequence[Dict[str, Any]],
    credits: Sequence[Credit],
) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table in ("token_attribution", "ticket_credit", "token_usage"):
            conn.execute(f"DELETE FROM {table}")
        write_usage(conn, usage_rows)
        check_usage_reconciles(conn, accounts)
        conn.executemany(
            "INSERT INTO token_attribution (person_id, day, work_item_source, work_item_id, cost_usd, weight, "
            "evidence, method, confidence, reason, inputs, algo_version, computed_at) VALUES (:person_id, :day, "
            ":work_item_source, :work_item_id, :cost_usd, :weight, :evidence, :method, :confidence, :reason, "
            ":inputs, :algo_version, :computed_at)",
            attribution,
        )
        conn.executemany(
            "INSERT INTO ticket_credit (work_item_source, work_item_id, person_id, share, evidence, method) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(c.ticket[0], c.ticket[1], c.person_id, c.share, c.evidence, c.method) for c in credits],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def rebuild(
    conn: sqlite3.Connection,
    today: date,
    *,
    config: AttributionConfig = DEFAULT_CONFIG,
    window_days: int = 90,
    now: Optional[str] = None,
) -> RebuildSummary:
    """Recompute token_usage, token_attribution and ticket_credit from stored data, deterministically."""
    stamp = now or _now_iso()
    summary = RebuildSummary()
    accounts = AccountMap(conn)
    usage = derive_usage(conn, accounts, config)
    summary.usage_rows = len(usage.rows)
    summary.usage_usd = round(sum(r.cost_usd for r in usage.rows), 2)
    summary.people_with_cost = len({r.person_id for r in usage.rows})
    summary.unmapped_actors = len(usage.unmapped)
    summary.unmapped_usd = round(sum(usage.unmapped.values()), 2)
    tickets = load_tickets(conn, accounts)
    attribution: List[Dict[str, Any]] = []
    credits: List[Credit] = []
    if tickets:
        summary.attribution_ran = True
        first = today - timedelta(days=window_days)
        day_cost: Dict[Tuple[str, date], float] = {}
        for row in usage.rows:
            day = date.fromisoformat(row.day)
            if first <= day < today:
                day_cost[(row.person_id, day)] = day_cost.get((row.person_id, day), 0.0) + row.cost_usd
        evidence = load_evidence(conn, accounts, tickets, config)
        intervals = {key: active_intervals(info.transitions, info.merges) for key, info in tickets.items()}
        eligible = {key for key, info in tickets.items() if info.eligible}
        assigned: Dict[str, Set[TicketKey]] = {}
        for key, info in tickets.items():
            if info.assignee_person:
                assigned.setdefault(info.assignee_person, set()).add(key)
        config_json = config.as_json()
        attributed = 0.0
        for (person, day), cost in sorted(day_cost.items()):
            found = candidates_for_day(day, today, assigned.get(person, set()), evidence.for_person(person),
                                       intervals, eligible, config)
            allocations = allocate(cost, found, (person, day) in evidence.untracked, config)
            total = sum(a.cost_usd for a in allocations)
            if allocations and abs(total - cost) > CENT or (not allocations and cost > CENT):
                raise RebuildError(
                    f"Attribution for {person} on {day.isoformat()} does not add up "
                    f"(${total:.2f} of ${cost:.2f}); nothing was changed."
                )
            inputs = json.dumps({
                "candidates": [
                    {"ticket": _ticket_text(c.ticket), "key": tickets[c.ticket].issue_key,
                     "evidence": c.evidence, "known": c.known}
                    for c in found
                ],
                "untracked_commits": (person, day) in evidence.untracked,
                "config": config_json,
            }, sort_keys=True)
            for a in allocations:
                attribution.append({
                    "person_id": person, "day": day.isoformat(),
                    "work_item_source": a.ticket[0] if a.ticket else "",
                    "work_item_id": a.ticket[1] if a.ticket else "",
                    "cost_usd": a.cost_usd, "weight": a.weight, "evidence": a.evidence, "method": a.method,
                    "confidence": a.confidence, "reason": a.reason, "inputs": inputs,
                    "algo_version": ALGO_VERSION, "computed_at": stamp,
                })
                if a.ticket is None:
                    reason = a.reason or "no_active_ticket"
                    summary.unattributed_usd[reason] = round(summary.unattributed_usd.get(reason, 0.0) + a.cost_usd, 6)
                else:
                    attributed += a.cost_usd
        summary.attributed_usd = round(attributed, 2)
        summary.unattributed_usd = {k: round(v, 2) for k, v in summary.unattributed_usd.items()}
        if day_cost:
            days = sorted(day for _, day in day_cost)
            summary.first_day, summary.last_day = days[0].isoformat(), days[-1].isoformat()
        parents = {key: info.parent for key, info in tickets.items() if info.parent in eligible}
        totals = roll_up_evidence(
            {key: value for key, value in evidence.totals().items() if key[0] in eligible}, parents
        )
        credits, _ = compute_credit(totals, {k: i.assignee_person for k, i in tickets.items() if i.eligible})
        credited = {c.ticket for c in credits}
        done = [i for i in tickets.values() if i.counts_for_impact and i.status_category == "done"]
        summary.tickets_without_points = sum(1 for i in done if i.story_points is None)
        summary.tickets_without_credit = sum(1 for i in done if i.key not in credited)
    _write(conn, accounts, usage.rows, attribution, credits)
    return summary
