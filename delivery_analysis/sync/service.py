from __future__ import annotations

import sqlite3
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from delivery_analysis.connectors.base import Connector
from delivery_analysis.settings import Settings, redact, secret_values
from delivery_analysis.sync.runner import SourceResult, run_sync, utc_now_iso
from delivery_analysis.teams.reconcile import reconcile_all, stale_repo_keys


def sync_and_reconcile(
    conn: sqlite3.Connection,
    connectors: Sequence[Connector],
    settings: Settings,
    environ: Mapping[str, str],
    *,
    only: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> Tuple[List[SourceResult], List[str], int]:
    """Sync, then update every team. Returns (results, team summary lines, failed team count)."""
    secrets = secret_values(environ)
    results = run_sync(
        conn, connectors, overlap_days=settings.overlap_days, only=only, redact_values=secrets, log=log
    )
    try:
        lines, failed_teams = reconcile_all(
            conn,
            utc_now_iso(),
            stale_repo_keys(conn),
            {only} if only else None,
            lambda text: redact(text, secrets),
        )
    except Exception as exc:
        lines = ["Team update failed: " + redact(str(exc) or exc.__class__.__name__, secrets)]
        failed_teams = 1
    return results, lines, failed_teams
