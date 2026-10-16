from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, Iterator, Mapping, Optional, Set

import httpx

from delivery_analysis import __version__

API_BASE = "https://api.anthropic.com"
REPORT_PATH = "/v1/organizations/usage_report/claude_code"
ADMIN_KEY_PREFIX = "sk-ant-admin"
RETRY_STATUSES = {429, 500, 502, 503, 504, 529}


class ClaudeUsageError(Exception):
    """A Claude usage problem whose message is safe to print: it never contains the key."""


class AuthError(ClaudeUsageError):
    pass


class ForbiddenError(ClaudeUsageError):
    pass


class NotFoundError(ClaudeUsageError):
    pass


class RateLimitedError(ClaudeUsageError):
    pass


def usage_key(environ: Mapping[str, str]) -> str:
    """ANTHROPIC_ADMIN if set, otherwise ANTHROPIC (stripped); empty when neither is set."""
    for name in ("ANTHROPIC_ADMIN", "ANTHROPIC"):
        value = (environ.get(name) or "").strip()
        if value:
            return value
    return ""


class ClaudeCodeClient:
    """Read-only Claude Code Analytics client: one request per second, back-off, cursor paging."""

    def __init__(
        self,
        key: str,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Optional[Callable[[], float]] = None,
        max_retries: int = 4,
        min_interval: float = 1.0,
        base_url: str = API_BASE,
    ) -> None:
        self._headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "User-Agent": f"delivery-analysis/{__version__}",
            "Accept": "application/json",
        }
        self._http = httpx.Client(transport=transport, timeout=60.0)
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter or random.random
        self._max_retries = max_retries
        self._min_interval = min_interval
        self._url = base_url.rstrip("/") + REPORT_PATH
        self._last: Optional[float] = None
        self.requests_made = 0

    def __repr__(self) -> str:
        return "ClaudeCodeClient(***)"

    def _pace(self) -> None:
        if self._last is not None:
            elapsed = self._clock() - self._last
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last = self._clock()

    def _wait(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = -1.0
        if retry_after is not None:
            try:
                delay = min(float(retry_after), 120.0)
            except ValueError:
                delay = -1.0
        if delay < 0:
            delay = min(60.0, 2.0 ** (attempt + 1)) * (0.7 + 0.6 * self._jitter())
        self._sleep(delay)

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            self._pace()
            self.requests_made += 1
            try:
                response = self._http.get(self._url, params=params, headers=self._headers)
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise ClaudeUsageError(
                        f"Could not reach the Claude usage API ({exc.__class__.__name__})."
                    ) from None
                self._wait(attempt, None)
                continue
            status = response.status_code
            if status == 200:
                try:
                    body = response.json()
                except ValueError:
                    raise ClaudeUsageError("The Claude usage API returned an unreadable response.") from None
                if not isinstance(body, dict):
                    raise ClaudeUsageError("The Claude usage API returned an unexpected response shape.")
                return body
            if status == 401:
                raise AuthError(
                    "The Claude usage key was rejected (HTTP 401). Check ANTHROPIC_ADMIN or ANTHROPIC; "
                    "an expired or revoked Admin key gives this."
                )
            if status == 403:
                raise ForbiddenError(
                    "The Claude usage API refused the key (HTTP 403). It needs an organization Admin key "
                    "(sk-ant-admin...) set in ANTHROPIC_ADMIN."
                )
            if status == 404:
                raise NotFoundError(
                    "The Claude Code usage report was not found (HTTP 404). The organization may be a Claude "
                    "Enterprise org, which needs the Enterprise Analytics API (not supported yet)."
                )
            if status in RETRY_STATUSES:
                if attempt < self._max_retries:
                    self._wait(attempt, response.headers.get("retry-after"))
                    continue
                raise RateLimitedError(f"The Claude usage API kept returning HTTP {status}; retry later.")
            raise ClaudeUsageError(f"The Claude usage API returned HTTP {status}.")
        raise RateLimitedError("The Claude usage API did not answer; retry later.")

    def day_pages(self, day: str, limit: int = 1000) -> Iterator[Dict[str, Any]]:
        """Every page for one UTC day, following `next_page` with the same query each time."""
        token: Optional[str] = None
        seen: Set[str] = set()
        while True:
            params: Dict[str, Any] = {"starting_at": day, "limit": limit}
            if token:
                params["page"] = token
            body = self._get(params)
            yield body
            if not body.get("has_more"):
                return
            token = body.get("next_page")
            if not token or token in seen:
                raise ClaudeUsageError(
                    f"The Claude usage API returned a missing or repeated page cursor for {day}; stopping that day."
                )
            seen.add(token)

    def probe(self, day: str) -> None:
        self._get({"starting_at": day, "limit": 1})
