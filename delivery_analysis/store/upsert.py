from __future__ import annotations

import sqlite3
from typing import Any, List, Mapping, Tuple

from delivery_analysis.model.records import TABLE_KEYS, Batch, RawPayload, Record


def _columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def upsert_record(conn: sqlite3.Connection, record: Record, fetched_at: str) -> None:
    columns = _columns(conn, record.table)
    values = dict(record.values)
    if "fetched_at" in columns and "fetched_at" not in values:
        values["fetched_at"] = fetched_at
    unknown = sorted(name for name in values if name not in columns)
    if unknown:
        raise ValueError(f"{record.table} has no column(s): {', '.join(unknown)}")
    keys = TABLE_KEYS[record.table]
    names = list(values)
    updates = [name for name in names if name not in keys]
    action = (
        "DO UPDATE SET " + ", ".join(f"{name}=excluded.{name}" for name in updates)
        if updates
        else "DO NOTHING"
    )
    sql = (
        f"INSERT INTO {record.table} ({', '.join(names)}) "
        f"VALUES ({', '.join('?' for _ in names)}) "
        f"ON CONFLICT({', '.join(keys)}) {action}"
    )
    conn.execute(sql, [values[name] for name in names])


def upsert_raw(conn: sqlite3.Connection, raw: RawPayload, fetched_at: str) -> None:
    conn.execute(
        "INSERT INTO raw_payload (source, source_id, kind, json, fetched_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(source, source_id, kind) DO UPDATE SET "
        "json=excluded.json, fetched_at=excluded.fetched_at",
        (raw.source, raw.source_id, raw.kind, raw.json, fetched_at),
    )


def delete_matching(conn: sqlite3.Connection, table: str, filters: Mapping[str, Any]) -> None:
    """Delete the rows of `table` whose columns equal `filters`. The caller owns the transaction."""
    if table not in TABLE_KEYS:
        raise ValueError(f"unknown table {table!r}")
    if not filters:
        raise ValueError(f"a replace for {table} needs at least one column filter")
    columns = _columns(conn, table)
    unknown = sorted(name for name in filters if name not in columns)
    if unknown:
        raise ValueError(f"{table} has no column(s): {', '.join(unknown)}")
    names = sorted(filters)
    conn.execute(
        f"DELETE FROM {table} WHERE " + " AND ".join(f"{name} = ?" for name in names),
        [filters[name] for name in names],
    )


def write_batch(conn: sqlite3.Connection, batch: Batch, fetched_at: str) -> int:
    """Write a batch's rows. The caller owns the transaction."""
    for table, filters in batch.replace:
        delete_matching(conn, table, filters)
    for record in batch.records:
        upsert_record(conn, record, fetched_at)
    for raw in batch.raw:
        upsert_raw(conn, raw, fetched_at)
    return len(batch.records)


def unmapped_identities(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    """Accounts seen in synced data that have no person mapped in `identity`."""
    rows = conn.execute(
        """
        SELECT a.source AS source, a.account AS account FROM (
            SELECT source, author_account AS account FROM change_request
            UNION SELECT source, actor_account FROM change_event
            UNION SELECT source, author_account FROM vcs_commit
            UNION SELECT source, assignee_account FROM work_item
            UNION SELECT source, reporter_account FROM work_item
            UNION SELECT source, actor_account FROM work_item_transition
            UNION SELECT source, author_account FROM document
            UNION SELECT source, author_account FROM document_version
        ) a
        WHERE a.account IS NOT NULL AND a.account != ''
          AND NOT EXISTS (
              SELECT 1 FROM identity i
              WHERE i.source = a.source AND i.account_id = a.account AND i.person_id IS NOT NULL
          )
        ORDER BY a.source, a.account
        """
    ).fetchall()
    return [(row["source"], row["account"]) for row in rows]
