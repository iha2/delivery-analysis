from __future__ import annotations

import base64
import random
import time
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Set

import httpx

BASE_URL = "https://api.bitbucket.org/2.0"
DEFAULT_BUDGET = 900
RETRY_STATUSES = {429, 502, 503, 504}


class BitbucketError(Exception):
    """A Bitbucket problem whose message is safe to print: it never contains the token."""


class AuthError(BitbucketError):
    pass


class ForbiddenError(BitbucketError):
    pass


class NotFoundError(BitbucketError):
    pass


class RateLimitedError(BitbucketError):
    pass


class BudgetExhausted(BitbucketError):
    pass


def auth_header(token: str) -> Dict[str, str]:
    token = token.strip()
    if ":" in token:
        return {"Authorization": "Basic " + base64.b64encode(token.encode("utf-8")).decode("ascii")}
    return {"Authorization": "Bearer " + token}


class BitbucketClient:
    """Read-only Bitbucket Cloud client: paging, back-off, and a per-run request budget."""

    def __init__(
        self,
        token: str,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Optional[Callable[[], float]] = None,
        budget: int = DEFAULT_BUDGET,
        max_retries: int = 4,
        base_url: str = BASE_URL,
    ) -> None:
        self._headers = {**auth_header(token), "Accept": "application/json"}
        self._http = httpx.Client(transport=transport, follow_redirects=True, timeout=30.0)
        self._sleep = sleep
        self._jitter = jitter or random.random
        self.budget = budget
        self.requests_made = 0
        self._max_retries = max_retries
        self._base = base_url.rstrip("/")

    @property
    def budget_left(self) -> int:
        return max(0, self.budget - self.requests_made)

    def _url(self, path_or_url: str) -> str:
        return path_or_url if path_or_url.startswith("http") else self._base + path_or_url

    def _wait(self, attempt: int, retry_after: Optional[str]) -> None:
        delay: float
        try:
            delay = min(float(retry_after), 120.0) if retry_after is not None else -1.0
        except ValueError:
            delay = -1.0
        if delay < 0:
            delay = min(60.0, 2.0 ** attempt) + self._jitter()
        self._sleep(delay)

    def get(self, path_or_url: str, params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        url = self._url(path_or_url)
        attempt = 0
        while True:
            if self.requests_made >= self.budget:
                raise BudgetExhausted(
                    "The request budget for this run is used up; the rest continues on the next sync."
                )
            self.requests_made += 1
            try:
                response = self._http.get(url, headers=self._headers, params=params)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise BitbucketError(f"Could not reach Bitbucket ({exc.__class__.__name__}).") from None
                attempt += 1
                self._wait(attempt, None)
                continue
            status = response.status_code
            if status == 200:
                if response.headers.get("X-RateLimit-NearLimit", "").lower() == "true":
                    self._sleep(2.0)
                return response.json()
            if status in RETRY_STATUSES:
                if attempt >= self._max_retries:
                    raise RateLimitedError(
                        "Bitbucket is rate limiting this token or is unavailable: rate limited, retry later."
                    )
                attempt += 1
                self._wait(attempt, response.headers.get("Retry-After"))
                continue
            if status == 401:
                raise AuthError(
                    "Bitbucket rejected the token (expired, revoked, or wrong). "
                    "Create a new API token and update BITBUCKET."
                )
            if status == 403:
                raise ForbiddenError(
                    "Bitbucket says the token lacks permission for this request. Check the "
                    "read:repository:bitbucket and read:pullrequest:bitbucket scopes and the workspace."
                )
            if status == 404:
                raise NotFoundError(
                    "Bitbucket did not find that resource. Check the name and that this token can see it."
                )
            raise BitbucketError(f"Bitbucket returned HTTP {status}.")

    def pages(
        self, path_or_url: str, params: Optional[Mapping[str, Any]] = None
    ) -> Iterator[Dict[str, Any]]:
        """Yield pages, following `next` verbatim. Stops if a `next` link repeats."""
        url: Optional[str] = self._url(path_or_url)
        query = params
        seen: Set[str] = set()
        while url:
            page = self.get(url, query)
            yield page
            query = None
            following = page.get("next")
            if not following or following in seen:
                break
            seen.add(following)
            url = following
