from datetime import datetime, timedelta, timezone

import pytest

from delivery_analysis.cli.main import main
from delivery_analysis.model.records import Record
from delivery_analysis.store import db
from delivery_analysis.store.upsert import upsert_record


def day(days_ago):
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def home(tmp_path):
    connection = db.connect(tmp_path / "delivery.sqlite")
    db.migrate(connection)
    rows = [
        ("ann@corp.example", "Ann Example", day(3)),
        ("ann@partner.example", "Ann Example", day(4)),
        ("build-bot@corp.example", "Build Bot", day(2)),
        ("john@a.example", "John Smith", day(5)),
        ("john@b.example", "John Doe", day(6)),
    ]
    for number, (email, name, when) in enumerate(rows, start=1):
        upsert_record(
            connection,
            Record(
                "vcs_commit",
                {
                    "source": "bitbucket",
                    "source_id": f"c{number}",
                    "repository_id": "r1",
                    "author_email": email,
                    "author_name": name,
                    "committed_at": when,
                },
            ),
            "2026-10-15T00:00:00Z",
        )
    connection.close()
    return tmp_path


def run(args, home):
    return main(
        args,
        env_path=home / "missing.env",
        environ={"GITHUB_ANALYSIS_RESULTS": str(home)},
    )


def count(home, table):
    connection = db.connect(home / "delivery.sqlite")
    try:
        return connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    finally:
        connection.close()


def test_discover_prints_the_roster_and_saves_nothing(home, capsys):
    assert run(["teams", "discover", "--repo", "bitbucket:r1", "--since", "90d"], home) == 0
    out = capsys.readouterr().out
    assert "Ann Example" in out and "ann@corp.example" in out and "ann@partner.example" in out
    assert "Build Bot" in out and "[bot]" in out
    assert "possible duplicate" in out and "john@a.example" in out
    assert count(home, "team") == 0 and count(home, "person") == 0


def test_discover_with_save_creates_the_team_and_its_members(home, capsys):
    code = run(["teams", "discover", "--repo", "bitbucket:r1", "--save", "Core"], home)
    assert code == 0
    out = capsys.readouterr().out
    assert "Team Core" in out and "Ann Example" in out
    assert count(home, "team") == 1
    assert count(home, "team_member") == 4  # Ann, the bot (excluded), and the two Johns


def test_saving_the_same_name_twice_exits_2(home, capsys):
    run(["teams", "discover", "--repo", "bitbucket:r1", "--save", "Core"], home)
    capsys.readouterr()
    assert run(["teams", "discover", "--repo", "bitbucket:r1", "--save", "Core"], home) == 2
    assert "already exists" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args, message",
    [
        (["teams", "discover", "--repo", "bitbucket:r1", "--since", "ninety"], "--since"),
        (["teams", "discover", "--repo", "bitbucket:r1", "--since", "0d"], "--since"),
        (["teams", "discover", "--repo", "justaname"], "--repo"),
    ],
)
def test_bad_arguments_exit_2_with_a_plain_message(home, capsys, args, message):
    assert run(args, home) == 2
    assert message in capsys.readouterr().out


def test_no_commits_says_so(home, capsys):
    assert run(["teams", "discover", "--repo", "bitbucket:nothing-here"], home) == 0
    assert "No commits found" in capsys.readouterr().out


def test_teams_appears_in_the_top_level_help(capsys):
    with pytest.raises(SystemExit):
        main(["--help"], environ={})
    assert "teams" in capsys.readouterr().out
