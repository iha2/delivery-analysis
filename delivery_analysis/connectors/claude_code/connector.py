from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from delivery_analysis.connectors.claude_code.client import ClaudeCodeClient, ClaudeUsageError
from delivery_analysis.connectors.claude_code.normalize import (
    activity_values, normalize_cost_rows, normalize_day, usage_values,
)
from delivery_analysis.model.records import Batch, RawPayload, Record

SOURCE = "claude_code_analytics"
COMPLETE_AFTER_DAYS = 2
CHUNK_DAYS = 31
COST_FLOOR = date(2026, 1, 1)  # the user cost endpoint refuses anything earlier
MAX_LOOKBACK_DAYS = 364  # and anything more than 365 days back
NOT_ADMIN = (
    "The Claude usage key is not an Admin key (Admin keys start with sk-ant-admin). "
    "Set ANTHROPIC_ADMIN to an Anthropic Admin key to sync Claude usage."
)


def _parse_utc(value: object) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


class ClaudeCodeConnector:
    """Per-developer daily Claude Code cost and activity. One scope, one replacing batch per UTC day."""

    name = SOURCE

    def __init__(
        self,
        client: ClaudeCodeClient,
        *,
        admin_key: bool = True,
        window_days: int = 90,
        today: Callable[[], date] = utc_today,
        report: str = "claude_code",
    ) -> None:
        if report not in ("claude_code", "user_cost"):
            raise ValueError(f"unknown Claude usage report {report!r}")
        self._report = report
        self._client = client
        self._admin_key = admin_key
        self._window_days = window_days
        self._today = today

    def validate(self) -> List[str]:
        if self._report == "claude_code" and not self._admin_key:
            return [NOT_ADMIN]
        try:
            if self._report == "user_cost":
                self._client.probe_cost(self._today())
            else:
                self._client.probe((self._today() - timedelta(days=1)).isoformat())
        except ClaudeUsageError as exc:
            return [str(exc)]
        return []

    def scopes(self) -> List[str]:
        return ["org"]

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
        if self._report == "user_cost":
            yield from self._sync_user_cost(since)
            return
        today = self._today()
        first = date.fromisoformat(since[:10]) if since else today - timedelta(days=self._window_days)
        complete = today - timedelta(days=COMPLETE_AFTER_DAYS)
        day = first
        while day <= today:
            iso = day.isoformat()
            pages = list(self._client.day_pages(iso))
            result = normalize_day(iso, [record for page in pages for record in (page.get("data") or [])])
            records = [Record("claude_usage_day", usage_values(SOURCE, row)) for row in result.usage]
            records += [Record("claude_activity_day", activity_values(SOURCE, row)) for row in result.activity]
            yield Batch(
                records,
                raw=[RawPayload(SOURCE, iso, "claude_code_day", json.dumps(pages, sort_keys=True))],
                cursor=f"{iso}T00:00:00Z" if day <= complete else None,
                replace=[
                    ("claude_usage_day", {"source": SOURCE, "day": iso}),
                    ("claude_activity_day", {"source": SOURCE, "day": iso}),
                ],
            )
            day += timedelta(days=1)

    def _sync_user_cost(self, since: Optional[str]) -> Iterator[Batch]:
        today = self._today()
        first = date.fromisoformat(since[:10]) if since else today - timedelta(days=self._window_days)
        first = max(first, COST_FLOOR, today - timedelta(days=MAX_LOOKBACK_DAYS))
        end = today + timedelta(days=1)
        chunk_start = first
        cursors_ok = True  # once a day is incomplete no later day may carry a cursor
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
            pages = list(self._client.cost_pages(chunk_start.isoformat(), chunk_end.isoformat()))
            refreshed = self._refreshed(pages)
            result = normalize_cost_rows([row for page in pages for row in (page.get("data") or [])])
            by_day: Dict[str, List[Record]] = {}
            for row in result.usage:
                by_day.setdefault(row.day, []).append(Record("claude_usage_day", usage_values(SOURCE, row)))
            raw = RawPayload(
                SOURCE, f"{chunk_start.isoformat()}..{chunk_end.isoformat()}", "user_cost_chunk",
                json.dumps(pages, sort_keys=True),
            )
            day = chunk_start
            while day < chunk_end:
                iso = day.isoformat()
                complete = self._complete(day, today, refreshed)
                cursors_ok = cursors_ok and complete
                yield Batch(
                    by_day.get(iso, []),
                    raw=[raw] if day == chunk_start else [],
                    cursor=f"{iso}T00:00:00Z" if cursors_ok else None,
                    replace=[("claude_usage_day", {"source": SOURCE, "day": iso})],
                )
                day += timedelta(days=1)
            chunk_start = chunk_end

    @staticmethod
    def _refreshed(pages: List[dict]) -> Optional[datetime]:
        """The oldest data_refreshed_at over the pages; None when any page lacks one."""
        stamps = [_parse_utc(page.get("data_refreshed_at")) for page in pages]
        if not stamps or any(stamp is None for stamp in stamps):
            return None
        return min(stamps)  # type: ignore[type-var]

    @staticmethod
    def _complete(day: date, today: date, refreshed: Optional[datetime]) -> bool:
        if day > today - timedelta(days=COMPLETE_AFTER_DAYS) or refreshed is None:
            return False
        day_end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        return day_end <= refreshed
