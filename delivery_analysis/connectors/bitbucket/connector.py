from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set
from urllib.parse import quote

from delivery_analysis.connectors.bitbucket import normalize
from delivery_analysis.connectors.bitbucket.client import (
    AuthError,
    BitbucketClient,
    BitbucketError,
    BudgetExhausted,
    ForbiddenError,
    NotFoundError,
)
from delivery_analysis.core.time_utils import to_utc_iso
from delivery_analysis.model.records import Batch, RawPayload, Record
from delivery_analysis.store.db import connect
from delivery_analysis.store.repo_selection import list_selected
from delivery_analysis.sync.runner import utc_now_iso
from delivery_analysis.teams.discover import window_start

SOURCE = "bitbucket"
PR_STATES = ["OPEN", "MERGED", "DECLINED", "SUPERSEDED"]
COMMIT_FIELDS = (
    "next,values.hash,values.date,values.author.raw,values.author.user.account_id,values.parents.hash"
)
PR_FIELDS = (
    "next,values.id,values.title,values.state,values.author.account_id,values.source.branch.name,"
    "values.created_on,values.updated_on,values.closed_by.account_id,values.merge_commit.hash,"
    "values.participants.role,values.participants.approved,values.participants.user.account_id"
)


class BitbucketConnector:
    name = SOURCE

    def __init__(
        self,
        client: BitbucketClient,
        db_path: Path,
        *,
        workspace: str = "",
        window_days: int = 90,
        now: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._client = client
        self._db_path = db_path
        self._workspace = workspace
        self._window_days = window_days
        self._now = now

    # --- selection -------------------------------------------------------------------------

    def _selected(self) -> List[Dict[str, str]]:
        conn = connect(self._db_path)
        try:
            return list_selected(conn, SOURCE)
        finally:
            conn.close()

    def scopes(self) -> List[str]:
        return sorted(row["repository_id"] for row in self._selected())

    def _selection_for(self, scope: str) -> Dict[str, str]:
        for row in self._selected():
            if row["repository_id"] == scope:
                return row
        raise BitbucketError(
            f"Repository {scope} is not selected. Run: delivery-analysis repos add bitbucket:<repo>"
        )

    # --- validation ------------------------------------------------------------------------

    def validate(self) -> List[str]:
        selected = self._selected()
        workspace = selected[0]["workspace"] if selected else self._workspace
        if not workspace:
            return []
        try:
            self._client.get(f"/repositories/{workspace}", {"pagelen": 1, "fields": "size"})
        except AuthError as exc:
            return [str(exc)]
        except ForbiddenError:
            return [
                "The token is missing the read:repository:bitbucket permission, or is limited to "
                "another workspace."
            ]
        except NotFoundError:
            return [f"Workspace {workspace!r} was not found or is not visible to this token."]
        except BitbucketError as exc:
            return [str(exc)]
        if selected:
            first = quote(selected[0]["repository_id"], safe="")
            try:
                self._client.get(
                    f"/repositories/{workspace}/{first}/pullrequests", {"pagelen": 1, "fields": "size"}
                )
            except ForbiddenError:
                return ["The token is missing the read:pullrequest:bitbucket permission."]
            except BitbucketError as exc:
                return [str(exc)]
        return []

    # --- sync ------------------------------------------------------------------------------

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
        selection = self._selection_for(scope)
        workspace = selection["workspace"]
        repo_path = f"/repositories/{workspace}/{quote(scope, safe='')}"
        started = self._now()
        cutoff = since or window_start(started, self._window_days)

        data = self._client.get(repo_path, {"fields": "uuid,slug,full_name,mainbranch.name"})
        record, raw = normalize.repository_record(workspace, data)
        yield Batch([record], [raw])

        yield from self._commits(scope, repo_path, cutoff)
        detailed = self._detailed_ids(scope)
        yield from self._pull_requests(scope, repo_path, cutoff, detailed)
        yield Batch([], cursor=started)
        yield from self._detail(scope, repo_path)

    def _commits(self, uuid: str, repo_path: str, cutoff: str) -> Iterator[Batch]:
        params = {"pagelen": 100, "fields": COMMIT_FIELDS}
        for page in self._client.pages(f"{repo_path}/commits", params):
            values = page.get("values", [])
            records: List[Record] = []
            raws: List[RawPayload] = []
            all_old = bool(values)
            for item in values:
                committed = to_utc_iso(item.get("date"))
                if committed is not None and committed < cutoff:
                    continue
                all_old = False
                if committed is None:
                    continue
                recs, raw = normalize.commit_records(uuid, item)
                records.extend(recs)
                raws.append(raw)
            if records:
                yield Batch(records, raws)
            if all_old:
                break

    def _pull_requests(
        self, uuid: str, repo_path: str, cutoff: str, detailed: Set[str]
    ) -> Iterator[Batch]:
        params: Dict[str, Any] = {
            "state": PR_STATES, "sort": "-updated_on", "pagelen": 100, "fields": PR_FIELDS,
        }
        for page in self._client.pages(f"{repo_path}/pullrequests", params):
            records: List[Record] = []
            raws: List[RawPayload] = []
            stop = False
            for item in page.get("values", []):
                updated = to_utc_iso(item.get("updated_on"))
                if updated is not None and updated < cutoff:
                    stop = True
                    break
                source_id = f"{uuid}#{item['id']}"
                recs, raw = normalize.pull_request_records(
                    uuid, item, include_times=source_id not in detailed
                )
                records.extend(recs)
                raws.append(raw)
            if records:
                yield Batch(records, raws)
            if stop:
                break

    def _detailed_ids(self, uuid: str) -> Set[str]:
        conn = connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT record_id FROM property WHERE record_kind = 'change_request' "
                "AND name = 'detail_updated_on' AND record_id LIKE ?",
                (uuid + "#%",),
            ).fetchall()
            return {row["record_id"] for row in rows}
        finally:
            conn.close()

    def _detail(self, uuid: str, repo_path: str) -> Iterator[Batch]:
        return iter(())
