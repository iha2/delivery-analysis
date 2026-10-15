from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn

from delivery_analysis import __version__
from delivery_analysis.app.server import create_app
from delivery_analysis.connectors.base import Connector
from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.settings import (
    CREDENTIAL_VARS,
    EnvFileError,
    Settings,
    credential_status,
    load_env_file,
    redact,
    secret_values,
)
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.cli import teams as teams_cli
from delivery_analysis.sync.runner import run_sync, utc_now_iso
from delivery_analysis.teams.reconcile import reconcile_all, stale_repo_keys
from github_analysis.cli.commands import COMMAND_REGISTRARS

NO_CONNECTORS_MESSAGE = (
    "No connectors are configured yet. Bitbucket, Jira, Confluence, and Claude usage "
    "connectors arrive in later specs."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delivery-analysis",
        description=(
            "Delivery analytics: sync sources into SQLite and view them in a local app, "
            "plus the GitHub pull-request monthly report.\n\n"
            "App commands:\n"
            "  serve     Start the local web app on 127.0.0.1\n"
            "  sync      Sync configured sources into the local database\n"
            "  doctor    Show which credential variables are present (names only)\n"
            "  teams     Discover, save, import and export team rosters\n\n"
            "GitHub report commands (need GitHub CLI `gh` authenticated with read access):\n"
            "  analyze   Fetch data from GitHub and write TSV reports\n"
            "  export    Convert TSV reports to Excel\n"
            "  run       Analyze + export in one step\n\n"
            "Run `delivery-analysis <command> --help` for command-specific options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=False)

    serve = commands.add_parser("serve", help="Start the local web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8000, help="Port to listen on (default 8000)")
    serve.add_argument("--no-browser", action="store_true", help="Do not open the browser")

    sync = commands.add_parser("sync", help="Sync configured sources into the local database")
    sync.add_argument("--source", help="Only sync the connector with this name")

    commands.add_parser("doctor", help="Show which credential variables are present (names only)")

    for register in COMMAND_REGISTRARS:
        register(commands)
    teams_cli.register(commands)
    return parser


def _serve(args: argparse.Namespace, settings: Settings) -> int:
    app = create_app(settings.db_path)
    url = f"http://{settings.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    print(f"Serving on {url} (local only). Press Ctrl+C to stop.")
    uvicorn.run(app, host=settings.host, port=args.port, log_level="info")
    return 0


def _sync(
    args: argparse.Namespace,
    settings: Settings,
    environ: Dict[str, str],
    connectors: Optional[List[Connector]],
) -> int:
    active = connectors if connectors is not None else build_connectors(settings, environ)
    if not active:
        print(NO_CONNECTORS_MESSAGE)
        return 0
    names = [connector.name for connector in active]
    if args.source and args.source not in names:
        print(f"No connector named {args.source!r}. Available: {', '.join(names)}")
        return 2
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        secrets = secret_values(environ)
        results = run_sync(
            conn,
            active,
            overlap_days=settings.overlap_days,
            only=args.source,
            redact_values=secrets,
            log=print,
        )
        try:
            for line in reconcile_all(conn, utc_now_iso(), stale_repo_keys(conn)):
                print(line)
        except Exception as exc:
            print("Team update failed: " + redact(str(exc) or exc.__class__.__name__, secrets))
    finally:
        conn.close()
    return 1 if any(result.status == "failed" for result in results) else 0


def default_env_path() -> Path:
    """The repo's .env when running from a checkout, otherwise `.env` in the current folder."""
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").is_file():
        return root / ".env"
    return Path.cwd() / ".env"


def _doctor(
    settings: Settings, environ: Dict[str, str], env_path: Path, connectors: Optional[List[Connector]]
) -> int:
    print(f".env: {env_path} ({'found' if env_path.is_file() else 'not found'})")
    for name, present in credential_status(environ, CREDENTIAL_VARS).items():
        print(f"{name}: {'present' if present else 'missing'}")
    secrets = secret_values(environ)
    active = connectors if connectors is not None else build_connectors(settings, environ)
    for connector in active:
        try:
            problems = connector.validate()
            status = "; ".join(problems) if problems else "ready"
        except Exception as exc:
            status = str(exc) or exc.__class__.__name__
        print(f"{connector.name}: {redact(status, secrets)}")
    print(f"Database: {settings.db_path}")
    return 0


def main(
    argv: Optional[List[str]] = None,
    *,
    env_path: Optional[Path] = None,
    environ: Optional[Dict[str, str]] = None,
    connectors: Optional[List[Connector]] = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    legacy_handler = getattr(args, "handler", None)
    if legacy_handler is not None:
        # analyze / export / run: the GitHub report commands keep their own behavior.
        return int(legacy_handler(args))
    env = os.environ if environ is None else environ
    path = default_env_path() if env_path is None else env_path
    env_error = False
    try:
        load_env_file(path, env)
    except EnvFileError as exc:
        print(str(exc), file=sys.stderr)
        if args.command != "doctor":
            return 2
        env_error = True
    settings = Settings.from_env(env)
    if args.command == "teams":
        return teams_cli.run(args, settings)
    if args.command == "serve":
        return _serve(args, settings)
    if args.command == "sync":
        return _sync(args, settings, env, connectors)
    code = _doctor(settings, env, path, connectors)
    return 1 if env_error else code


if __name__ == "__main__":
    raise SystemExit(main())
