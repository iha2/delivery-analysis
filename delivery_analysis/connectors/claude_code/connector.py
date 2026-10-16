from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterator, List, Optional

from delivery_analysis.connectors.claude_code.client import ClaudeCodeClient, ClaudeUsageError
from delivery_analysis.connectors.claude_code.normalize import activity_values, normalize_day, usage_values
from delivery_analysis.model.records import Batch, RawPayload, Record

SOURCE = "claude_code_analytics"
COMPLETE_AFTER_DAYS = 2
NOT_ADMIN = (
    "The Claude usage key is not an Admin key (Admin keys start with sk-ant-admin). "
    "Set ANTHROPIC_ADMIN to an Anthropic Admin key to sync Claude usage."
)


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
    ) -> None:
        self._client = client
        self._admin_key = admin_key
        self._window_days = window_days
        self._today = today

    def validate(self) -> List[str]:
        if not self._admin_key:
            return [NOT_ADMIN]
        try:
            self._client.probe((self._today() - timedelta(days=1)).isoformat())
        except ClaudeUsageError as exc:
            return [str(exc)]
        return []

    def scopes(self) -> List[str]:
        return ["org"]

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
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
