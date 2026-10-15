from __future__ import annotations

from typing import Dict, Iterator, List, Optional, Tuple

from delivery_analysis.model.records import Batch


class FakeConnector:
    """In-memory connector used by tests."""

    def __init__(
        self,
        name: str = "fake",
        batches: Optional[Dict[str, List[Batch]]] = None,
        problems: Optional[List[str]] = None,
        fail_on_batch: Optional[int] = None,
        fail_message: str = "boom",
    ) -> None:
        self.name = name
        self._batches = batches if batches is not None else {"main": []}
        self._problems = list(problems or [])
        self._fail_on_batch = fail_on_batch
        self._fail_message = fail_message
        self.calls: List[Tuple[str, Optional[str]]] = []

    def validate(self) -> List[str]:
        return list(self._problems)

    def scopes(self) -> List[str]:
        return list(self._batches)

    def sync(self, scope: str, since: Optional[str]) -> Iterator[Batch]:
        self.calls.append((scope, since))
        for index, batch in enumerate(self._batches.get(scope, [])):
            if self._fail_on_batch == index:
                raise RuntimeError(self._fail_message)
            yield batch
