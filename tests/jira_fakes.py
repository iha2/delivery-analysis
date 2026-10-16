"""A fake Jira Cloud API served through httpx.MockTransport, plus fixture builders.

Only made-up people, made-up keys and fake tokens are used here.
"""
import base64
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx

from delivery_analysis.core.time_utils import to_utc_iso

ISO_Z = "%Y-%m-%dT%H:%M:%SZ"

DEFAULT_FIELDS = [
    {"id": "summary", "name": "Summary", "custom": False, "schema": {"type": "string"}},
    {"id": "labels", "name": "Labels", "custom": False, "schema": {"type": "array"}},
    {"id": "fixVersions", "name": "Fix versions", "custom": False, "schema": {"type": "array"}},
    {"id": "priority", "name": "Priority", "custom": False, "schema": {"type": "priority"}},
    {"id": "customfield_10004", "name": "Story Points", "custom": True, "schema": {"type": "number"}},
    {"id": "customfield_11168", "name": "Story point estimate", "custom": True, "schema": {"type": "number"}},
    {"id": "customfield_11104", "name": "Story point estimate", "custom": True, "schema": {"type": "number"}},
    {"id": "customfield_10006", "name": "Sprint", "custom": True, "schema": {"type": "array"}},
]


def epoch_ms(iso: str) -> int:
    """Epoch milliseconds for a UTC `YYYY-MM-DDTHH:MM:SSZ` string (the form bulkfetch uses)."""
    moment = datetime.strptime(iso, ISO_Z).replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


def jira_ts(days_ago: float = 0.0) -> str:
    """A recent timestamp in the `...000+0000` form issues use (no colon in the offset)."""
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def user(account, name="Ann Example", email=None, kind="atlassian", active=True):
    body: Dict[str, Any] = {"accountId": account, "displayName": name, "accountType": kind, "active": active}
    if email:
        body["emailAddress"] = email
    return body


def issue(
    issue_id,
    key,
    *,
    project="MD",
    type="Story",
    subtask=False,
    status="To Do",
    status_id="1",
    assignee=None,
    reporter=None,
    points=None,
    updated="2026-10-14T10:00:00.000-0700",
    created="2026-10-01T09:00:00.000-0700",
    sprint=None,
    labels=None,
    parent=None,
    links=None,
    points_field="customfield_10004",
    extra=None,
):
    fields: Dict[str, Any] = {
        "summary": f"Summary of {key}",
        "project": {"key": project},
        "issuetype": {"name": type, "subtask": subtask},
        "status": {"name": status, "id": status_id, "statusCategory": {"key": "new"}},
        "assignee": assignee,
        "reporter": reporter,
        "creator": reporter,
        "created": created,
        "updated": updated,
        "labels": labels or [],
        "priority": {"name": "Medium"},
        points_field: points,
        "customfield_10006": sprint,
        "description": {"type": "doc", "version": 1, "content": []},
        "parent": parent,
        "issuelinks": links or [],
    }
    fields.update(extra or {})
    return {"id": str(issue_id), "key": key, "fields": fields}


def history(history_id, created_iso, from_status, to_status, author="acc-ann", field_id="status"):
    """A bulkfetch history: `created` is epoch milliseconds, like the live API."""
    return {
        "id": str(history_id),
        "author": {"accountId": author} if author else None,
        "created": epoch_ms(created_iso),
        "items": [
            {
                "field": field_id,
                "fieldtype": "jira",
                "fieldId": field_id,
                "from": "1",
                "fromString": from_status,
                "to": "2",
                "toString": to_status,
            }
        ],
    }


class FakeJira:
    PREFIX = "/rest/api/3"

    def __init__(
        self,
        email: str = "me@corp.example",
        token: str = "tok-jira-1",
        tz: str = "America/Los_Angeles",
        page_size: int = 100,
        history_page: int = 1000,
    ):
        raw = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        self.expected_auth = "Basic " + raw
        self.tz = tz
        self.page_size = page_size
        self.history_page = history_page
        self.projects: Dict[str, Dict[str, Any]] = {}
        self.issues: List[Dict[str, Any]] = []
        self.histories: Dict[str, List[Dict[str, Any]]] = {}
        self.fields: List[Dict[str, Any]] = list(DEFAULT_FIELDS)
        self.myself_body: Optional[Dict[str, Any]] = {"accountId": "acc-me", "timeZone": tz}
        self.myself_empty = False
        self.requests: List[Any] = []
        self.jqls: List[str] = []
        self.errors: Dict[str, int] = {}
        self.error_headers: Dict[str, str] = {}

    def add_project(self, key, project_id, name, statuses):
        self.projects[key] = {"id": str(project_id), "key": key, "name": name, "statuses": list(statuses)}

    def add_issue(self, issue_dict, histories=None):
        self.issues.append(issue_dict)
        self.histories[issue_dict["id"]] = list(histories or [])

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def count(self, fragment: str) -> int:
        return sum(1 for _, path, _ in self.requests if fragment in path)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, path, body))
        if request.headers.get("Authorization") != self.expected_auth:
            return httpx.Response(401, json={"message": "unauthorized"})
        for suffix, status in self.errors.items():
            if path.endswith(suffix):
                return httpx.Response(status, json={"errorMessages": ["fake"]}, headers=self.error_headers)
        if not path.startswith(self.PREFIX):
            return httpx.Response(404, json={})
        rest = path[len(self.PREFIX):]
        if request.method == "GET":
            return self._get(rest)
        if rest == "/search/jql":
            return self._search(body)
        if rest == "/changelog/bulkfetch":
            return self._bulkfetch(body)
        return httpx.Response(404, json={})

    def _get(self, rest: str) -> httpx.Response:
        if rest == "/myself":
            if self.myself_empty:
                return httpx.Response(200, content=b"")
            return httpx.Response(200, json=self.myself_body)
        if rest == "/field":
            return httpx.Response(200, json=self.fields)
        parts = [part for part in rest.split("/") if part]
        if len(parts) >= 2 and parts[0] == "project":
            project = self.projects.get(parts[1])
            if project is None:
                return httpx.Response(404, json={"errorMessages": ["No project could be found."]})
            if len(parts) == 2:
                return httpx.Response(
                    200, json={"id": project["id"], "key": project["key"], "name": project["name"]}
                )
            if parts[2] == "statuses":
                return httpx.Response(
                    200,
                    json=[{"name": "Story", "statuses": [{"name": name} for name in project["statuses"]]}],
                )
        return httpx.Response(404, json={})

    def _search(self, body: Dict[str, Any]) -> httpx.Response:
        jql = body["jql"]
        self.jqls.append(jql)
        match = re.search(r'project = "([A-Za-z0-9_]+)"', jql)
        key = match.group(1) if match else None
        pool = [i for i in self.issues if i["fields"]["project"]["key"] == key]
        lower = re.search(r'updated >= "(\d{4}/\d{2}/\d{2} \d{2}:\d{2})"', jql)
        if lower:
            floor = (
                datetime.strptime(lower.group(1), "%Y/%m/%d %H:%M")
                .replace(tzinfo=ZoneInfo(self.tz))
                .astimezone(timezone.utc)
                .strftime(ISO_Z)
            )
            pool = [i for i in pool if to_utc_iso(i["fields"]["updated"]) >= floor]
        pool.sort(key=lambda i: (to_utc_iso(i["fields"]["updated"]), i["key"]))
        size = min(int(body.get("maxResults", 50)), self.page_size)
        token = body.get("nextPageToken")
        start = int(token[1:]) if token else 0
        out: Dict[str, Any] = {"issues": pool[start:start + size], "isLast": start + size >= len(pool)}
        if start + size < len(pool):
            out["nextPageToken"] = f"t{start + size}"
        return httpx.Response(200, json=out)

    def _bulkfetch(self, body: Dict[str, Any]) -> httpx.Response:
        wanted = set(body.get("fieldIds") or [])
        flat = []
        for issue_id in [str(x) for x in body["issueIdsOrKeys"]]:
            for item in self.histories.get(issue_id, []):
                items = [it for it in item["items"] if not wanted or it["fieldId"] in wanted]
                if items:
                    flat.append((issue_id, dict(item, items=items)))
        token = body.get("nextPageToken")
        start = int(token[1:]) if token else 0
        chunk = flat[start:start + self.history_page]
        logs: List[Dict[str, Any]] = []
        for issue_id, item in chunk:
            if logs and logs[-1]["issueId"] == issue_id:
                logs[-1]["changeHistories"].append(item)
            else:
                logs.append({"issueId": issue_id, "changeHistories": [item]})
        out: Dict[str, Any] = {"issueChangeLogs": logs}
        if start + len(chunk) < len(flat):
            out["nextPageToken"] = f"h{start + len(chunk)}"
        return httpx.Response(200, json=out)
