from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from delivery_analysis.connectors.jira.fields import (
    EXCLUDED_FIELDS,
    SKIP_PROPERTY,
    FieldCatalogue,
    flatten_value,
    points_value,
)
from delivery_analysis.core.time_utils import to_utc_iso
from delivery_analysis.model.records import RawPayload, Record

SOURCE = "jira"
STARTED_STATUS = "In Progress"
ISO_Z = "%Y-%m-%dT%H:%M:%SZ"
USER_FIELDS = ("assignee", "reporter", "creator")


def prop(
    kind: str, record_id: str, name: str, value: Optional[str], source_field_id: Optional[str] = None
) -> Record:
    values: Dict[str, Any] = {"record_kind": kind, "record_id": record_id, "name": name, "value": value}
    if source_field_id:
        values["source_field_id"] = source_field_id
    return Record("property", values)


def ts_to_utc_iso(value: Any) -> Optional[str]:
    """UTC `YYYY-MM-DDTHH:MM:SSZ` from a `-0700`-style string or epoch milliseconds (bulkfetch)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"not a timestamp: {value!r}")
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit() and len(value.strip()) >= 11):
        moment = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        return moment.strftime(ISO_Z)
    return to_utc_iso(str(value))


@dataclass(frozen=True)
class Transition:
    history_id: str
    index: int
    from_status: Optional[str]
    to_status: Optional[str]
    actor: Optional[str]
    occurred_at: str


def _history_order(history_id: str) -> int:
    return int(history_id) if str(history_id).isdigit() else 0


def status_transitions(histories: Sequence[Mapping[str, Any]]) -> List[Transition]:
    """Status items of change histories, oldest first. Other fields are ignored."""
    found: List[Transition] = []
    for entry in histories:
        occurred = ts_to_utc_iso(entry.get("created"))
        if occurred is None:
            raise ValueError(f"History entry {entry.get('id')!r} has no created timestamp.")
        actor = (entry.get("author") or {}).get("accountId") or None
        for index, item in enumerate(entry.get("items") or []):
            if item.get("fieldId") != "status":
                continue
            found.append(
                Transition(
                    str(entry.get("id")), index, item.get("fromString"), item.get("toString"), actor, occurred
                )
            )
    found.sort(key=lambda t: (t.occurred_at, _history_order(t.history_id), t.index))
    return found


@dataclass(frozen=True)
class Lifecycle:
    started_at: Optional[str]
    resolved_at: Optional[str]
    reopen_count: int
    unknown_statuses: Tuple[str, ...]


def lifecycle(
    transitions: Sequence[Transition],
    status_map: Mapping[str, str],
    current_category: str,
    started_status: str = STARTED_STATUS,
) -> Lifecycle:
    started: Optional[str] = None
    last_done: Optional[str] = None
    reopened = 0
    unknown = set()
    for t in transitions:
        for name in (t.from_status, t.to_status):
            if name and name not in status_map:
                unknown.add(name)
        if started is None and t.to_status == started_status:
            started = t.occurred_at
        if status_map.get(t.to_status or "") == "done":
            last_done = t.occurred_at
        if status_map.get(t.from_status or "") == "done" and status_map.get(t.to_status or "") != "done":
            reopened += 1
    resolved = last_done if current_category == "done" else None
    return Lifecycle(started, resolved, reopened, tuple(sorted(unknown)))


@dataclass(frozen=True)
class IssueResult:
    records: List[Record]
    raw: RawPayload
    updated: Optional[str]
    unknown_statuses: Tuple[str, ...]


def _account_records(user: Any) -> List[Record]:
    if not isinstance(user, dict) or not user.get("accountId"):
        return []
    account = str(user["accountId"])
    identity: Dict[str, Any] = {"source": SOURCE, "account_id": account}
    if user.get("displayName"):
        identity["label"] = user["displayName"]  # never person_id: a mapped person must stay mapped
    records = [Record("identity", identity)]
    record_id = f"{SOURCE}:{account}"
    if user.get("emailAddress"):
        records.append(prop("identity", record_id, "email", str(user["emailAddress"]).strip().lower()))
    if user.get("accountType"):
        records.append(prop("identity", record_id, "account_type", str(user["accountType"])))
    if "active" in user:
        records.append(prop("identity", record_id, "active", "true" if user["active"] else "false"))
    return records


def _link_records(issue_id: str, fields: Mapping[str, Any]) -> List[Record]:
    records: List[Record] = []
    for link in fields.get("issuelinks") or []:
        kind = (link.get("type") or {}).get("name")
        if link.get("outwardIssue"):
            source, target = issue_id, str(link["outwardIssue"]["id"])
        elif link.get("inwardIssue"):
            source, target = str(link["inwardIssue"]["id"]), issue_id
        else:
            continue
        records.append(
            Record(
                "link",
                {
                    "source": SOURCE,
                    "source_id": f"issuelink:{link['id']}",
                    "from_kind": "work_item",
                    "from_id": source,
                    "to_kind": "work_item",
                    "to_id": target,
                    "kind": kind,
                    "found_by": SOURCE,
                },
            )
        )
    parent = fields.get("parent")
    if isinstance(parent, dict) and parent.get("id"):
        records.append(
            Record(
                "link",
                {
                    "source": SOURCE,
                    "source_id": f"parent:{issue_id}:{parent['id']}",
                    "from_kind": "work_item",
                    "from_id": issue_id,
                    "to_kind": "work_item",
                    "to_id": str(parent["id"]),
                    "kind": "parent",
                    "found_by": SOURCE,
                },
            )
        )
    return records


def _excluded_types(project: Mapping[str, Any]) -> set:
    return {part.strip() for part in (project.get("excluded_types") or "").split(",") if part.strip()}


PERSONAL_KEYS = frozenset({"emailAddress", "avatarUrls"})


def _without_personal_keys(value: Any) -> Any:
    """A deep copy with `emailAddress` and `avatarUrls` removed at any depth (emails live only in
    property(identity, email))."""
    if isinstance(value, Mapping):
        return {k: _without_personal_keys(v) for k, v in value.items() if k not in PERSONAL_KEYS}
    if isinstance(value, (list, tuple)):
        return [_without_personal_keys(v) for v in value]
    return value


def issue_records(
    issue: Mapping[str, Any],
    project: Mapping[str, Any],
    status_map: Mapping[str, str],
    catalogue: FieldCatalogue,
    histories: Sequence[Mapping[str, Any]],
) -> IssueResult:
    """Every canonical record for one issue and its status history. Raises ValueError when the
    current status has no mapping or a timestamp is malformed (the caller writes nothing then)."""
    fields = issue.get("fields") or {}
    issue_id = str(issue["id"])
    status = fields.get("status") or {}
    status_name = status.get("name")
    category = status_map.get(status_name or "")
    if category is None:
        raise ValueError(f"Status {status_name!r} of {issue.get('key')} has no mapping.")
    transitions = status_transitions(histories)
    life = lifecycle(transitions, status_map, category)
    points_field = project.get("story_points_field")
    issue_type = fields.get("issuetype") or {}
    counts = issue_type.get("name") not in _excluded_types(project) and not issue_type.get("subtask")
    records: List[Record] = [
        Record(
            "work_item",
            {
                "source": SOURCE,
                "source_id": issue_id,
                "project": (fields.get("project") or {}).get("key"),
                "key": issue.get("key"),
                "type": issue_type.get("name"),
                "summary": fields.get("summary"),
                "assignee_account": (fields.get("assignee") or {}).get("accountId") or None,
                "reporter_account": (fields.get("reporter") or {}).get("accountId") or None,
                "status": status_name,
                "status_category": category,
                "created_at": ts_to_utc_iso(fields.get("created")),
                "started_at": life.started_at,
                "resolved_at": life.resolved_at,
                "story_points": points_value(fields.get(points_field)) if points_field else None,
            },
        )
    ]
    for t in transitions:
        records.append(
            Record(
                "work_item_transition",
                {
                    "source": SOURCE,
                    "source_id": f"{issue_id}:{t.history_id}:{t.index}",
                    "work_item_id": issue_id,
                    "from_status": t.from_status,
                    "to_status": t.to_status,
                    "actor_account": t.actor,
                    "occurred_at": t.occurred_at,
                },
            )
        )
    seen_accounts = set()
    for name in USER_FIELDS:
        user = fields.get(name)
        if isinstance(user, dict) and user.get("accountId") and user["accountId"] not in seen_accounts:
            seen_accounts.add(user["accountId"])
            records.extend(_account_records(user))
    records.extend(_link_records(issue_id, fields))
    for field_id, value in fields.items():
        if field_id in EXCLUDED_FIELDS or field_id in SKIP_PROPERTY:
            continue
        text = flatten_value(value)
        if text is None:
            continue
        custom = field_id if catalogue.is_custom(field_id) else None
        records.append(prop("work_item", issue_id, catalogue.property_name(field_id), text, custom))
    records.append(prop("work_item", issue_id, "counts_for_impact", "1" if counts else "0"))
    records.append(prop("work_item", issue_id, "reopen_count", str(life.reopen_count)))
    if status.get("id") is not None:
        records.append(prop("work_item", issue_id, "status_id", str(status["id"])))
    parent = fields.get("parent")
    if isinstance(parent, dict) and parent.get("key"):
        records.append(prop("work_item", issue_id, "parent_key", str(parent["key"])))
    raw = RawPayload(SOURCE, issue_id, "issue", json.dumps(_without_personal_keys(issue), sort_keys=True))
    return IssueResult(records, raw, ts_to_utc_iso(fields.get("updated")), life.unknown_statuses)
