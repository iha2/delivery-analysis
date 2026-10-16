from datetime import date

from token_world import World
from delivery_analysis.cli import tokens as tokens_cli
from delivery_analysis.cli.main import build_parser, main
from delivery_analysis.settings import Settings
from delivery_analysis.store import db
from delivery_analysis.sync import service
from delivery_analysis.sync.service import sync_and_reconcile


def world_db(tmp_path):
    path = tmp_path / "delivery.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    w = World(conn)
    ada = w.person("Ada Example")
    t1 = w.ticket("MD-1", assignee=ada, points=3).in_progress("2026-03-02")
    w.usage(ada, "2026-03-02", 1000)
    t1.completed("2026-03-06")
    return path, conn


def test_tokens_rebuild_through_main(tmp_path, capsys):
    path, conn = world_db(tmp_path)
    conn.close()
    env = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path)}
    assert main(["tokens", "rebuild"], env_path=tmp_path / "missing.env", environ=env) == 0
    assert "Claude cost: $10.00 across 1 people." in capsys.readouterr().out


def test_tokens_explain_prints_the_split(tmp_path, capsys):
    path, conn = world_db(tmp_path)
    conn.close()
    settings = Settings(db_path=path)
    today = lambda: date(2026, 3, 20)  # noqa: E731
    assert tokens_cli.run(build_parser().parse_args(["tokens", "rebuild"]), settings, today=today) == 0
    args = build_parser().parse_args(["tokens", "explain", "--person", "Ada Example", "--day", "2026-03-02"])
    assert tokens_cli.run(args, settings, today=today) == 0
    out = capsys.readouterr().out
    assert "MD-1" in out and "window_single" in out and "high" in out
    bad = build_parser().parse_args(["tokens", "explain", "--person", "Nobody", "--day", "2026-03-02"])
    assert tokens_cli.run(bad, settings, today=today) == 2


def test_sync_runs_the_rebuild_and_redacts_its_failure(tmp_path, monkeypatch):
    path, conn = world_db(tmp_path)
    settings = Settings(db_path=path)
    results, lines, failed = sync_and_reconcile(conn, [], settings, {})
    assert any(line.startswith("Claude cost: $10.00") for line in lines) and failed == 0

    def boom(*args, **kwargs):
        raise RuntimeError("broke near sk-ant-admin01-SECRET-VALUE")

    monkeypatch.setattr(service, "rebuild_tokens", boom)
    results, lines, failed = sync_and_reconcile(conn, [], settings, {"ANTHROPIC_ADMIN": "sk-ant-admin01-SECRET-VALUE"})
    assert any(line.startswith("Token attribution failed: broke near ***") for line in lines) and failed == 0
    conn.close()


def test_sync_without_claude_usage_adds_no_token_lines(conn, tmp_path):
    results, lines, failed = sync_and_reconcile(conn, [], Settings(db_path=tmp_path / "x.sqlite"), {})
    assert not any("Claude" in line for line in lines)


def test_no_connectors_message_lists_every_enabling_variable():
    from delivery_analysis.cli.main import NO_CONNECTORS_MESSAGE as text

    for name in ("BITBUCKET", "ATLASSIAN_EMAIL", "ANTHROPIC_ADMIN", "ANTHROPIC", "claude_code_analytics"):
        assert name in text
    assert "only Confluence is still to come" in text and "later specs" not in text
