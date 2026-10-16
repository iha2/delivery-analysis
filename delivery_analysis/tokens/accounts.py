from __future__ import annotations

import sqlite3
from typing import Dict, Optional, Set, Tuple


class AccountMap:
    """(source, account) to person, read once. Identities of excluded people resolve to None.

    Jira and Bitbucket share one Atlassian account id, and the Jira connector never sets
    `identity.person_id`, so a Jira account falls back to the Bitbucket identity with the same id.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        excluded = {
            row["person_id"] for row in conn.execute("SELECT person_id FROM person WHERE excluded = 1")
        }
        self._map: Dict[Tuple[str, str], str] = {}
        self._excluded: Set[Tuple[str, str]] = set()
        for row in conn.execute(
            "SELECT source, account_id, person_id FROM identity WHERE person_id IS NOT NULL"
        ):
            key = (row["source"], row["account_id"])
            if row["person_id"] in excluded:
                self._excluded.add(key)
            else:
                self._map[key] = row["person_id"]

    def person(self, source: str, account: Optional[str]) -> Optional[str]:
        if not account:
            return None
        found = self._map.get((source, account))
        if found is None and source == "jira":
            found = self._map.get(("bitbucket", account))
        return found

    def commit_author(self, account: Optional[str], email: Optional[str]) -> Optional[str]:
        found = self.person("bitbucket", account)
        if found is None and email:
            found = self.person("email", email.strip().lower())
        return found

    def is_excluded(self, source: str, account: Optional[str]) -> bool:
        return bool(account) and (source, account) in self._excluded
