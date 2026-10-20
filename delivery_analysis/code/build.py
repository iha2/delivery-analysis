"""Clone, read commit files and weigh files for each selected Bitbucket repository."""
from __future__ import annotations

import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional

from delivery_analysis.code.changes import read_commit_files
from delivery_analysis.code.clone import CodeError, ensure_clone, repo_dir
from delivery_analysis.code.graph import snapshot
from delivery_analysis.settings import Settings, redact, secret_values
from delivery_analysis.store import repo_selection
from delivery_analysis.sync.runner import utc_now_iso

SOURCE = "bitbucket"


def bitbucket_url(workspace: str, slug: str) -> str:
    return "https://bitbucket.org/%s/%s.git" % (workspace, slug)


@dataclass
class CodeBuildResult:
    lines: List[str] = field(default_factory=list)
    failed: int = 0
    built: int = 0


def build_code(
    conn: sqlite3.Connection,
    settings: Settings,
    environ: Mapping[str, str],
    *,
    repo: Optional[str] = None,
    fetch: bool = True,
    run: Callable[..., Any] = subprocess.run,
    log: Optional[Callable[[str], None]] = None,
    url_for: Callable[[str, str], str] = bitbucket_url,
) -> CodeBuildResult:
    """Per selected repo: ensure_clone, read_commit_files, snapshot. fetch=False uses only existing clones."""
    token = (environ.get("BITBUCKET") or "").strip()
    secrets = secret_values(environ)
    result = CodeBuildResult()
    selected = repo_selection.list_selected(conn, SOURCE)
    if repo is not None:
        wanted = repo_selection.resolve(conn, SOURCE, repo)
        selected = [row for row in selected if row["repository_id"] == wanted]
    results_dir = Path(settings.db_path).parent

    def emit(text: str) -> None:
        line = redact(text, secrets)
        result.lines.append(line)
        if log is not None:
            log(line)

    for row in selected:
        name = "%s/%s" % (row["workspace"], row["slug"])
        dest = repo_dir(results_dir, row["repository_id"])
        try:
            if fetch:
                ensure_clone(url_for(row["workspace"], row["slug"]), dest, token, run=run)
            elif not (dest / ".git").is_dir():
                continue
            now = utc_now_iso()
            changes = read_commit_files(conn, row["repository_id"], dest, now, run=run)
            files = snapshot(conn, row["repository_id"], dest, now)
            conn.commit()
        except CodeError as exc:
            result.failed += 1
            emit("%s: code build failed: %s" % (name, exc))
            continue
        result.built += 1
        emit(
            "%s: %d files weighed, %d commits read, %d commits missing, %d merges skipped"
            % (name, files, changes.read, changes.missing, changes.skipped_merges)
        )
    return result
