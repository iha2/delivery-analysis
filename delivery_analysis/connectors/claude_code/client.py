from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Set

import httpx

from delivery_analysis import __version__

API_BASE = "https://api.anthropic.com"
REPORT_PATH = "/v1/organizations/usage_report/claude_code"
COST_PATH = "/v1/organizations/analytics/user_cost_report"
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


class StalePageError(ClaudeUsageError):
    """HTTP 410: the page cursor expired, so the range has to restart from its first page."""


@dataclass(frozen=True)
class _Report:
    path: str
    unauthorized: str
    forbidden: str
    not_found: str


USAGE_REPORT = _Report(
    REPORT_PATH,
    "The Claude usage key was rejected (HTTP 401). Check ANTHROPIC_ADMIN or ANTHROPIC; "
    "an expired or revoked Admin key gives this.",
    "The Claude usage API refused the key (HTTP 403). It needs an organization Admin key "
    "(sk-ant-admin...) set in ANTHROPIC_ADMIN.",
    "The Claude Code usage report was not found (HTTP 404). The organization may be a Claude "
    "Enterprise org, which needs the Enterprise Analytics API (not supported yet).",
)
COST_REPORT = _Report(
    COST_PATH,
    "The Claude analytics key was rejected (HTTP 401). Check ANTHROPIC_ADMIN or ANTHROPIC; "
    "an expired or revoked key gives this.",
    "The Claude analytics API refused the key (HTTP 403). The key needs the read:analytics scope.",
    "The Claude user cost report was not found (HTTP 404). It is only available to Claude Enterprise "
    "organizations.",
)


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
        self._base = base_url.rstrip("/")
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

    def _get(self, params: Dict[str, Any], report: _Report = USAGE_REPORT) -> Dict[str, Any]:
        url = self._base + report.path
        for attempt in range(self._max_retries + 1):
            self._pace()
            self.requests_made += 1
            try:
                response = self._http.get(url, params=params, headers=self._headers)
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
                raise AuthError(report.unauthorized)
            if status == 403:
                raise ForbiddenError(report.forbidden)
            if status == 404:
                raise NotFoundError(report.not_found)
            if status == 410:
                raise StalePageError("The Claude usage API page cursor expired (HTTP 410).")
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

    def cost_pages(self, starting_day: str, ending_day: str, limit: int = 1000) -> Iterator[Dict[str, Any]]:
        """Every page of the per-user cost report for [starting_day, ending_day) in daily buckets.

        An expired cursor (HTTP 410) restarts the range from its first page once; pages are yielded
        only after a whole attempt succeeded, so a restart never duplicates rows.
        """
        label = f"{starting_day}..{ending_day}"
        for attempt in range(2):
            try:
                pages = list(self._cost_attempt(starting_day, ending_day, limit, label))
            except StalePageError:
                if attempt == 0:
                    continue
                raise ClaudeUsageError(
                    f"The Claude usage API page cursor kept expiring for {label}; try again later."
                ) from None
            yield from pages
            return

    def _cost_attempt(self, starting_day: str, ending_day: str, limit: int, label: str) -> Iterator[Dict[str, Any]]:
        token: Optional[str] = None
        seen: Set[str] = set()
        while True:
            params: Dict[str, Any] = {
                "starting_at": f"{starting_day}T00:00:00Z",
                "ending_at": f"{ending_day}T00:00:00Z",
                "bucket_width": "1d",
                "group_by[]": ["model"],
                "products[]": ["claude_code"],
                "limit": limit,
            }
            if token:
                params["page"] = token
            body = self._get(params, COST_REPORT)
            yield body
            if not body.get("has_more"):
                return
            token = body.get("next_page")
            if not token or token in seen:
                raise ClaudeUsageError(
                    f"The Claude usage API returned a missing or repeated page cursor for {label}; stopping that range."
                )
            seen.add(token)

    def probe_cost(self, today: Optional[date] = None) -> None:
        """One row, yesterday to today (UTC): proves the key, scope and plan."""
        today = today or datetime.now(timezone.utc).date()
        for _ in self.cost_pages((today - timedelta(days=1)).isoformat(), today.isoformat(), limit=1):
            break
