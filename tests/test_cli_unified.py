import re
from pathlib import Path

import pytest

from delivery_analysis.cli.main import main

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_help(args, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(args, env_path=REPO_ROOT / "missing.env", environ={})
    assert exit_info.value.code == 0
    return capsys.readouterr().out


def test_top_level_help_lists_every_command(capsys):
    output = run_help(["--help"], capsys)
    for command in ("serve", "sync", "doctor", "analyze", "export", "run"):
        assert command in output
    assert "delivery-analysis" in output


@pytest.mark.parametrize("command", ["analyze", "export", "run"])
def test_github_report_commands_are_available_under_the_new_name(command, capsys):
    output = run_help([command, "--help"], capsys)
    assert "delivery-analysis " + command in output
    assert "github-analysis" not in output.replace("github-analysis-results", "")


def test_no_command_prints_help_and_succeeds(capsys):
    assert main([], env_path=REPO_ROOT / "missing.env", environ={}) == 0
    assert "serve" in capsys.readouterr().out


def test_old_command_is_removed_from_the_package_scripts():
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    scripts = re.search(r"\[project\.scripts\](.*?)(?:\n\[|\Z)", text, re.S).group(1)
    assert "delivery-analysis" in scripts
    assert "github-analysis" not in scripts


def test_production_scripts_call_the_new_command():
    for name in ("run_monthly_report.sh", "scripts/run_cedt_trio.sh", "scripts/run_monthly.sh"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"github-analysis(?![-\w])", text), name
