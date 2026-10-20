from pathlib import Path

from delivery_analysis.cli import code as code_cli
from delivery_analysis.cli.main import build_parser, main
from delivery_analysis.settings import Settings
from delivery_analysis.store import repo_selection
from delivery_analysis.store.db import connect, migrate
from impact_seed import issue, link_pr
from metrics_seed import NOW, OTHER, REPO, pr
from tests.git_fakes import make_repo, shas

TOKEN = "tok-SECRET"


def _origin(tmp_path, name="origin"):
    return make_repo(
        tmp_path,
        [
            {"files": {"src/a.py": "import b\n", "src/b.py": "x = 1\n"}},
            {"files": {"src/a.py": "import b\nprint(b)\n"}},
        ],
        name=name,
    )


def _seed(conn, origin):
    repo_selection.add_repo(conn, "bitbucket", REPO, "ws", "slug", NOW)
    sid = pr(conn, 1, "acc-ann", "MERGED", "2026-09-07T09:00:00Z", "2026-09-09T12:00:00Z")
    issue(conn, "T", "acc-ann", resolved="2026-09-10T12:00:00Z", started="2026-09-07T12:00:00Z", points=5)
    link_pr(conn, 1, "T")
    for sha in shas(origin):
        conn.execute(
            "INSERT INTO vcs_commit (source, source_id, repository_id, sha, author_account, committed_at, "
            "change_request_id, fetched_at) VALUES ('bitbucket', ?, ?, ?, 'acc-ann', ?, ?, ?)",
            (REPO + ":" + sha, REPO, sha, "2026-09-08T09:00:00Z", sid, NOW),
        )
    conn.commit()


def _run(tmp_path, argv, environ, url_for):
    settings = Settings(db_path=tmp_path / "teams.sqlite")
    args = build_parser().parse_args(argv)
    return code_cli.run(args, settings, environ, url_for=url_for)


def test_build_writes_files_commits_and_impact(tmp_path, conn, capsys):
    origin = _origin(tmp_path)
    _seed(conn, origin)
    code = _run(tmp_path, ["code", "build"], {"BITBUCKET": TOKEN}, lambda ws, slug: str(origin))
    out = capsys.readouterr().out
    assert code == 0
    assert "ws/slug: 2 files weighed, 2 commits read, 0 commits missing, 0 merges skipped" in out
    assert "Impact" in out or "ticket" in out.lower()
    assert conn.execute("SELECT COUNT(*) AS n FROM code_file").fetchone()["n"] == 2
    assert conn.execute("SELECT COUNT(*) AS n FROM commit_file").fetchone()["n"] >= 3
    assert conn.execute("SELECT COUNT(*) AS n FROM impact_share").fetchone()["n"] >= 1
    assert TOKEN not in out


def test_repo_option_limits_the_build(tmp_path, conn, capsys):
    origin = _origin(tmp_path)
    _seed(conn, origin)
    repo_selection.add_repo(conn, "bitbucket", OTHER, "ws", "other", NOW)
    conn.commit()
    urls = []

    def url_for(ws, slug):
        urls.append(slug)
        return str(origin)

    assert _run(tmp_path, ["code", "build", "--repo", "bitbucket:ws/slug"], {"BITBUCKET": TOKEN}, url_for) == 0
    assert urls == ["slug"]


def test_missing_token_is_a_plain_message(tmp_path, conn, capsys):
    settings_env = {"BITBUCKET": "", "GITHUB_ANALYSIS_RESULTS": str(tmp_path)}
    code = main(["code", "build"], env_path=tmp_path / "none.env", environ=settings_env)
    out = capsys.readouterr().out
    assert code == 1
    assert "BITBUCKET is not set" in out


def test_a_failing_repo_is_redacted_and_the_others_continue(tmp_path, conn, capsys):
    origin = _origin(tmp_path)
    _seed(conn, origin)
    repo_selection.add_repo(conn, "bitbucket", OTHER, "aaa", "bad", NOW)
    conn.commit()

    def url_for(ws, slug):
        return str(tmp_path / ("missing-" + TOKEN)) if slug == "bad" else str(origin)

    code = _run(tmp_path, ["code", "build"], {"BITBUCKET": TOKEN}, url_for)
    out = capsys.readouterr().out
    assert code == 1
    assert TOKEN not in out
    assert "aaa/bad: code build failed" in out and "***" in out
    assert "ws/slug: 2 files weighed" in out
    assert Path(tmp_path / "code").is_dir()
