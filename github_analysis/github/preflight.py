from __future__ import annotations

import json
import subprocess

from github_analysis.github.client import GhClient
from github_analysis.logging.run_log import RunLog
from github_analysis.models import RepositoryRef


def run_preflight(repository: RepositoryRef, log: RunLog) -> bool:
    """Verify gh authentication and read access to the target repository."""
    log.info("Preflight: checking GitHub CLI authentication (gh auth status)")
    status = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
    )
    auth_output = (status.stdout or "") + (status.stderr or "")
    for line in auth_output.strip().splitlines():
        if line.strip():
            log.info(f"  {line.strip()}")

    if status.returncode != 0:
        log.error("GitHub CLI is not authenticated. Run: gh auth login")
        log.error("For private org repos, ensure your token has the 'repo' scope and SSO is authorized.")
        return False

    log.info(f"Preflight: checking read access to {repository.slug}")
    client = GhClient()
    try:
        user = client.get("/user")
        login = (user or {}).get("login") or "(unknown)"
        log.info(f"Authenticated as GitHub user: {login}")
    except Exception as exc:
        log.error(f"Cannot call GitHub API as authenticated user: {exc}")
        return False

    try:
        repo = client.get(f"/repos/{repository.owner}/{repository.name}")
        log.info(f"Repository access OK: {(repo or {}).get('full_name', repository.slug)}")
        log.info(f"  private={(repo or {}).get('private')!r} default_branch={(repo or {}).get('default_branch')!r}")
        return True
    except Exception as exc:
        log.error(f"Cannot read repository {repository.slug}: {exc}")
        log.error("Check that your account can view the repo and that org SSO is authorized for your token.")
        return False
