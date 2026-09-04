from __future__ import annotations

import sys
from urllib.parse import urlparse

from github_analysis.config import DEFAULT_GITHUB_OWNER
from github_analysis.models import RepositoryRef


def resolve_repository(repo_arg: str, owner_override: str = "") -> RepositoryRef:
    """
    Accepts HTTPS/SSH clone URL, owner/name, or repo name only.
    """
    raw = repo_arg.strip().rstrip("/")
    note_owner_ignored = False

    if raw.startswith("git@"):
        if ":" not in raw:
            raise ValueError(f"invalid git SSH URL: {repo_arg!r}")
        _, _, rest = raw.partition(":")
        rest = rest.removesuffix(".git").strip()
        parts = rest.split("/", 1)
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"could not parse owner/repo from SSH URL: {repo_arg!r}")
        owner, name = parts[0], parts[1]
        note_owner_ignored = True
    elif raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        path = (parsed.path or "").strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        segments = [part for part in path.split("/") if part]
        if len(segments) < 2:
            raise ValueError(
                f"expected a URL like https://github.com/owner/repo — got: {repo_arg!r}"
            )
        owner, name = segments[0], segments[1]
        note_owner_ignored = True
    elif "/" in raw:
        owner, _, name = raw.partition("/")
        owner, name = owner.strip(), name.strip().strip("/")
        note_owner_ignored = True
    else:
        name = raw.strip("/")
        owner = owner_override.strip() or DEFAULT_GITHUB_OWNER

    if not owner or not name:
        raise ValueError("owner and repository name must be non-empty")

    if note_owner_ignored and owner_override.strip():
        print(
            "Note: --owner ignored because --repo already includes owner (URL or owner/name).",
            file=sys.stderr,
        )
    return RepositoryRef(owner=owner, name=name)
