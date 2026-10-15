from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

OUTPUT_DIR_ENV_VAR = "GITHUB_ANALYSIS_RESULTS"
DEFAULT_OUTPUT_DIR = Path.home() / "github-analysis-results"
DB_FILE_NAME = "delivery.sqlite"
CREDENTIAL_VARS = ("ATLASSIAN", "ANTHROPIC", "ANTHROPIC_ADMIN")


def parse_env_text(text: str) -> Dict[str, str]:
    """Parse KEY=VALUE lines. Handles comments, blanks, CRLF, `export `, and quoted values."""
    values: Dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def load_env_file(path: Path, environ: Optional[Dict[str, str]] = None) -> List[str]:
    """Load a .env file into environ without overriding variables already set.

    Returns the names that were loaded, never their values.
    """
    target = os.environ if environ is None else environ
    if not path.is_file():
        return []
    loaded: List[str] = []
    for name, value in parse_env_text(path.read_text(encoding="utf-8-sig")).items():
        if name not in target:
            target[name] = value
            loaded.append(name)
    return loaded


class Secret:
    """Holds a credential so that printing or logging it shows no value."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__


def credential_status(
    environ: Optional[Mapping[str, str]] = None,
    names: Iterable[str] = CREDENTIAL_VARS,
) -> Dict[str, bool]:
    env = os.environ if environ is None else environ
    return {name: bool((env.get(name) or "").strip()) for name in names}


def secret_values(
    environ: Optional[Mapping[str, str]] = None,
    names: Iterable[str] = CREDENTIAL_VARS,
) -> List[str]:
    env = os.environ if environ is None else environ
    return [env[name] for name in names if (env.get(name) or "").strip()]


def redact(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


@dataclass(frozen=True)
class Settings:
    db_path: Path
    report_tz: ZoneInfo = ZoneInfo("America/New_York")
    overlap_days: int = 7
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if environ is None else environ
        raw = (env.get(OUTPUT_DIR_ENV_VAR) or "").strip()
        base = Path(os.path.expanduser(raw)) if raw else DEFAULT_OUTPUT_DIR
        return cls(db_path=base / DB_FILE_NAME)
