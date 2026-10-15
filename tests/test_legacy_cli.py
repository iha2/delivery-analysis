import pytest

from github_analysis.cli.main import main


def test_help_lists_the_three_commands(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    for command in ("analyze", "export", "run"):
        assert command in output


def test_no_arguments_prints_help_and_succeeds(capsys):
    assert main([]) == 0
    assert "delivery-analysis" in capsys.readouterr().out


def test_output_dir_rule_still_works_through_the_old_path(monkeypatch, tmp_path):
    from github_analysis.config import resolve_output_dir

    monkeypatch.setenv("GITHUB_ANALYSIS_RESULTS", str(tmp_path))
    assert resolve_output_dir(None) == str(tmp_path)
    assert resolve_output_dir("~/elsewhere").endswith("elsewhere")
