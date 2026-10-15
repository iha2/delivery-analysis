from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

from delivery_analysis.connectors.bitbucket.client import BitbucketClient, NotFoundError

_UUID = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)


@dataclass(frozen=True)
class ResolvedRepo:
    uuid: str
    workspace: str
    slug: str


def resolve_repository(client: BitbucketClient, text: str, default_workspace: str = "") -> ResolvedRepo:
    """Turn `workspace/slug`, a UUID, or a bare slug into the repository's UUID using the API."""
    cleaned = text.strip()
    if "/" in cleaned:
        workspace, _, identifier = cleaned.partition("/")
    else:
        workspace, identifier = default_workspace.strip(), cleaned
    if not workspace:
        raise ValueError(
            "Say which workspace: write workspace/repo, or set BITBUCKET_WORKSPACE in .env."
        )
    if _UUID.match(identifier):
        identifier = "{" + identifier.strip("{}") + "}"
    try:
        data = client.get(
            f"/repositories/{workspace}/{quote(identifier, safe='')}",
            {"fields": "uuid,slug,workspace.slug"},
        )
    except NotFoundError:
        raise ValueError(f"Repository {text!r} was not found, or this token cannot see it.") from None
    return ResolvedRepo(
        uuid=data["uuid"],
        workspace=(data.get("workspace") or {}).get("slug") or workspace,
        slug=data["slug"],
    )
