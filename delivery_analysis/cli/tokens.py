from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from typing import Callable

from delivery_analysis.settings import Settings
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.tokens.explain import explain, explain_lines, find_person
from delivery_analysis.tokens.rebuild import RebuildError, rebuild


def _today() -> date:
    return datetime.now(timezone.utc).date()


def register(commands: "argparse._SubParsersAction") -> None:
    tokens = commands.add_parser("tokens", help="Rebuild or explain Claude cost attribution")
    actions = tokens.add_subparsers(dest="tokens_command", metavar="<action>")
    actions.required = True
    actions.add_parser("rebuild", help="Recompute token usage, attribution and credit from stored data")
    detail = actions.add_parser("explain", help="Show how one person's day of Claude cost was attributed")
    detail.add_argument("--person", required=True, help="Person id or display name")
    detail.add_argument("--day", required=True, help="UTC day, YYYY-MM-DD")


def run(args: argparse.Namespace, settings: Settings, today: Callable[[], date] = _today) -> int:
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        if args.tokens_command == "rebuild":
            try:
                summary = rebuild(conn, today(), window_days=settings.window_days)
            except RebuildError as exc:
                print(str(exc))
                return 1
            for line in summary.lines():
                print(line)
            return 0
        try:
            day = date.fromisoformat(args.day).isoformat()
        except ValueError:
            print("Give --day as YYYY-MM-DD (a UTC day).")
            return 2
        try:
            person = find_person(conn, args.person)
        except LookupError as exc:
            print(str(exc))
            return 2
        for line in explain_lines(explain(conn, person, day)):
            print(line)
        return 0
    finally:
        conn.close()
