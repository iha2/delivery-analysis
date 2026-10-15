from __future__ import annotations

import argparse
from typing import Dict, Mapping, Optional

import httpx

from delivery_analysis.cli.teams import parse_repo
from delivery_analysis.connectors.bitbucket.client import BitbucketClient, BitbucketError
from delivery_analysis.connectors.bitbucket.resolve import resolve_repository
from delivery_analysis.settings import Settings
from delivery_analysis.store import repo_selection
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.store.sync_state import list_sync_states
from delivery_analysis.sync.runner import utc_now_iso

SOURCE = "bitbucket"


def register(commands) -> None:
    repos = commands.add_parser("repos", help="Choose which repositories are synced")
    actions = repos.add_subparsers(dest="repos_command", metavar="<action>", required=True)
    add = actions.add_parser("add", help="Select a Bitbucket repository (checks access first)")
    add.add_argument(
        "repo", metavar="bitbucket:REPO",
        help="workspace/slug, a UUID, or a slug if BITBUCKET_WORKSPACE is set",
    )
    actions.add_parser("list", help="Show selected repositories and their sync status")
    remove = actions.add_parser("remove", help="Stop syncing a repository (stored data is kept)")
    remove.add_argument("repo", metavar="bitbucket:REPO")


def _source_and_text(value: str) -> str:
    try:
        source, text = parse_repo(value)
    except ValueError:
        raise ValueError("Write the repository as bitbucket:<repo>, for example bitbucket:myspace/myrepo.") from None
    if source != SOURCE:
        raise ValueError("Only bitbucket repositories are supported for now. Use bitbucket:<repo>.")
    return text


def _add(conn, args, settings: Settings, environ: Mapping[str, str], transport) -> int:
    text = _source_and_text(args.repo)
    token = (environ.get("BITBUCKET") or "").strip()
    if not token:
        raise ValueError(
            "BITBUCKET is not set. Create an Atlassian API token with read:repository:bitbucket and "
            "read:pullrequest:bitbucket and put it in .env as BITBUCKET."
        )
    client = BitbucketClient(token, transport=transport)
    repo = resolve_repository(client, text, settings.bitbucket_workspace)
    repo_selection.add_repo(conn, SOURCE, repo.uuid, repo.workspace, repo.slug, utc_now_iso())
    print(f"Selected bitbucket:{repo.workspace}/{repo.slug} ({repo.uuid})")
    return 0


def _list(conn) -> int:
    selected = repo_selection.list_selected(conn, SOURCE)
    if not selected:
        print("No repositories are selected. Run: delivery-analysis repos add bitbucket:<workspace>/<repo>")
        return 0
    states: Dict[str, Dict[str, object]] = {
        state["scope"]: state for state in list_sync_states(conn) if state["connector"] == SOURCE
    }
    for row in selected:
        state = states.get(row["repository_id"])
        status = state["status"] if state else "never"
        last = (state["last_run"] if state else None) or "never"
        done, total = repo_selection.detail_progress(conn, row["repository_id"])
        print(
            f"{row['workspace']}/{row['slug']}  {row['repository_id']}  "
            f"status: {status}  last sync: {last}  detail: {done}/{total}"
        )
    return 0


def _remove(conn, args) -> int:
    text = _source_and_text(args.repo)
    if repo_selection.remove_repo(conn, SOURCE, text) == 0:
        raise ValueError(f"No selected repository matches {text!r}.")
    print(f"Removed {text} from the selection. Stored data is kept.")
    return 0


def run(
    args: argparse.Namespace,
    settings: Settings,
    environ: Mapping[str, str],
    *,
    transport: Optional[httpx.BaseTransport] = None,
) -> int:
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        if args.repos_command == "add":
            return _add(conn, args, settings, environ, transport)
        if args.repos_command == "list":
            return _list(conn)
        return _remove(conn, args)
    except (ValueError, BitbucketError) as exc:
        print(str(exc))
        return 2
    finally:
        conn.close()
