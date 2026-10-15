from __future__ import annotations

from typing import Iterator, List, Optional, Protocol

from delivery_analysis.model.records import Batch


class Connector(Protocol):
    """A source of canonical records. Connectors only fetch and normalize.

    Convention that team rosters rely on: a connector's `name` equals the `source` column of every
    record it writes, and a repository scope string equals that repository's `source_id` (the same
    value stored in `vcs_commit.repository_id`). A failed scope marks that repository stale, and a
    failed `validate()` or `scopes()` (recorded under scope "*") marks every repository of the
    source stale, so a failed sync never marks anyone inactive. If a connector breaks the
    convention, failures are not matched to repositories and rosters are not protected.
    """

    name: str

    def validate(self) -> List[str]:
        """Return plain-language problems (for example a missing credential); empty means ready."""
        ...

    def scopes(self) -> List[str]:
        """The units that are synced and tracked separately (repos, projects, spaces)."""
        ...

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
        """Yield batches of records changed since `since` (UTC ISO string, or None for everything)."""
        ...
