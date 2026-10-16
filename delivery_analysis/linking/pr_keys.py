from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Pattern, Set, Tuple

from delivery_analysis.model.records import Record
from delivery_analysis.store.upsert import upsert_record

LINK_SOURCE = "linker"


@dataclass(frozen=True)
class Coverage:
    total: int
    linked: int
    links: int
    unknown_keys: int
    unlinked_authors: Tuple[Tuple[str, int], ...]
    projects: int

    def lines(self) -> List[str]:
        if self.projects == 0:
            return ["Issue links: no Jira project has been synced yet, so no pull request keys were checked."]
        out = [f"Issue links: {self.linked} of {self.total} pull requests have an issue key."]
        if self.unlinked_authors:
            listed = ", ".join(f"{author} ({count})" for author, count in self.unlinked_authors)
            out.append("  most unlinked pull requests by author: " + listed)
        return out


def key_pattern(projects: Iterable[str]) -> Optional[Pattern[str]]:
    """A case-sensitive pattern for `KEY-123` built from the synced project keys, longest first.

    The key must not touch a letter or digit on either side, so `XMD-1`, `MD-1abc`, `MD-123456789`
    and `UTF-8` do not match; a following `_` or `-` is fine (`feature/MD-1_fix`).
    """
    ordered = sorted({p for p in projects if p}, key=lambda p: (-len(p), p))
    if not ordered:
        return None
    alternatives = "|".join(re.escape(p) for p in ordered)
    return re.compile(r"(?<![A-Za-z0-9])(" + alternatives + r")-(\d{1,7})(?![A-Za-z0-9])")


def link_id(from_id: str, to_id: str, found_by: str) -> str:
    return hashlib.sha1(f"{from_id}|{to_id}|implements|{found_by}".encode("utf-8")).hexdigest()


def link_pull_requests(conn: sqlite3.Connection, now: str) -> Coverage:
    """Link Bitbucket pull requests to Jira issues by key in the title or source branch."""
    projects = [
        row["project"]
        for row in conn.execute(
            "SELECT DISTINCT project FROM work_item WHERE source = 'jira' AND project IS NOT NULL"
        )
    ]
    prs = conn.execute(
        "SELECT source_id, author_account, title, branch FROM change_request WHERE source = 'bitbucket'"
    ).fetchall()
    pattern = key_pattern(projects)
    if pattern is None:
        return Coverage(len(prs), 0, 0, 0, (), 0)
    issues: Dict[str, str] = {
        row["key"]: row["source_id"]
        for row in conn.execute("SELECT key, source_id FROM work_item WHERE source = 'jira' AND key IS NOT NULL")
    }
    linked = links = unknown = 0
    unlinked: Dict[str, int] = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        for pr in prs:
            found: Dict[str, Set[str]] = {}
            for found_by, text in (("pr_title", pr["title"]), ("pr_branch", pr["branch"])):
                for match in pattern.finditer(text or ""):
                    issue_id = issues.get(f"{match.group(1)}-{match.group(2)}")
                    if issue_id is None:
                        unknown += 1
                        continue
                    found.setdefault(issue_id, set()).add(found_by)
            if not found:
                author = pr["author_account"] or "unknown"
                unlinked[author] = unlinked.get(author, 0) + 1
                continue
            linked += 1
            for issue_id in sorted(found):
                for found_by in sorted(found[issue_id]):
                    upsert_record(
                        conn,
                        Record(
                            "link",
                            {
                                "source": LINK_SOURCE,
                                "source_id": link_id(pr["source_id"], issue_id, found_by),
                                "from_kind": "change_request",
                                "from_id": pr["source_id"],
                                "to_kind": "work_item",
                                "to_id": issue_id,
                                "kind": "implements",
                                "found_by": found_by,
                            },
                        ),
                        now,
                    )
                    links += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    top = tuple(sorted(unlinked.items(), key=lambda item: (-item[1], item[0]))[:5])
    return Coverage(len(prs), linked, links, unknown, top, len(projects))
