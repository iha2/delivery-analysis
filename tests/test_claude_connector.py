from datetime import date

import httpx

from claude_fakes import KEY, PAGE_1, PAGE_2, transport
from delivery_analysis.cli.main import main
from delivery_analysis.connectors.claude_code.client import ClaudeCodeClient
from delivery_analysis.connectors.claude_code.connector import NOT_ADMIN, ClaudeCodeConnector
from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.settings import Settings
from delivery_analysis.sync.runner import run_sync

TODAY = date(2026, 3, 20)


def connector(tx, **kwargs):
    client = ClaudeCodeClient(KEY, transport=tx, sleep=lambda s: None, clock=lambda: 0.0)
    return ClaudeCodeConnector(client, today=lambda: TODAY, **kwargs)


def test_a_key_that_is_not_an_admin_key_is_reported_without_a_request():
    calls = []
    assert connector(transport({}, calls=calls), admin_key=False).validate() == [NOT_ADMIN]
    assert calls == []


def test_validate_probes_yesterday_and_reports_plain_errors():
    calls = []
    assert connector(transport({}, calls=calls)).validate() == []
    assert calls[0].url.params["starting_at"] == "2026-03-19" and calls[0].url.params["limit"] == "1"
    (problem,) = connector(transport({}, status=401)).validate()
    assert "rejected" in problem and KEY not in problem


def test_one_replacing_batch_per_day_and_the_cursor_only_for_complete_days():
    batches = list(connector(transport({"2026-03-17": [PAGE_1, PAGE_2]}), window_days=3).sync("org", None))
    assert [b.cursor for b in batches] == ["2026-03-17T00:00:00Z", "2026-03-18T00:00:00Z", None, None]
    assert batches[0].replace == [
        ("claude_usage_day", {"source": "claude_code_analytics", "day": "2026-03-17"}),
        ("claude_activity_day", {"source": "claude_code_analytics", "day": "2026-03-17"}),
    ]
    assert len(batches[0].records) == 7 and batches[1].records == []
    assert batches[0].raw[0].source_id == "2026-03-17" and KEY not in batches[0].raw[0].json


def test_since_starts_from_the_cursor_day():
    batches = list(connector(transport({})).sync("org", "2026-03-15T00:00:00Z"))
    assert batches[0].raw[0].source_id == "2026-03-15" and len(batches) == 6


def test_a_repulled_day_drops_an_actor_that_vanished(conn):
    first = connector(transport({"2026-03-17": [PAGE_1, PAGE_2]}), window_days=3)
    run_sync(conn, [first])
    assert conn.execute("SELECT COUNT(DISTINCT actor) FROM claude_usage_day").fetchone()[0] == 3
    revised = dict(PAGE_1, has_more=False, next_page=None)
    run_sync(conn, [connector(transport({"2026-03-17": [revised]}), window_days=3)])
    actors = [r[0] for r in conn.execute("SELECT DISTINCT actor FROM claude_usage_day ORDER BY actor")]
    assert actors == ["ada@corp.example"]


def test_building_the_connector_makes_no_request(tmp_path):
    calls = []
    settings = Settings(db_path=tmp_path / "d.sqlite")
    built = build_connectors(settings, {"ANTHROPIC_ADMIN": KEY}, transport=transport({}, calls=calls))
    assert [c.name for c in built] == ["claude_code_analytics"] and calls == []
    assert build_connectors(settings, {}) == []
    (plain,) = build_connectors(settings, {"ANTHROPIC": "sk-ant-api03-not-admin"}, transport=transport({}))
    assert plain.validate() == [NOT_ADMIN]


def test_the_key_never_reaches_output_or_the_database(tmp_path, capsys):
    env = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path), "ANTHROPIC_ADMIN": KEY}
    code = main(["sync", "--source", "claude_code_analytics"], env_path=tmp_path / "missing.env",
                environ=env, transport=transport({}, status=401))
    assert code == 1
    out = capsys.readouterr()
    assert KEY not in out.out and KEY not in out.err
    for path in tmp_path.glob("delivery.sqlite*"):
        assert KEY.encode("utf-8") not in path.read_bytes()
