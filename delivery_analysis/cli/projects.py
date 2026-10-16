from __future__ import annotations

import argparse
import re
from typing import Dict, List, Mapping, Optional, Tuple

import httpx

from delivery_analysis.connectors.jira.client import (
    JiraClient,
    JiraError,
    NotFoundError,
    base_url_from,
    jira_credentials,
)
from delivery_analysis.connectors.jira.connector import credential_problems
from delivery_analysis.connectors.jira.fields import FieldCatalogue, detect_points_field
from delivery_analysis.connectors.jira.statuses import seed_for
from delivery_analysis.settings import Settings
from delivery_analysis.store import project_selection
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.store.sync_state import list_sync_states
from delivery_analysis.sync.runner import utc_now_iso

SOURCE = "jira"
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def register(commands) -> None:
    projects = commands.add_parser("projects", help="Choose which Jira projects are synced")
    actions = projects.add_subparsers(dest="projects_command", metavar="<action>", required=True)
    add = actions.add_parser("add", help="Select a Jira project (checks access, picks the story points field)")
    add.add_argument("project", metavar="jira:KEY", help="for example jira:MD")
    add.add_argument(
        "--points-field", metavar="ID",
        help="Story points field id, for example customfield_10004 (default: the most filled candidate)",
    )
    actions.add_parser("list", help="Show selected projects and their sync status")
    remove = actions.add_parser("remove", help="Stop syncing a project (stored data is kept)")
    remove.add_argument("project", metavar="jira:KEY")
    mapper = actions.add_parser("map", help="Map one status of a project to a category")
    mapper.add_argument("project", metavar="jira:KEY")
    mapper.add_argument("status", help="the status name exactly as Jira shows it")
    mapper.add_argument("category", choices=list(project_selection.CATEGORIES))


def _key(value: str) -> str:
    source, separator, key = value.partition(":")
    if not separator or not source.strip() or not key.strip():
        raise ValueError("Write the project as jira:<KEY>, for example jira:MD.")
    if source.strip() != SOURCE:
        raise ValueError("Only jira projects are supported here. Use jira:<KEY>.")
    key = key.strip()
    if not _KEY.match(key):
        raise ValueError(f"{key!r} is not a valid project key.")
    return key.upper()


def _client(environ: Mapping[str, str], transport: Optional[httpx.BaseTransport]) -> JiraClient:
    email, token = jira_credentials(environ)
    if not token:
        raise ValueError(
            "ATLASSIAN is not set. Create an Atlassian API token and put it in .env as ATLASSIAN, "
            "with the account email as ATLASSIAN_EMAIL."
        )
    return JiraClient(email, token, base_url=base_url_from(environ), transport=transport)


def _detect_points(client: JiraClient, key: str, catalogue: FieldCatalogue) -> Tuple[str, List[str]]:
    candidates = catalogue.points_candidates()
    if not candidates:
        raise ValueError("No story points field exists on this site. Pass --points-field.")
    page = client.search(f'project = "{key}" ORDER BY updated DESC', candidates)
    issues = page.get("issues") or []
    counts: Dict[str, int] = {
        field: sum(1 for item in issues if (item.get("fields") or {}).get(field) is not None)
        for field in candidates
    }
    chosen, reason = detect_points_field(counts)
    lines = [f"  {field}: {counts[field]} of {len(issues)} sampled issues have a value" for field in candidates]
    if chosen is None:
        raise ValueError("\n".join(lines + [reason]))
    return chosen, lines


def _add(conn, args, environ, transport) -> int:
    key = _key(args.project)
    client = _client(environ, transport)
    problems = credential_problems(client)
    if problems:
        raise ValueError(" ".join(problems))
    try:
        info = client.project(key)
    except NotFoundError:
        raise ValueError(f"Project {key} was not found, or this token cannot browse it.") from None
    catalogue = FieldCatalogue(client.fields())
    detail: List[str] = []
    if args.points_field:
        field = args.points_field.strip()
        if not catalogue.has(field):
            raise ValueError(f"Field {field} was not found on this Jira site.")
        points = field
        detail.append(f"Story points field: {field} (chosen by you)")
    else:
        points, lines = _detect_points(client, key, catalogue)
        detail.append(f"Story points field: {points}")
        detail.extend(lines)
    names = {
        status["name"]
        for issue_type in client.project_statuses(key)
        for status in issue_type.get("statuses", [])
    }
    mapped, _ = seed_for(names)
    project_selection.add_project(
        conn, SOURCE, info.get("key") or key, str(info["id"]), info.get("name"), points, utc_now_iso()
    )
    project_key = info.get("key") or key
    project_selection.seed_statuses(conn, SOURCE, project_key, mapped)
    current = project_selection.status_map(conn, SOURCE, project_key)
    still = sorted(name for name in names if name not in current)
    print(f"Selected jira:{project_key} ({info.get('name')}, id {info['id']})")
    for line in detail:
        print(line)
    print(f"Statuses mapped: {len(current)} ({len(mapped)} from the defaults)")
    if still:
        print(f'Statuses that still need a mapping (run: delivery-analysis projects map jira:{project_key} "<status>" <category>):')
        for name in still:
            print(f"  {name}")
    return 0


def _list(conn) -> int:
    selected = project_selection.list_projects(conn, SOURCE)
    if not selected:
        print("No Jira projects are selected. Run: delivery-analysis projects add jira:<KEY>")
        return 0
    states = {s["scope"]: s for s in list_sync_states(conn) if s["connector"] == SOURCE}
    for row in selected:
        state = states.get(row["project_key"])
        status = state["status"] if state else "never"
        last = (state["last_run"] if state else None) or "never"
        unmapped = project_selection.unmapped_seen(conn, SOURCE, row["project_key"])
        line = (
            f"{row['project_key']}  {row['name'] or ''}  status: {status}  last sync: {last}  "
            f"issues: {project_selection.issue_count(conn, SOURCE, row['project_key'])}  "
            f"points field: {row['story_points_field'] or 'none'}"
        )
        if unmapped:
            line += "  unmapped statuses: " + ", ".join(unmapped)
        print(line)
    return 0


def _remove(conn, args) -> int:
    key = _key(args.project)
    if project_selection.remove_project(conn, SOURCE, key) == 0:
        raise ValueError(f"Project {key} is not selected.")
    print(f"Removed jira:{key} from the selection. Stored data is kept.")
    return 0


def _map(conn, args) -> int:
    key = _key(args.project)
    if project_selection.get_project(conn, SOURCE, key) is None:
        raise ValueError(f"Project {key} is not selected. Run: delivery-analysis projects add jira:{key}")
    project_selection.set_status(conn, SOURCE, key, args.status, args.category)
    print(f"jira:{key}: {args.status!r} is now {args.category}.")
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
        if args.projects_command == "add":
            return _add(conn, args, environ, transport)
        if args.projects_command == "list":
            return _list(conn)
        if args.projects_command == "map":
            return _map(conn, args)
        return _remove(conn, args)
    except (ValueError, JiraError) as exc:
        print(str(exc))
        return 2
    finally:
        conn.close()
