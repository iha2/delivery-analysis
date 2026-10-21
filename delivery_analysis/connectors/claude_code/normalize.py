from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

EDIT_TOOLS = ("edit_tool", "multi_edit_tool", "write_tool", "notebook_edit_tool")
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_creation")
SIX_PLACES = Decimal("0.000001")


class NormalizeError(ValueError):
    """A record that cannot be stored safely (for example a currency other than USD)."""


@dataclass(frozen=True)
class UsageRow:
    day: str
    actor_type: str
    actor: str
    model: str
    cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int


@dataclass(frozen=True)
class ActivityRow:
    day: str
    actor_type: str
    actor: str
    sessions: int
    lines_added: int
    lines_removed: int
    commits: int
    pull_requests: int
    edits_accepted: int
    edits_rejected: int
    tool_actions: str  # JSON map of tool name to accepted and rejected counts
    customer_types: str  # comma list, sorted


@dataclass
class DayResult:
    usage: List[UsageRow] = field(default_factory=list)
    activity: List[ActivityRow] = field(default_factory=list)
    skipped: int = 0


def _int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _cents(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except InvalidOperation:
        return Decimal(0)


def _actor(record: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    actor = record.get("actor") or {}
    kind = actor.get("type")
    if kind == "user_actor":
        email = str(actor.get("email_address") or "").strip().lower()
        return ("email", email) if email else None
    if kind == "api_actor":
        name = str(actor.get("api_key_name") or "").strip()
        return ("claude_api_key", name) if name else None
    return None


def normalize_day(day: str, records: Iterable[Mapping[str, Any]]) -> DayResult:
    """Sum one UTC day's records per actor and model (several rows per email and day are normal)."""
    cost: Dict[Tuple[str, str, str], Decimal] = {}
    tokens: Dict[Tuple[str, str, str], List[int]] = {}
    activity: Dict[Tuple[str, str], Dict[str, Any]] = {}
    result = DayResult()
    for record in records:
        who = _actor(record)
        if who is None:
            result.skipped += 1
            continue
        for item in record.get("model_breakdown") or []:
            estimated = item.get("estimated_cost") or {}
            currency = str(estimated.get("currency") or "USD")
            if currency != "USD":
                raise NormalizeError(f"Claude usage for {day} is in {currency}, not USD; only USD is supported.")
            key = (who[0], who[1], str(item.get("model") or "unknown"))
            cost[key] = cost.get(key, Decimal(0)) + _cents(estimated.get("amount"))
            sums = tokens.setdefault(key, [0, 0, 0, 0])
            counts = item.get("tokens") or {}
            for index, name in enumerate(TOKEN_FIELDS):
                sums[index] += _int(counts.get(name))
        act = activity.setdefault(who, {
            "sessions": 0, "lines_added": 0, "lines_removed": 0, "commits": 0, "pull_requests": 0,
            "edits_accepted": 0, "edits_rejected": 0, "tools": {}, "customer_types": set(),
        })
        core = record.get("core_metrics") or {}
        lines = core.get("lines_of_code") or {}
        act["sessions"] += _int(core.get("num_sessions"))
        act["lines_added"] += _int(lines.get("added"))
        act["lines_removed"] += _int(lines.get("removed"))
        act["commits"] += _int(core.get("commits_by_claude_code"))
        act["pull_requests"] += _int(core.get("pull_requests_by_claude_code"))
        for tool, counts in (record.get("tool_actions") or {}).items():
            accepted = _int((counts or {}).get("accepted"))
            rejected = _int((counts or {}).get("rejected"))
            entry = act["tools"].setdefault(str(tool), {"accepted": 0, "rejected": 0})
            entry["accepted"] += accepted
            entry["rejected"] += rejected
            if tool in EDIT_TOOLS:
                act["edits_accepted"] += accepted
                act["edits_rejected"] += rejected
        if record.get("customer_type"):
            types: Set[str] = act["customer_types"]
            types.add(str(record["customer_type"]))
    for key in sorted(cost):
        dollars = float((cost[key] / Decimal(100)).quantize(SIX_PLACES))
        t = tokens[key]
        result.usage.append(UsageRow(day, key[0], key[1], key[2], dollars, t[0], t[1], t[2], t[3]))
    for who in sorted(activity):
        act = activity[who]
        result.activity.append(ActivityRow(
            day, who[0], who[1], act["sessions"], act["lines_added"], act["lines_removed"], act["commits"],
            act["pull_requests"], act["edits_accepted"], act["edits_rejected"],
            json.dumps(act["tools"], sort_keys=True), ",".join(sorted(act["customer_types"])),
        ))
    return result


def _utc_day(value: Any) -> Optional[str]:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).date().isoformat()


def normalize_cost_rows(rows: Iterable[Mapping[str, Any]]) -> DayResult:
    """Sum user_cost_report rows per (UTC day, email, model); `amount` is a decimal string in cents."""
    cost: Dict[Tuple[str, str, str], Decimal] = {}
    result = DayResult()
    for record in rows:
        actor = record.get("actor") or {}
        email = str(actor.get("email_address") or "").strip().lower()
        day = _utc_day(record["starting_at"]) if record.get("starting_at") else None
        if not email or day is None:
            result.skipped += 1
            continue
        currency = str(record.get("currency") or "USD")
        if currency != "USD":
            raise NormalizeError(f"Claude cost for {day} is in {currency}, not USD; only USD is supported.")
        key = (day, email, str(record.get("model") or "unknown"))
        cost[key] = cost.get(key, Decimal(0)) + _cents(record.get("amount"))
    for key in sorted(cost):
        dollars = float((cost[key] / Decimal(100)).quantize(SIX_PLACES))
        result.usage.append(UsageRow(key[0], "email", key[1], key[2], dollars, 0, 0, 0, 0))
    return result


def usage_values(source: str, row: UsageRow) -> Dict[str, Any]:
    return {
        "source": source, "day": row.day, "actor_type": row.actor_type, "actor": row.actor, "model": row.model,
        "cost_usd": row.cost_usd, "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
        "cache_read_tokens": row.cache_read_tokens, "cache_creation_tokens": row.cache_creation_tokens,
    }


def activity_values(source: str, row: ActivityRow) -> Dict[str, Any]:
    return {
        "source": source, "day": row.day, "actor_type": row.actor_type, "actor": row.actor,
        "sessions": row.sessions, "lines_added": row.lines_added, "lines_removed": row.lines_removed,
        "commits": row.commits, "pull_requests": row.pull_requests, "edits_accepted": row.edits_accepted,
        "edits_rejected": row.edits_rejected, "tool_actions": row.tool_actions,
        "customer_types": row.customer_types,
    }
