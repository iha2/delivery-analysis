from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from delivery_analysis.tokens.accounts import AccountMap
from delivery_analysis.tokens.config import DEFAULT_CONFIG, AttributionConfig


@dataclass(frozen=True)
class PersonUsage:
    person_id: str
    day: str
    model: str
    purpose: str
    cost_usd: float
    total_tokens: int
    source: str
    purpose_method: str
    purpose_confidence: str


@dataclass
class UsageResult:
    rows: List[PersonUsage] = field(default_factory=list)
    unmapped: Dict[Tuple[str, str], float] = field(default_factory=dict)


def generate_share(accepted: Optional[int], half: float) -> float:
    """v1 proxy: accepted edit and write actions saturate towards an all-generate day."""
    count = max(0, int(accepted or 0))
    if count == 0:
        return 0.0
    return count / (count + half)


def derive_usage(conn: sqlite3.Connection, accounts: AccountMap, config: AttributionConfig = DEFAULT_CONFIG) -> UsageResult:
    result = UsageResult()
    totals: Dict[Tuple[str, str, str, str], List[float]] = {}  # (person, day, model, source) -> [cost, tokens]
    for row in conn.execute(
        "SELECT source, day, actor_type, actor, model, cost_usd, "
        "input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens AS tokens FROM claude_usage_day"
    ):
        person = accounts.person(row["actor_type"], row["actor"])
        if person is None:
            if not accounts.is_excluded(row["actor_type"], row["actor"]):
                key = (row["actor_type"], row["actor"])
                result.unmapped[key] = round(result.unmapped.get(key, 0.0) + row["cost_usd"], 6)
            continue
        cell = totals.setdefault((person, row["day"], row["model"], row["source"]), [0.0, 0])
        cell[0] += row["cost_usd"]
        cell[1] += int(row["tokens"] or 0)
    accepted: Dict[Tuple[str, str, str], int] = {}  # (person, day, source)
    for row in conn.execute("SELECT source, day, actor_type, actor, edits_accepted FROM claude_activity_day"):
        person = accounts.person(row["actor_type"], row["actor"])
        if person is not None:
            key = (person, row["day"], row["source"])
            accepted[key] = accepted.get(key, 0) + int(row["edits_accepted"] or 0)
    for (person, day, model, source), (amount, tokens) in sorted(totals.items()):
        key = (person, day, source)
        if key in accepted:
            share = generate_share(accepted[key], config.generate_half_saturation)
            generate = round(amount * share, 6)
            generate_tokens = int(round(tokens * share))
            result.rows.append(PersonUsage(person, day, model, "ask", round(amount - generate, 6),
                                           int(tokens) - generate_tokens, source, "v1_actions", "low"))
            result.rows.append(PersonUsage(person, day, model, "generate", generate, generate_tokens,
                                           source, "v1_actions", "low"))
        else:
            result.rows.append(PersonUsage(person, day, model, "unclassified", round(amount, 6), int(tokens),
                                           source, "none", "low"))
    return result


def write_usage(conn: sqlite3.Connection, rows: Sequence[PersonUsage]) -> None:
    """Insert derived usage rows. The caller owns the transaction."""
    conn.executemany(
        "INSERT INTO token_usage (person_id, day, model, purpose, cost_usd, total_tokens, source, "
        "purpose_method, purpose_confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(r.person_id, r.day, r.model, r.purpose, r.cost_usd, r.total_tokens, r.source, r.purpose_method,
          r.purpose_confidence) for r in rows],
    )
