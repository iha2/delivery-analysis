from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

from delivery_analysis.teams.reconcile import create_team, new_id

Repo = Tuple[str, str]
Member = Tuple[str, List[str], str]  # (name, emails, github user)


class TeamsFileError(ValueError):
    """A teams file that cannot be read or is not valid; the message is safe to print."""


def _load(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix not in (".json", ".yaml", ".yml"):
        raise TeamsFileError(f"{path} must be a .json, .yaml or .yml file.")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise TeamsFileError(f"Could not read {path}: {exc.strerror or exc.__class__.__name__}.") from None
    if suffix == ".json":
        try:
            data = json.loads(text)
        except ValueError:
            raise TeamsFileError(f"{path} is not valid JSON.") from None
    else:
        try:
            import yaml
        except ImportError:
            raise TeamsFileError(
                "Reading .yaml needs PyYAML (uv sync --group excel); or use a .json file."
            ) from None
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError:
            raise TeamsFileError(f"{path} is not valid YAML.") from None
    if not isinstance(data, dict) or not isinstance(data.get("teams"), list):
        raise TeamsFileError(f"{path} must contain a 'teams' list.")
    return data


def _parse(data: Dict[str, Any]) -> List[Tuple[str, List[Member]]]:
    teams: List[Tuple[str, List[Member]]] = []
    for index, raw in enumerate(data["teams"]):
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            raise TeamsFileError(f"teams[{index}] needs a name.")
        name = str(raw["name"]).strip()
        members: List[Member] = []
        for member in raw.get("members") or []:
            if not isinstance(member, dict):
                raise TeamsFileError(f"{name}: each member must be an object.")
            member_name = str(member.get("name") or "").strip()
            emails = [str(e).strip().lower() for e in (member.get("emails") or []) if str(e).strip()]
            user = str(member.get("user") or "").strip()
            if not member_name or not (emails or user):
                label = member_name or "(no name)"
                raise TeamsFileError(f"{name}: member {label!r} needs a name and emails or user.")
            members.append((member_name, emails, user))
        teams.append((name, members))
    return teams


def _import_member(
    conn: sqlite3.Connection, team_id: str, member: Member, now: str, make_id: Callable[[], str]
) -> None:
    name, emails, user = member
    keys = [("email", email) for email in emails] + ([("github", user)] if user else [])
    conn.execute("BEGIN IMMEDIATE")
    try:
        clause = " OR ".join("(source = ? AND account_id = ?)" for _ in keys)
        rows = conn.execute(
            f"SELECT person_id FROM identity WHERE person_id IS NOT NULL AND ({clause})",
            [value for key in keys for value in key],
        ).fetchall()
        ids = sorted({row["person_id"] for row in rows})
        if ids:
            person_id = ids[0]
        else:
            person_id = make_id()
            conn.execute(
                "INSERT INTO person (person_id, display_name, manual) VALUES (?, ?, 1)",
                (person_id, name),
            )
        for source, account in keys:
            conn.execute(
                "INSERT INTO identity (source, account_id, person_id, manual) VALUES (?, ?, ?, 1) "
                "ON CONFLICT(source, account_id) DO UPDATE SET person_id = excluded.person_id, manual = 1",
                (source, account, person_id),
            )
        conn.execute(
            "INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit, pinned, manual) "
            "VALUES (?, ?, 'active', ?, NULL, 0, 0) ON CONFLICT(team_id, person_id) DO NOTHING",
            (team_id, person_id, now[:10]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def import_teams(
    conn: sqlite3.Connection,
    path: Path,
    repos: Sequence[Repo],
    now: str,
    make_id: Callable[[], str] = new_id,
) -> List[str]:
    teams = _parse(_load(Path(path)))  # validate the whole file before writing anything
    lines: List[str] = []
    for name, members in teams:
        row = conn.execute("SELECT team_id FROM team WHERE name = ?", (name,)).fetchone()
        if row is None:
            team_id = create_team(conn, name, repos, 90, now=now, make_id=make_id)
        else:
            team_id = row["team_id"]
            for source, repository_id in repos:
                conn.execute(
                    "INSERT OR IGNORE INTO team_repo (team_id, repository_source, repository_id) "
                    "VALUES (?, ?, ?)",
                    (team_id, source, repository_id),
                )
        for member in members:
            _import_member(conn, team_id, member, now, make_id)
        lines.append(f"Team {name}: {len(members)} member(s) imported")
    return lines


def export_teams(conn: sqlite3.Connection, path: Path, team_name: str = "") -> str:
    path = Path(path)
    if path.suffix.lower() not in (".json", ".yaml", ".yml"):
        raise TeamsFileError(f"{path} must be a .json, .yaml or .yml file.")
    if team_name:
        teams = conn.execute("SELECT team_id, name FROM team WHERE name = ?", (team_name,)).fetchall()
        if not teams:
            raise TeamsFileError(f"No team named {team_name!r}.")
    else:
        teams = conn.execute("SELECT team_id, name FROM team ORDER BY name").fetchall()
    out: List[Dict[str, Any]] = []
    for team in teams:
        entries: List[Dict[str, Any]] = []
        members = conn.execute(
            "SELECT p.person_id AS pid, p.display_name AS name FROM team_member m "
            "JOIN person p ON p.person_id = m.person_id "
            "WHERE m.team_id = ? AND m.status = 'active' ORDER BY lower(p.display_name)",
            (team["team_id"],),
        ).fetchall()
        for member in members:
            entry: Dict[str, Any] = {"name": member["name"]}
            emails = [
                row["account_id"]
                for row in conn.execute(
                    "SELECT account_id FROM identity WHERE source = 'email' AND person_id = ? "
                    "ORDER BY account_id",
                    (member["pid"],),
                )
            ]
            if emails:
                entry["emails"] = emails
            github = conn.execute(
                "SELECT account_id FROM identity WHERE source = 'github' AND person_id = ? LIMIT 1",
                (member["pid"],),
            ).fetchone()
            if github:
                entry["user"] = github["account_id"]
            entries.append(entry)
        out.append({"name": team["name"], "members": entries})
    payload = {"teams": out}
    if path.suffix.lower() == ".json":
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        try:
            import yaml
        except ImportError:
            raise TeamsFileError(
                "Writing .yaml needs PyYAML (uv sync --group excel); or use a .json file."
            ) from None
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    return f"Exported {len(out)} team(s) to {path}"
