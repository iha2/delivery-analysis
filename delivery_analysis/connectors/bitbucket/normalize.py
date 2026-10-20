from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from delivery_analysis.core.time_utils import to_utc_iso
from delivery_analysis.model.records import RawPayload, Record

SOURCE = "bitbucket"


def prop(kind: str, record_id: str, name: str, value: Optional[str]) -> Record:
    return Record(
        "property",
        {"record_kind": kind, "record_id": record_id, "name": name, "value": value},
    )


def _raw(source_id: str, kind: str, data: Any) -> RawPayload:
    return RawPayload(SOURCE, source_id, kind, json.dumps(data, sort_keys=True))


def parse_author_raw(raw: Optional[str]) -> Tuple[str, str]:
    """Split a git author string `Name <email>` into (name, lower-case email). Missing parts are ''."""
    text = (raw or "").strip()
    if not text:
        return "", ""
    start, end = text.rfind("<"), text.rfind(">")
    if start != -1 and end > start:
        return text[:start].strip(), text[start + 1:end].strip().lower()
    if "@" in text and " " not in text:
        return "", text.lower()
    return text, ""


def repository_record(workspace: str, data: Mapping[str, Any]) -> Tuple[Record, RawPayload]:
    uuid = data["uuid"]
    record = Record(
        "repository",
        {
            "source": SOURCE,
            "source_id": uuid,
            "workspace": workspace,
            "name": data.get("slug"),
            "default_branch": (data.get("mainbranch") or {}).get("name"),
        },
    )
    return record, _raw(uuid, "repository", data)


def commit_records(repo_uuid: str, commit: Mapping[str, Any]) -> Tuple[List[Record], RawPayload]:
    sha = commit["hash"]
    source_id = f"{repo_uuid}:{sha}"
    author = commit.get("author") or {}
    name, email = parse_author_raw(author.get("raw"))
    account = (author.get("user") or {}).get("account_id") or None
    records = [
        Record(
            "vcs_commit",
            {
                "source": SOURCE,
                "source_id": source_id,
                "repository_id": repo_uuid,
                "sha": sha,
                "author_account": account,
                "author_name": name or None,
                "author_email": email or None,
                "committed_at": to_utc_iso(commit.get("date")),
            },
        )
    ]
    if len(commit.get("parents") or []) > 1:
        records.append(prop("vcs_commit", source_id, "is_merge", "1"))
    return records, _raw(source_id, "commit", commit)


def pull_request_records(
    repo_uuid: str, pr: Mapping[str, Any], include_times: bool = True
) -> Tuple[List[Record], RawPayload]:
    number = pr["id"]
    source_id = f"{repo_uuid}#{number}"
    state = pr.get("state")
    updated = to_utc_iso(pr.get("updated_on"))
    values: Dict[str, Any] = {
        "source": SOURCE,
        "source_id": source_id,
        "repository_id": repo_uuid,
        "number": str(number),
        "author_account": (pr.get("author") or {}).get("account_id") or None,
        "branch": ((pr.get("source") or {}).get("branch") or {}).get("name"),
        "title": pr.get("title"),
        "state": state,
        "created_at": to_utc_iso(pr.get("created_on")),
    }
    if include_times:
        if state == "MERGED":
            values["merged_at"] = updated
            values["closed_at"] = updated
        elif state in ("DECLINED", "SUPERSEDED"):
            values["closed_at"] = updated
    records = [Record("change_request", values)]
    if updated is not None:
        records.append(prop("change_request", source_id, "updated_on", updated))
    for participant in pr.get("participants") or []:
        account = (participant.get("user") or {}).get("account_id")
        if participant.get("role") == "REVIEWER" and account:
            state = "approved" if participant.get("approved") else "pending"
            records.append(prop("change_request", source_id, f"reviewer:{account}", state))
    if include_times:
        records.append(prop("change_request", source_id, "times_from", "updated_on"))
    return records, _raw(source_id, "pull_request", pr)


@dataclass(frozen=True)
class ActivitySummary:
    merged_at: Optional[str]
    closed_at: Optional[str]


def _event(pr_source_id: str, source_id: str, kind: str, actor: Optional[str], occurred: Optional[str]) -> Record:
    return Record(
        "change_event",
        {
            "source": SOURCE,
            "source_id": source_id,
            "change_request_id": pr_source_id,
            "type": kind,
            "actor_account": actor,
            "occurred_at": occurred,
        },
    )


def activity_records(
    pr_source_id: str, items: Sequence[Mapping[str, Any]]
) -> Tuple[List[Record], ActivitySummary]:
    events: List[Record] = []
    merged: List[str] = []
    closed: List[str] = []
    for item in items:
        if "comment" in item:
            comment = item["comment"]
            if comment.get("deleted"):
                continue
            occurred = to_utc_iso(comment.get("created_on"))
            actor = (comment.get("user") or {}).get("account_id") or None
            events.append(
                _event(pr_source_id, f"{pr_source_id}:comment:{comment.get('id')}", "comment", actor, occurred)
            )
        elif "approval" in item:
            approval = item["approval"]
            occurred = to_utc_iso(approval.get("date"))
            actor = (approval.get("user") or {}).get("account_id") or None
            events.append(
                _event(pr_source_id, f"{pr_source_id}:approval:{occurred}:{actor}", "approved", actor, occurred)
            )
        elif "update" in item:
            update = item["update"]
            state = update.get("state")
            occurred = to_utc_iso(update.get("date"))
            actor = (update.get("author") or {}).get("account_id") or None
            kind = {"MERGED": "merged", "DECLINED": "declined"}.get(state, "update")
            events.append(
                _event(pr_source_id, f"{pr_source_id}:update:{state}:{occurred}:{actor}", kind, actor, occurred)
            )
            if occurred and state == "MERGED":
                merged.append(occurred)
                closed.append(occurred)
            elif occurred and state == "DECLINED":
                closed.append(occurred)
    summary = ActivitySummary(
        merged_at=max(merged) if merged else None,
        closed_at=max(closed) if closed else None,
    )
    return events, summary


def review_comment_records(pr_source_id: str, comments: Sequence[Mapping[str, Any]]) -> List[Record]:
    """Review comments from /pullrequests/{n}/comments; ids match the comment change_event rows."""
    records: List[Record] = []
    for item in comments:
        if item.get("deleted"):
            continue
        inline = item.get("inline") or {}
        line = inline.get("to") or inline.get("from")
        parent = (item.get("parent") or {}).get("id")
        records.append(
            Record(
                "review_comment",
                {
                    "source": SOURCE,
                    "source_id": f"{pr_source_id}:comment:{item.get('id')}",
                    "change_request_id": pr_source_id,
                    "actor_account": (item.get("user") or {}).get("account_id") or None,
                    "created_at": to_utc_iso(item.get("created_on")),
                    "path": inline.get("path") or None,
                    "line": int(line) if line else None,
                    "parent_id": f"{pr_source_id}:comment:{parent}" if parent else None,
                    "resolved": 1 if item.get("resolution") else 0,
                },
            )
        )
    return records


def commit_link_records(
    repo_uuid: str, pr_source_id: str, commits: Sequence[Mapping[str, Any]]
) -> List[Record]:
    """Link commits to a pull request; carries only the link columns so author data is never overwritten."""
    return [
        Record(
            "vcs_commit",
            {
                "source": SOURCE,
                "source_id": f"{repo_uuid}:{commit['hash']}",
                "repository_id": repo_uuid,
                "sha": commit["hash"],
                "change_request_id": pr_source_id,
            },
        )
        for commit in commits
    ]
