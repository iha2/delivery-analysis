from __future__ import annotations

import argparse
import subprocess
from typing import Any, Callable, Mapping

from delivery_analysis.cli.repos import _source_and_text
from delivery_analysis.code.build import bitbucket_url, build_code
from delivery_analysis.metrics.impact_build import rebuild_impact
from delivery_analysis.settings import Settings, redact, secret_values
from delivery_analysis.store.db import connect, migrate
from delivery_analysis.sync.runner import utc_now_iso

NO_TOKEN_MESSAGE = (
    "BITBUCKET is not set. Put your Atlassian API token in .env as BITBUCKET so the code can be cloned."
)


def register(commands) -> None:
    code = commands.add_parser("code", help="Clone repositories and build code-weighted impact")
    actions = code.add_subparsers(dest="code_command", metavar="<action>", required=True)
    build = actions.add_parser("build", help="Clone or fetch each selected repository, weigh files, rebuild impact")
    build.add_argument("--repo", metavar="bitbucket:REPO", help="Only this repository (default: every selected one)")


def run(
    args: argparse.Namespace,
    settings: Settings,
    environ: Mapping[str, str],
    *,
    run: Callable[..., Any] = subprocess.run,
    url_for: Callable[[str, str], str] = bitbucket_url,
) -> int:
    if not (environ.get("BITBUCKET") or "").strip():
        print(NO_TOKEN_MESSAGE)
        return 1
    secrets = secret_values(environ)
    conn = connect(settings.db_path)
    try:
        migrate(conn)
        repo = _source_and_text(args.repo) if args.repo else None
        result = build_code(
            conn, settings, environ, repo=repo, fetch=True, run=run, url_for=url_for,
            log=lambda line: print(line),
        )
        try:
            for line in rebuild_impact(conn, utc_now_iso()).lines():
                print(redact(line, secrets))
            conn.commit()
        except Exception as exc:
            print(redact("Impact build failed: " + (str(exc) or exc.__class__.__name__), secrets))
            return 1
        return 1 if result.failed else 0
    except ValueError as exc:
        print(redact(str(exc), secrets))
        return 2
    finally:
        conn.close()
