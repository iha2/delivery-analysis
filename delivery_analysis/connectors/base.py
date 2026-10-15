from __future__ import annotations

from typing import Iterator, List, Optional, Protocol

from delivery_analysis.model.records import Batch


class Connector(Protocol):
    """A source of canonical records. Connectors only fetch and normalize."""

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
