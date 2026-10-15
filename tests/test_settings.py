from pathlib import Path

from delivery_analysis import settings as s


def test_parse_env_text_handles_windows_editor_output():
    text = (
        "# comment\r\n"
        "\r\n"
        "ATLASSIAN=abc=def\r\n"
        'ANTHROPIC="quoted value"\r\n'
        "export ANTHROPIC_ADMIN='single'\r\n"
        "NOEQUALS\r\n"
        "TOKEN_WITH_HASH=abc#123\r\n"
    )
    parsed = s.parse_env_text(text)
    assert parsed == {
        "ATLASSIAN": "abc=def",
        "ANTHROPIC": "quoted value",
        "ANTHROPIC_ADMIN": "single",
        "TOKEN_WITH_HASH": "abc#123",
    }


def test_load_env_file_reads_a_bom_file_and_never_overrides(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_bytes("﻿ATLASSIAN=from-file\r\nANTHROPIC=from-file\r\n".encode("utf-8"))
    environ = {"ANTHROPIC": "already-set"}
    loaded = s.load_env_file(env_file, environ)
    assert loaded == ["ATLASSIAN"]
    assert environ == {"ANTHROPIC": "already-set", "ATLASSIAN": "from-file"}


def test_load_env_file_missing_file_is_fine(tmp_path):
    assert s.load_env_file(tmp_path / "nope.env", {}) == []


def test_secret_never_shows_its_value():
    secret = s.Secret("sk-live-123")
    assert "sk-live-123" not in repr(secret)
    assert "sk-live-123" not in str(secret)
    assert secret.reveal() == "sk-live-123"


def test_credential_status_reports_names_only():
    status = s.credential_status({"ATLASSIAN": "x", "ANTHROPIC": "  "})
    assert status == {"ATLASSIAN": True, "ANTHROPIC": False, "ANTHROPIC_ADMIN": False}


def test_redact_removes_every_secret():
    text = "failed with sk-live-123 and also tok-9"
    assert s.redact(text, ["sk-live-123", "tok-9", ""]) == "failed with *** and also ***"


def test_secret_values_lists_only_present_values():
    assert s.secret_values({"ATLASSIAN": "a", "OTHER": "b"}) == ["a"]


def test_settings_defaults_use_the_home_results_folder():
    settings = s.Settings.from_env({})
    assert settings.db_path == Path.home() / "github-analysis-results" / "delivery.sqlite"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.overlap_days == 7
    assert str(settings.report_tz) == "America/New_York"


def test_settings_output_dir_env_var_wins(tmp_path):
    settings = s.Settings.from_env({"GITHUB_ANALYSIS_RESULTS": str(tmp_path)})
    assert settings.db_path == tmp_path / "delivery.sqlite"
