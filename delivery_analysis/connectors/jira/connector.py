from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set
from zoneinfo import ZoneInfo

from delivery_analysis.connectors.jira import normalize
from delivery_analysis.connectors.jira.client import (
    AuthError,
    BudgetExhausted,
    ForbiddenError,
    JiraClient,
    JiraError,
    NotFoundError,
)
from delivery_analysis.connectors.jira.fields import SEARCH_FIELDS, FieldCatalogue
from delivery_analysis.connectors.jira.jql import project_jql
from delivery_analysis.model.records import Batch, RawPayload, Record
from delivery_analysis.store.db import connect
from delivery_analysis.store import project_selection
from delivery_analysis.sync.runner import utc_now_iso
from delivery_analysis.teams.discover import window_start

SOURCE = "jira"
STATUS_FIELDS = ["status"]


def credential_problems(client: JiraClient) -> List[str]:
    """Plain-language problems with the Jira credentials; empty means they work."""
    if not client.email:
        return [
            "ATLASSIAN_EMAIL is not set. Put the Atlassian account email in .env as ATLASSIAN_EMAIL "
            "(or write ATLASSIAN as email:token)."
        ]
    try:
        me = client.myself()
    except AuthError as exc:
        return [str(exc)]
    except ForbiddenError:
        return ["The token is missing the read:jira-user permission."]
    except NotFoundError:
        return [
            "Jira did not find the site. Check JIRA_BASE_URL; a scoped token needs the "
            "https://api.atlassian.com/ex/jira/<cloudId> form."
        ]
    except JiraError as exc:
        return [str(exc)]
    if not isinstance(me, dict) or not me.get("accountId"):
        return [
            "Jira answered without an account. Check JIRA_BASE_URL; a scoped token needs the "
            "https://api.atlassian.com/ex/jira/<cloudId> form."
        ]
    return []


class JiraConnector:
    name = SOURCE

    def __init__(
        self,
        client: JiraClient,
        db_path: Path,
        *,
        window_days: int = 90,
        now: Callable[[], str] = utc_now_iso,
        max_pages: int = 500,
    ) -> None:
        self._client = client
        self._db_path = db_path
        self._window_days = window_days
        self._now = now
        self._max_pages = max_pages
        self._tz: Optional[ZoneInfo] = None
        self.unknown_statuses: Set[str] = set()

    # --- selection -------------------------------------------------------------------------

    def _selected(self) -> List[Dict[str, str]]:
        conn = connect(self._db_path)
        try:
            return project_selection.list_projects(conn, SOURCE)
        except sqlite3.OperationalError:
            return []  # database not migrated yet
        finally:
            conn.close()

    def scopes(self) -> List[str]:
        return sorted(row["project_key"] for row in self._selected())

    def _project(self, scope: str) -> Dict[str, str]:
        for row in self._selected():
            if row["project_key"] == scope:
                return row
        raise JiraError(f"Project {scope} is not selected. Run: delivery-analysis projects add jira:{scope}")

    def _status_map(self, scope: str) -> Dict[str, str]:
        conn = connect(self._db_path)
        try:
            return project_selection.status_map(conn, SOURCE, scope)
        finally:
            conn.close()

    # --- validation ------------------------------------------------------------------------

    def validate(self) -> List[str]:
        if not self._selected():
            return []
        return credential_problems(self._client)

    # --- sync ------------------------------------------------------------------------------

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
        project = self._project(scope)
        try:
            yield from self._sync_project(scope, project, since)
        except BudgetExhausted:
            return  # the run budget is used up; the next sync continues from the last committed page

    def _timezone(self) -> ZoneInfo:
        if self._tz is None:
            name = (self._client.myself() or {}).get("timeZone") or "UTC"
            try:
                self._tz = ZoneInfo(name)
            except Exception:
                self._tz = ZoneInfo("UTC")
        return self._tz

    def _precheck(self, scope: str, status_map: Dict[str, str]) -> None:
        names = {
            status["name"]
            for issue_type in self._client.project_statuses(scope)
            for status in issue_type.get("statuses", [])
        }
        missing = sorted(name for name in names if name not in status_map)
        if missing:
            listed = ", ".join(repr(name) for name in missing)
            raise JiraError(
                f"Project {scope} has statuses with no mapping: {listed}. Map each with: "
                f'delivery-analysis projects map jira:{scope} "<status>" '
                "<todo|in_progress|in_review|done|dropped>"
            )

    def _histories(self, issue_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        by_issue: Dict[str, List[Dict[str, Any]]] = {}
        for page in self._client.changelog_pages(issue_ids, STATUS_FIELDS):
            for entry in page.get("issueChangeLogs", []):
                by_issue.setdefault(str(entry["issueId"]), []).extend(entry.get("changeHistories", []))
        return by_issue

    def _sync_project(self, scope: str, project: Dict[str, str], since: Optional[str]) -> Iterator[Batch]:
        status_map = self._status_map(scope)
        self._precheck(scope, status_map)
        catalogue = FieldCatalogue(self._client.fields())
        tz = self._timezone()
        started = self._now()
        cutoff = since or window_start(started, self._window_days)
        jql = project_jql(scope, cutoff, tz)
        token: Optional[str] = None
        seen: Set[str] = set()
        pages = 0
        while True:
            if pages >= self._max_pages:
                raise JiraError(f"Jira returned more than {self._max_pages} pages for {scope}; stopping.")
            page = self._client.search(jql, SEARCH_FIELDS, token)
            issues = page.get("issues") or []
            if not issues:
                return
            pages += 1
            histories = self._histories([str(issue["id"]) for issue in issues])
            records: List[Record] = []
            raws: List[RawPayload] = []
            updated: List[str] = []
            for issue in issues:
                result = normalize.issue_records(
                    issue, project, status_map, catalogue, histories.get(str(issue["id"]), [])
                )
                records.extend(result.records)
                raws.append(result.raw)
                self.unknown_statuses.update(result.unknown_statuses)
                if result.updated:
                    updated.append(result.updated)
            yield Batch(records, raws, cursor=max(updated) if updated else None)
            token = page.get("nextPageToken")
            if not token or token in seen:
                return
            seen.add(token)
