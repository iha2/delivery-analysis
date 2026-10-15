from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path
from typing import Callable, List, Tuple

from delivery_analysis.identity.merge import merge_identities
from delivery_analysis.settings import Settings
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.sync.runner import utc_now_iso
from delivery_analysis.teams.discover import discover_people, window_start
from delivery_analysis.teams.reconcile import create_team, reconcile_team
from delivery_analysis.teams.yaml_io import export_teams, import_teams

Repo = Tuple[str, str]


def register(commands) -> None:
    teams = commands.add_parser("teams", help="Discover, save, import and export team rosters")
    actions = teams.add_subparsers(dest="teams_command", metavar="<action>", required=True)

    discover = actions.add_parser(
        "discover", help="Show who committed to the repositories (add --save NAME to keep the team)"
    )
    discover.add_argument(
        "--repo", action="append", required=True, metavar="SOURCE:REPO",
        help="Repository to look at, for example bitbucket:my-repo (repeatable)",
    )
    discover.add_argument("--since", default="90d", help="Window, a number of days such as 90d (default 90d)")
    discover.add_argument("--save", metavar="NAME", help="Create a team with this name and load its roster")

    importer = actions.add_parser("import", help="Load teams from a .json or .yaml file")
    importer.add_argument("path")
    importer.add_argument(
        "--repo", action="append", metavar="SOURCE:REPO",
        help="Repository the imported teams are kept up to date from (repeatable)",
    )

    exporter = actions.add_parser("export", help="Write active members to a .json or .yaml file")
    exporter.add_argument("path")
    exporter.add_argument("--team", help="Only this team")


def parse_since(text: str) -> int:
    match = re.fullmatch(r"(\d+)d", text.strip().lower())
    if not match or int(match.group(1)) == 0:
        raise ValueError("--since must be a number of days such as 90d.")
    return int(match.group(1))


def parse_repo(text: str) -> Repo:
    source, separator, repository = text.partition(":")
    if not separator or not source.strip() or not repository.strip():
        raise ValueError("--repo must look like bitbucket:repo-name.")
    return source.strip(), repository.strip()


def _print_roster(conn: sqlite3.Connection, team_id: str) -> None:
    rows = conn.execute(
        "SELECT p.display_name AS name, m.status AS status, m.last_commit AS last "
        "FROM team_member m JOIN person p ON p.person_id = m.person_id WHERE m.team_id = ? "
        "ORDER BY m.status, lower(p.display_name)",
        (team_id,),
    ).fetchall()
    for row in rows:
        print(f"  {row['status']:9} {row['name']}  (last commit {(row['last'] or '')[:10]})")


def _discover(conn: sqlite3.Connection, args: argparse.Namespace, now: str) -> int:
    days = parse_since(args.since)
    repos: List[Repo] = [parse_repo(text) for text in args.repo]
    if args.save:
        team_id = create_team(conn, args.save, repos, days, now=now)
        print(reconcile_team(conn, team_id, now).summary())
        _print_roster(conn, team_id)
        return 0
    people, duplicates = merge_identities(discover_people(conn, repos, window_start(now, days)))
    if not people:
        print("No commits found for these repositories in the window. Has the sync run?")
        return 0
    for person in people:
        flag = "  [bot]" if person.is_bot else ""
        print(
            f"{person.display_name}  {person.commits} commits  last {person.last_commit[:10]}  "
            f"{', '.join(person.emails)}{flag}"
        )
    for duplicate in duplicates:
        print(f"possible duplicate: {duplicate.email_a}  <->  {duplicate.email_b}  ({duplicate.reason})")
    return 0


def run(args: argparse.Namespace, settings: Settings, *, now: Callable[[], str] = utc_now_iso) -> int:
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        if args.teams_command == "discover":
            return _discover(conn, args, now())
        if args.teams_command == "import":
            repos = [parse_repo(text) for text in (args.repo or [])]
            for line in import_teams(conn, Path(args.path), repos, now()):
                print(line)
            return 0
        if args.teams_command == "export":
            print(export_teams(conn, Path(args.path), args.team or ""))
            return 0
        raise ValueError(f"Unknown teams action {args.teams_command!r}.")
    except ValueError as exc:
        print(str(exc))
        return 2
    finally:
        conn.close()
