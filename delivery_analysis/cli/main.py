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
from delivery_analysis.sync.runner import run_sync

NO_CONNECTORS_MESSAGE = (
    "No connectors are configured yet. Bitbucket, Jira, Confluence, and Claude usage "
    "connectors arrive in later specs."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delivery-analysis",
        description="Delivery analytics app: sync sources into SQLite and view them locally.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    serve = commands.add_parser("serve", help="Start the local web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8000, help="Port to listen on (default 8000)")
    serve.add_argument("--no-browser", action="store_true", help="Do not open the browser")

    sync = commands.add_parser("sync", help="Sync configured sources into the local database")
    sync.add_argument("--source", help="Only sync the connector with this name")

    commands.add_parser("doctor", help="Show which credential variables are present (names only)")
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
        results = run_sync(
            conn,
            active,
            overlap_days=settings.overlap_days,
            only=args.source,
            redact_values=secret_values(environ),
            log=print,
        )
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
    args = build_parser().parse_args(argv)
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
    if args.command == "serve":
        return _serve(args, settings)
    if args.command == "sync":
        return _sync(args, settings, env, connectors)
    code = _doctor(settings, env, path, connectors)
    return 1 if env_error else code


if __name__ == "__main__":
    raise SystemExit(main())
