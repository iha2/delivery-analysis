"""A fake Bitbucket Cloud API served through httpx.MockTransport, plus fixture builders.

Only made-up people and fake tokens are used here.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote

import httpx


def recent(days_ago: float = 0.0) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.replace(microsecond=0).isoformat()  # ends with +00:00


def commit(hash, raw, when, account=None, parents=1):
    author: Dict[str, Any] = {"raw": raw}
    if account:
        author["user"] = {"account_id": account}
    return {"hash": hash, "date": when, "author": author, "parents": [{"hash": f"p{i}"} for i in range(parents)]}


def pr(pr_id, state, updated, created=None, author="acc-ann", title="Change", branch="feature/x"):
    return {
        "id": pr_id,
        "title": title,
        "state": state,
        "author": {"account_id": author},
        "source": {"branch": {"name": branch}},
        "created_on": created or updated,
        "updated_on": updated,
        "closed_by": {"account_id": "acc-ann"},
        "merge_commit": {"hash": "abc123def456"},
    }


def update(state, date, account="acc-ann"):
    return {"update": {"state": state, "date": date, "author": {"account_id": account}}, "pull_request": {"id": 0}}


def comment(comment_id, date, account="acc-bob", deleted=False):
    return {
        "comment": {"id": comment_id, "created_on": date, "deleted": deleted, "user": {"account_id": account}},
        "pull_request": {"id": 0},
    }


def approval(date, account="acc-bob"):
    return {"approval": {"date": date, "user": {"account_id": account}}, "pull_request": {"id": 0}}


def api_comment(comment_id, date, account="acc-bob", deleted=False, path=None, to=None, from_=None,
                parent=None, resolution=None):
    """A value from /pullrequests/{n}/comments (the activity payload leaves inline and resolution empty)."""
    return {
        "id": comment_id,
        "created_on": date,
        "deleted": deleted,
        "user": {"account_id": account},
        "inline": {"path": path, "to": to, "from": from_} if path else None,
        "parent": {"id": parent} if parent else None,
        "resolution": resolution,
    }


class FakeBitbucket:
    BASE = "https://api.bitbucket.org/2.0"

    def __init__(self, token: str = "tok-bb-1", workspace: str = "keyhealthtech"):
        self.token = token
        self.workspace = workspace
        self.repos: Dict[str, Dict[str, Any]] = {}
        self.requests: List[Any] = []
        self.errors: Dict[str, int] = {}
        self.pr_scope_missing = False

    def add_repo(self, slug, uuid, commits=None, prs=None, activity=None, pr_commits=None, diffstat=None,
                 comments=None):
        self.repos[slug] = {
            "uuid": uuid,
            "slug": slug,
            "commits": commits or [],
            "prs": prs or [],
            "activity": activity or {},
            "pr_commits": pr_commits or {},
            "diffstat": diffstat or {},
            "comments": comments or {},
        }

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def count(self, fragment: str) -> int:
        return sum(1 for path, _ in self.requests if fragment in path)

    def _find(self, ident: str) -> Optional[Dict[str, Any]]:
        for repo in self.repos.values():
            if ident in (repo["slug"], repo["uuid"]):
                return repo
        return None

    def _page(self, request: httpx.Request, items: List[Any]) -> httpx.Response:
        params = parse_qs(request.url.query.decode("ascii"))
        pagelen = int(params.get("pagelen", ["10"])[0])
        page = int(params.get("page", ["1"])[0])
        start = (page - 1) * pagelen
        body: Dict[str, Any] = {"pagelen": pagelen, "values": items[start:start + pagelen]}
        if start + pagelen < len(items):
            body["next"] = str(request.url.copy_merge_params({"page": page + 1}))
        return httpx.Response(200, json=body)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = unquote(request.url.path)
        params = parse_qs(request.url.query.decode("ascii"))
        self.requests.append((path, params))
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        for suffix, status in self.errors.items():
            if path.endswith(suffix):
                return httpx.Response(status, json={"error": "fake"})
        parts = [part for part in path.split("/") if part]
        if parts[:2] != ["2.0", "repositories"] or len(parts) < 3 or parts[2] != self.workspace:
            return httpx.Response(404, json={})
        if len(parts) == 3:
            values = [{"slug": r["slug"], "uuid": r["uuid"]} for r in self.repos.values()]
            return httpx.Response(200, json={"size": len(values), "values": values})
        repo = self._find(parts[3])
        if repo is None:
            return httpx.Response(404, json={})
        rest = parts[4:]
        if not rest:
            return httpx.Response(
                200,
                json={
                    "uuid": repo["uuid"],
                    "slug": repo["slug"],
                    "full_name": f"{self.workspace}/{repo['slug']}",
                    "workspace": {"slug": self.workspace},
                    "mainbranch": {"name": "main"},
                },
            )
        if rest == ["commits"]:
            return self._page(request, repo["commits"])
        if rest[0] == "pullrequests":
            if self.pr_scope_missing:
                return httpx.Response(403, json={})
            if len(rest) == 1:
                if int(params.get("pagelen", ["10"])[0]) > 50:
                    return httpx.Response(400, json={"error": {"message": "Invalid pagelen"}})
                states = params.get("state", ["OPEN"])
                items = [p for p in repo["prs"] if p["state"] in states]
                items.sort(key=lambda p: p["updated_on"], reverse=True)
                return self._page(request, items)
            if len(rest) == 3:
                if rest[2] == "activity" and int(params.get("pagelen", ["10"])[0]) > 50:
                    return httpx.Response(400, json={"error": {"message": "Invalid pagelen"}})
                source = {
                    "activity": repo["activity"],
                    "commits": repo["pr_commits"],
                    "diffstat": repo["diffstat"],
                    "comments": repo["comments"],
                }.get(rest[2])
                if source is not None:
                    return self._page(request, source.get(int(rest[1]), []))
        return httpx.Response(404, json={})
