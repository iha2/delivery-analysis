from __future__ import annotations

from typing import List, Mapping

from delivery_analysis.connectors.base import Connector
from delivery_analysis.settings import Settings


def build_connectors(settings: Settings, environ: Mapping[str, str]) -> List[Connector]:
    """Connectors are added by later specs (Bitbucket, Jira, Confluence, Claude usage)."""
    return []
