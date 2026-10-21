from pathlib import Path

from delivery_analysis.app import refresh
from delivery_analysis.code.build import CodeBuildResult
from delivery_analysis.metrics.impact_build import ImpactSummary
from delivery_analysis.settings import Settings
from delivery_analysis.sync import service

SUMMARY = ImpactSummary(tickets=2, prs_valued=1, prs_without_files=0, fixes=0)


def settings(tmp_path=None):
    return Settings(db_path=Path("unused.sqlite") if tmp_path is None else tmp_path / "d.sqlite")


def test_sync_builds_code_without_fetching_then_rebuilds_impact(conn, monkeypatch):
    calls = []

    def fake_build(connection, cfg, environ, **kwargs):
        calls.append(("build", kwargs.get("fetch")))
        return CodeBuildResult(lines=["ws/slug: 1 files weighed, 0 commits read, 0 commits missing, 0 merges skipped"])

    def fake_rebuild(connection, now):
        calls.append(("impact", None))
        return SUMMARY

    monkeypatch.setattr(service, "build_code", fake_build)
    monkeypatch.setattr(service, "rebuild_impact", fake_rebuild)
    _, lines, failed = service.sync_and_reconcile(conn, [], settings(), {})
    assert calls == [("build", False), ("impact", None)]
    assert failed == 0
    assert any("files weighed" in line for line in lines)
    assert any(line == SUMMARY.lines()[0] for line in lines)


def test_an_exception_in_either_step_is_a_redacted_line_and_the_sync_survives(conn, monkeypatch):
    def boom_build(*args, **kwargs):
        raise RuntimeError("clone said tok-XYZ")

    def boom_impact(*args, **kwargs):
        raise RuntimeError("bad sum tok-XYZ")

    monkeypatch.setattr(service, "build_code", boom_build)
    monkeypatch.setattr(service, "rebuild_impact", boom_impact)
    results, lines, failed = service.sync_and_reconcile(conn, [], settings(), {"ATLASSIAN": "tok-XYZ"})
    assert "Code build failed: clone said ***" in lines
    assert "Impact build failed: bad sum ***" in lines
    assert results == [] and failed == 0


def test_a_source_that_does_not_feed_impact_skips_it(conn, monkeypatch):
    called = []
    monkeypatch.setattr(service, "build_code", lambda *a, **k: called.append("build"))
    monkeypatch.setattr(service, "rebuild_impact", lambda *a, **k: called.append("impact"))
    service.sync_and_reconcile(conn, [], settings(), {}, only="claude_code_analytics")
    assert called == []


def test_the_real_impact_rebuild_runs_on_an_empty_store(conn):
    _, lines, failed = service.sync_and_reconcile(conn, [], settings(), {})
    assert failed == 0 and not any("failed" in line for line in lines)


class _Fake:
    name = "bitbucket"


def _refresh(tmp_path, monkeypatch, environ, lines):
    seen = {}

    def fake_sync(conn, connectors, cfg, env, **kwargs):
        seen.update(kwargs)
        return [], lines, 0

    monkeypatch.setattr(refresh, "build_connectors", lambda *a, **k: [_Fake()])
    monkeypatch.setattr(refresh, "sync_and_reconcile", fake_sync)
    text = refresh.sync_runner(tmp_path / "d.sqlite", settings(tmp_path), environ)(None, False)
    return seen, text


def test_refresh_asks_the_sync_to_fetch_the_clone_when_a_token_exists(tmp_path, monkeypatch):
    seen, text = _refresh(tmp_path, monkeypatch, {"BITBUCKET": "tok-XYZ"}, ["ws/slug: code build failed: nope"])
    assert seen["fetch_code"] is True
    assert "ws/slug: code build failed: nope" in text


def test_refresh_without_a_token_does_not_fetch(tmp_path, monkeypatch):
    seen, _ = _refresh(tmp_path, monkeypatch, {}, [])
    assert seen["fetch_code"] is False


def test_fetch_code_without_a_token_falls_back_to_no_fetch(tmp_path, conn, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "build_code", lambda c, s, e, **k: calls.append(k.get("fetch")) or CodeBuildResult())
    monkeypatch.setattr(service, "rebuild_impact", lambda c, n: SUMMARY)
    service.sync_and_reconcile(conn, [], settings(), {}, fetch_code=True)
    assert calls == [False]


def test_delivered_dates_are_derived_before_the_impact_rebuild_and_a_failure_never_fails_the_sync(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(service, "build_code", lambda *a, **k: CodeBuildResult(lines=[]))
    monkeypatch.setattr(service, "rebuild_impact", lambda c, now: calls.append("impact") or SUMMARY)
    monkeypatch.setattr(
        service, "derive_delivered", lambda c, statuses=None: calls.append(("derive", tuple(statuses))) or 0
    )
    service.sync_and_reconcile(conn, [], settings(), {"DELIVERED_STATUSES": "Shipped"})
    assert calls == [("derive", ("Shipped",)), "impact"]

    def boom(*args, **kwargs):
        raise RuntimeError("bad date tok-XYZ")

    monkeypatch.setattr(service, "derive_delivered", boom)
    _, lines, failed = service.sync_and_reconcile(conn, [], settings(), {"ATLASSIAN": "tok-XYZ"})
    assert "Delivered date update failed: bad date ***" in lines and failed == 0
