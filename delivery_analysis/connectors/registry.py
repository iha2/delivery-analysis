from __future__ import annotations

from typing import List, Mapping, Optional

import httpx

from delivery_analysis.connectors.base import Connector
from delivery_analysis.connectors.bitbucket.client import BitbucketClient
from delivery_analysis.connectors.bitbucket.connector import BitbucketConnector
from delivery_analysis.settings import Settings


def build_connectors(
    settings: Settings,
    environ: Mapping[str, str],
    transport: Optional[httpx.BaseTransport] = None,
) -> List[Connector]:
    """Jira, Confluence, and Claude usage connectors are added by later specs."""
    connectors: List[Connector] = []
    token = (environ.get("BITBUCKET") or "").strip()
    if token:
        client = BitbucketClient(token, transport=transport)
        connectors.append(
            BitbucketConnector(
                client,
                settings.db_path,
                workspace=settings.bitbucket_workspace,
                window_days=settings.window_days,
            )
        )
    return connectors
