import pytest

from delivery_analysis.cli.main import main
from delivery_analysis.connectors.fake import FakeConnector
from delivery_analysis.model.records import Batch, Record


def make_env(tmp_path, **extra):
    env = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path)}
    env.update(extra)
    return env


def run(args, tmp_path, env=None, connectors=None, env_file=None):
    return main(
        args,
        env_path=env_file or (tmp_path / "missing.env"),
        environ=env if env is not None else make_env(tmp_path),
        connectors=connectors,
    )


def test_doctor_lists_names_and_never_values(tmp_path, capsys):
    env = make_env(tmp_path, ATLASSIAN="super-secret-token")
    assert run(["doctor"], tmp_path, env) == 0
    out = capsys.readouterr().out
    assert "ATLASSIAN: present" in out
    assert "ANTHROPIC: missing" in out
    assert "ANTHROPIC_ADMIN: missing" in out
    assert "super-secret-token" not in out


def test_doctor_reads_the_env_file_without_printing_it(tmp_path, capsys):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC=from-the-file\r\n", encoding="utf-8")
    assert run(["doctor"], tmp_path, env_file=env_file) == 0
    out = capsys.readouterr().out
    assert "ANTHROPIC: present" in out
    assert "from-the-file" not in out


def test_sync_with_no_connectors_says_so_plainly(tmp_path, capsys):
    assert run(["sync"], tmp_path) == 0
    assert "No connectors are configured yet" in capsys.readouterr().out


def test_sync_runs_injected_connectors(tmp_path, capsys):
    record = Record("work_item", {"source": "fake", "source_id": "1"})
    fake = FakeConnector(batches={"main": [Batch([record], cursor="c1")]})
    assert run(["sync"], tmp_path, connectors=[fake]) == 0
    assert "fake/main: ok" in capsys.readouterr().out


def test_sync_exit_code_is_1_when_a_source_fails_and_the_token_is_hidden(tmp_path, capsys):
    env = make_env(tmp_path, ATLASSIAN="tok-ABC-123")
    fake = FakeConnector(batches={"main": [Batch([])]}, fail_on_batch=0, fail_message="denied tok-ABC-123")
    assert run(["sync"], tmp_path, env, connectors=[fake]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "tok-ABC-123" not in out


def test_sync_with_an_unknown_source_name_exits_2(tmp_path, capsys):
    fake = FakeConnector()
    assert run(["sync", "--source", "nope"], tmp_path, connectors=[fake]) == 2
    assert "No connector named 'nope'" in capsys.readouterr().out


def test_serve_has_no_host_option(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        run(["serve", "--host", "0.0.0.0"], tmp_path)
    assert exit_info.value.code == 2


def test_serve_binds_to_localhost_only(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: captured.update(kwargs))
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    assert run(["serve", "--no-browser", "--port", "8123"], tmp_path) == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8123
    assert opened == []
