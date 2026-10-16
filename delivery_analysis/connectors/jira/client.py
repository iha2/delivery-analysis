from __future__ import annotations

import base64
import random
import time
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote

import httpx

DEFAULT_BASE_URL = "https://keyjira.atlassian.net"
API_PREFIX = "/rest/api/3"
DEFAULT_BUDGET = 600
PAGE_SIZE = 100
MAX_HISTORY_PAGES = 200
RETRY_STATUSES = {429, 502, 503, 504}


class JiraError(Exception):
    """A Jira problem whose message is safe to print: it never contains the token or the email."""


class AuthError(JiraError):
    pass


class ForbiddenError(JiraError):
    pass


class NotFoundError(JiraError):
    pass


class RateLimitedError(JiraError):
    pass


class BudgetExhausted(JiraError):
    pass


def jira_credentials(environ: Mapping[str, str]) -> Tuple[str, str]:
    """(email, token). A colon inside ATLASSIAN means `email:token` and wins over ATLASSIAN_EMAIL."""
    token = (environ.get("ATLASSIAN") or "").strip()
    email = (environ.get("ATLASSIAN_EMAIL") or "").strip()
    if ":" in token:
        embedded, _, token = token.partition(":")
        email = embedded.strip() or email
    return email, token.strip()


def base_url_from(environ: Mapping[str, str]) -> str:
    return (environ.get("JIRA_BASE_URL") or "").strip() or DEFAULT_BASE_URL


class JiraClient:
    """Read-only Jira Cloud client: Basic auth, back-off, a per-run request budget, token paging."""

    def __init__(
        self,
        email: str,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Optional[Callable[[], float]] = None,
        budget: int = DEFAULT_BUDGET,
        max_retries: int = 4,
    ) -> None:
        self.email = email
        raw = base64.b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        self._headers = {"Authorization": "Basic " + raw, "Accept": "application/json"}
        self._http = httpx.Client(transport=transport, timeout=60.0)
        self._sleep = sleep
        self._jitter = jitter or random.random
        self.budget = budget
        self.requests_made = 0
        self._max_retries = max_retries
        self._base = base_url.rstrip("/") + API_PREFIX

    @property
    def budget_left(self) -> int:
        return max(0, self.budget - self.requests_made)

    def _wait(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = -1.0
        if retry_after is not None:
            try:
                delay = min(float(retry_after), 120.0)
            except ValueError:
                delay = -1.0
        if delay < 0:
            delay = min(60.0, 2.0 ** attempt) * (0.7 + 0.6 * self._jitter())
        self._sleep(delay)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise JiraError(
                "Jira returned an empty or unreadable response. A scoped token must use "
                "https://api.atlassian.com/ex/jira/<cloudId> as JIRA_BASE_URL."
            ) from None

    @staticmethod
    def _message(response: httpx.Response) -> str:
        try:
            data = response.json()
        except ValueError:
            return ""
        if isinstance(data, dict):
            messages = data.get("errorMessages")
            if isinstance(messages, list) and messages:
                return "; ".join(str(m) for m in messages)[:300]
        return ""

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        body: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        url = self._base + path
        attempt = 0
        while True:
            if self.requests_made >= self.budget:
                raise BudgetExhausted(
                    "The request budget for this run is used up; the rest continues on the next sync."
                )
            self.requests_made += 1
            try:
                response = self._http.request(method, url, headers=self._headers, params=params, json=body)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise JiraError(f"Could not reach Jira ({exc.__class__.__name__}).") from None
                attempt += 1
                self._wait(attempt, None)
                continue
            status = response.status_code
            if status == 200:
                if response.headers.get("X-RateLimit-NearLimit", "").lower() == "true":
                    self._sleep(2.0)
                return self._parse(response)
            if status == 429 and "quota" in response.headers.get("RateLimit-Reason", "").lower():
                reset = response.headers.get("X-RateLimit-Reset")
                raise RateLimitedError(
                    "Jira's request quota is used up"
                    + (f" and resets at {reset}" if reset else "")
                    + ": rate limited, retry later."
                )
            if status in RETRY_STATUSES:
                if attempt >= self._max_retries:
                    raise RateLimitedError(
                        "Jira is rate limiting this token or is unavailable: rate limited, retry later."
                    )
                attempt += 1
                self._wait(attempt, response.headers.get("Retry-After"))
                continue
            if status == 401:
                raise AuthError(
                    "Jira rejected the email or token (bad, expired, or revoked). "
                    "Create a new API token, update ATLASSIAN, and check ATLASSIAN_EMAIL."
                )
            if status == 403:
                raise ForbiddenError(
                    "Jira says the token lacks permission for this request. Check the read:jira-work "
                    "and read:jira-user scopes and that the account can browse the project."
                )
            if status == 404:
                raise NotFoundError(
                    "Jira did not find that resource. Check the name and that this account can see it."
                )
            if status == 400:
                detail = self._message(response)
                raise JiraError("Jira rejected the request (HTTP 400)" + (f": {detail}" if detail else "."))
            raise JiraError(f"Jira returned HTTP {status}.")

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: Mapping[str, Any]) -> Any:
        return self._request("POST", path, body=body)

    def myself(self) -> Dict[str, Any]:
        return self.get("/myself")

    def fields(self) -> Any:
        return self.get("/field")

    def project(self, key: str) -> Dict[str, Any]:
        return self.get(f"/project/{quote(key, safe='')}")

    def project_statuses(self, key: str) -> Any:
        return self.get(f"/project/{quote(key, safe='')}/statuses")

    def search(self, jql: str, fields: Sequence[str], page_token: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"jql": jql, "maxResults": PAGE_SIZE, "fields": list(fields)}
        if page_token:
            body["nextPageToken"] = page_token
        return self.post("/search/jql", body)

    def changelog_pages(
        self, issue_ids: Sequence[str], field_ids: Sequence[str]
    ) -> Iterator[Dict[str, Any]]:
        """Yield bulkfetch pages. The next page needs the same body plus `nextPageToken`."""
        token: Optional[str] = None
        seen: Set[str] = set()
        for _ in range(MAX_HISTORY_PAGES):
            body: Dict[str, Any] = {"issueIdsOrKeys": list(issue_ids), "fieldIds": list(field_ids)}
            if token:
                body["nextPageToken"] = token
            page = self.post("/changelog/bulkfetch", body)
            yield page
            token = page.get("nextPageToken")
            if not token or token in seen:
                return
            seen.add(token)
        raise JiraError("Jira kept returning more change history pages than expected; stopping.")
