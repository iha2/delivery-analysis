"""Build small throwaway git repositories for tests (made-up people only)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

ADA = "Ada Example <ada@dev.example>"
BO = "Bo Example <bo@dev.example>"


def git(repo: Path, *args: str, author: str = ADA) -> str:
    name, email = author[:-1].split(" <")
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
    )
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=True,
    )
    return proc.stdout.strip()


def make_repo(tmp_path: Path, commits: Optional[List[dict]] = None, name: str = "origin") -> Path:
    """Create a repo on branch main. Each commit: {files: {path: text|bytes|None}, author, message}.

    A None value deletes the file. Returns the repo path.
    """
    repo = Path(tmp_path) / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    for index, spec in enumerate(commits or []):
        files: Dict[str, object] = spec.get("files", {})
        for rel, content in files.items():
            target = repo / rel
            if content is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_bytes(str(content).encode("utf-8"))
        git(repo, "add", "-A")
        git(
            repo,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            spec.get("message", "commit %d" % index),
            author=spec.get("author", ADA),
        )
    return repo


def shas(repo: Path) -> List[str]:
    """Commit shas on the current branch, oldest first."""
    return git(repo, "rev-list", "--reverse", "HEAD").splitlines()
