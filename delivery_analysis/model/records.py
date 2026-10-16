from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Natural key columns per table. Source records key on (source, source_id).
TABLE_KEYS: Dict[str, Tuple[str, ...]] = {
    "person": ("person_id",),
    "identity": ("source", "account_id"),
    "repository": ("source", "source_id"),
    "change_request": ("source", "source_id"),
    "change_event": ("source", "source_id"),
    "vcs_commit": ("source", "source_id"),
    "work_item": ("source", "source_id"),
    "work_item_transition": ("source", "source_id"),
    "document": ("source", "source_id"),
    "document_version": ("source", "source_id"),
    "link": ("source", "source_id"),
    "property": ("record_kind", "record_id", "name"),
    "token_usage": ("person_id", "day", "model", "purpose", "source"),
    "token_attribution": ("person_id", "day", "work_item_source", "work_item_id"),
    "ticket_credit": ("work_item_source", "work_item_id", "person_id"),
    "claude_usage_day": ("source", "day", "actor_type", "actor", "model"),
    "claude_activity_day": ("source", "day", "actor_type", "actor"),
}


@dataclass(frozen=True)
class Record:
    """One canonical row for `table`; `values` maps column names to values."""

    table: str
    values: Dict[str, Any]

    def __post_init__(self) -> None:
        if self.table not in TABLE_KEYS:
            raise ValueError(f"unknown table {self.table!r}")
        missing = [column for column in TABLE_KEYS[self.table] if column not in self.values]
        if missing:
            raise ValueError(
                f"{self.table} record is missing key column(s): {', '.join(missing)}"
            )


@dataclass(frozen=True)
class RawPayload:
    source: str
    source_id: str
    kind: str
    json: str


@dataclass
class Batch:
    """A unit of work from a connector. `cursor` is stored in the same transaction as the batch.

    `cursor` must be a UTC ISO timestamp (`YYYY-MM-DDTHH:MM:SSZ`); the runner treats anything
    else as "no usable cursor" and does a full sync. `replace` lists (table, {column: value})
    equality deletes that run first, in the same transaction, so a connector can replace a slice
    (for example one day) instead of only upserting.
    """

    records: List[Record]
    raw: List[RawPayload] = field(default_factory=list)
    cursor: Optional[str] = None
    replace: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
