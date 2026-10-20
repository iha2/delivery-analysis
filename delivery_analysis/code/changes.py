"""Read per-commit file changes (lines and new-file hunk ranges) from a local clone."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import sqlite3

from delivery_analysis.code.clone import CodeError

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class ChangeSummary:
    read: int
    missing: int
    skipped_merges: int


def parse_hunks(diff_text: str) -> Dict[str, List[Tuple[int, int]]]:
    """New-file line ranges per path from a `-U0` diff.

    Decided: a pure-deletion hunk (`+c,0`) is kept as the single line (c, c), the line
    before the removal (at least 1), so proximity checks still see where code was removed.
    Deleted files (`+++ /dev/null`) have no new-file lines and are omitted.
    """
    out: Dict[str, List[Tuple[int, int]]] = {}
    current: Optional[str] = None
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ "):
            target = line[4:].rstrip("\t")
            if target == "/dev/null":
                current = None
            else:
                if target.startswith('"') and target.endswith('"'):
                    target = target[1:-1]
                current = target[2:] if target[:2] == "b/" else target
                out.setdefault(current, [])
        elif current is not None:
            match = _HUNK.match(line)
            if match:
                start = int(match.group(1))
                count = 1 if match.group(2) is None else int(match.group(2))
                if count == 0:
                    start = max(start, 1)
                    out[current].append((start, start))
                else:
                    out[current].append((start, start + count - 1))
    return out


def _parse_numstat(raw: str) -> Dict[str, Tuple[int, int]]:
    """Parse `--numstat -z` output into {new path: (added, removed)}; binary `-` counts as 0."""
    parts = raw.split("\0")
    out: Dict[str, Tuple[int, int]] = {}
    i = 0
    while i < len(parts):
        head = parts[i]
        i += 1
        if not head.strip():
            continue
        fields = head.split("\t", 2)
        if len(fields) < 3:
            continue
        added = int(fields[0]) if fields[0].isdigit() else 0
        removed = int(fields[1]) if fields[1].isdigit() else 0
        path = fields[2]
        if path == "":  # rename: old and new paths follow as separate records
            path = parts[i + 1] if i + 1 < len(parts) else ""
            i += 2
        if path:
            out[path] = (added, removed)
    return out


def _git(repo_path: Path, args: List[str], run: Callable[..., Any]) -> "subprocess.CompletedProcess[str]":
    try:
        return run(
            ["git", "-c", "core.quotePath=false", "-C", str(repo_path)] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise CodeError("git is not installed or not on PATH")


def read_commit_files(
    conn: sqlite3.Connection,
    repository_id: str,
    repo_path: Path,
    now: str,
    *,
    run: Callable[..., Any] = subprocess.run,
) -> ChangeSummary:
    shas = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT c.sha FROM vcs_commit c "
            "WHERE c.repository_id = ? AND c.change_request_id IS NOT NULL AND c.sha IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM commit_file f WHERE f.repository_id = c.repository_id AND f.sha = c.sha) "
            "ORDER BY c.sha",
            (repository_id,),
        )
    ]
    read = missing = merges = 0
    for sha in shas:
        parents = _git(repo_path, ["show", "-s", "--format=%P", sha], run)
        if parents.returncode != 0:
            missing += 1
            continue
        if len((parents.stdout or "").split()) > 1:
            merges += 1
            continue
        stat = _git(repo_path, ["show", "--format=", "--numstat", "-z", "-M", sha], run)
        diff = _git(repo_path, ["show", "--format=", "-U0", "-M", sha], run)
        if stat.returncode != 0 or diff.returncode != 0:
            missing += 1
            continue
        counts = _parse_numstat(stat.stdout or "")
        hunks = parse_hunks(diff.stdout or "")
        rows = [
            (
                repository_id,
                sha,
                path.replace("\\", "/"),
                added,
                removed,
                json.dumps([list(r) for r in hunks.get(path, [])]),
                now,
            )
            for path, (added, removed) in counts.items()
        ]
        conn.execute("BEGIN")
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO commit_file "
                "(repository_id, sha, path, lines_added, lines_removed, hunks, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        read += 1
    return ChangeSummary(read=read, missing=missing, skipped_merges=merges)
