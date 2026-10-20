from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from delivery_analysis.code.build import build_code
from delivery_analysis.connectors.base import Connector
from delivery_analysis.linking.pr_keys import link_pull_requests
from delivery_analysis.metrics.impact_build import rebuild_impact
from delivery_analysis.settings import Settings, redact, secret_values
from delivery_analysis.sync.runner import SourceResult, run_sync, utc_now_iso
from delivery_analysis.teams.reconcile import reconcile_all, stale_repo_keys
from delivery_analysis.tokens.rebuild import rebuild as rebuild_tokens


def sync_and_reconcile(
    conn: sqlite3.Connection,
    connectors: Sequence[Connector],
    settings: Settings,
    environ: Mapping[str, str],
    *,
    only: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
    fetch_code: bool = False,
) -> Tuple[List[SourceResult], List[str], int]:
    """Sync, then update every team. Returns (results, team summary lines, failed team count).

    fetch_code lets the code build fetch clones (needs BITBUCKET); otherwise only existing clones are read.
    """
    secrets = secret_values(environ)
    results = run_sync(
        conn, connectors, overlap_days=settings.overlap_days, only=only, redact_values=secrets, log=log
    )
    link_lines: List[str] = []
    if only is None or only in ("jira", "bitbucket"):
        try:
            link_lines = link_pull_requests(conn, utc_now_iso()).lines()
        except Exception as exc:
            link_lines = ["Issue link pass failed: " + redact(str(exc) or exc.__class__.__name__, secrets)]
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
    if only is None or only in ("jira", "bitbucket"):
        fetch = fetch_code and bool((environ.get("BITBUCKET") or "").strip())
        try:
            lines.extend(build_code(conn, settings, environ, fetch=fetch, log=None).lines)
        except Exception as exc:  # the code build must never fail the sync
            lines.append("Code build failed: " + redact(str(exc) or exc.__class__.__name__, secrets))
        try:
            lines.extend(redact(line, secrets) for line in rebuild_impact(conn, utc_now_iso()).lines())
        except Exception as exc:
            lines.append("Impact build failed: " + redact(str(exc) or exc.__class__.__name__, secrets))
    try:
        if conn.execute("SELECT 1 FROM claude_usage_day LIMIT 1").fetchone() is not None:
            summary = rebuild_tokens(conn, datetime.now(timezone.utc).date(), window_days=settings.window_days)
            lines.extend(summary.lines())
    except Exception as exc:  # attribution must never fail the sync
        lines.append("Token attribution failed: " + redact(str(exc) or exc.__class__.__name__, secrets))
    return results, link_lines + lines, failed_teams
