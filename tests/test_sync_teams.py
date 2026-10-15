from datetime import datetime, timedelta, timezone

from delivery_analysis.cli.main import main
from delivery_analysis.connectors.fake import FakeConnector
from delivery_analysis.model.records import Batch, Record
from delivery_analysis.store import db
from delivery_analysis.store.upsert import upsert_record
from delivery_analysis.teams.reconcile import create_team, reconcile_team


def stamp(days_ago):
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def commit(number, email, name, when, source="fake", repo="main"):
    return Record(
        "vcs_commit",
        {
            "source": source,
            "source_id": f"c{number}",
            "repository_id": repo,
            "author_email": email,
            "author_name": name,
            "committed_at": when,
        },
    )


def prepare(tmp_path):
    """A team whose only member, Ann, last committed years ago and is active."""
    connection = db.connect(tmp_path / "delivery.sqlite")
    db.migrate(connection)
    upsert_record(connection, commit(1, "ann@corp.example", "Ann Example", "2020-01-01T00:00:00Z"), "2020-01-02T00:00:00Z")
    team_id = create_team(connection, "Core", [("fake", "main")], 90, now="2020-02-01T00:00:00Z")
    reconcile_team(connection, team_id, "2020-02-01T00:00:00Z")
    connection.close()


def roster(tmp_path):
    connection = db.connect(tmp_path / "delivery.sqlite")
    try:
        rows = connection.execute(
            "SELECT p.display_name AS name, m.status AS status FROM team_member m "
            "JOIN person p ON p.person_id = m.person_id ORDER BY p.display_name"
        ).fetchall()
        return {row["name"]: row["status"] for row in rows}
    finally:
        connection.close()


def run_sync(tmp_path, connector):
    return main(
        ["sync"],
        env_path=tmp_path / "missing.env",
        environ={"GITHUB_ANALYSIS_RESULTS": str(tmp_path)},
        connectors=[connector],
    )


def test_a_healthy_sync_adds_new_committers_and_retires_silent_ones(tmp_path, capsys):
    prepare(tmp_path)
    batch = Batch([commit(2, "bob@corp.example", "Bob Builder", stamp(1))], cursor=stamp(0))
    assert run_sync(tmp_path, FakeConnector(batches={"main": [batch]})) == 0
    assert roster(tmp_path) == {"Ann Example": "inactive", "Bob Builder": "active"}
    assert "Team Core" in capsys.readouterr().out


def test_a_failed_source_does_not_retire_anyone(tmp_path, capsys):
    prepare(tmp_path)
    connection = db.connect(tmp_path / "delivery.sqlite")
    upsert_record(connection, commit(2, "bob@corp.example", "Bob Builder", stamp(1)), stamp(0))
    connection.close()
    failing = FakeConnector(batches={"main": [Batch([])]}, fail_on_batch=0, fail_message="source down")
    assert run_sync(tmp_path, failing) == 1
    assert roster(tmp_path) == {"Ann Example": "active", "Bob Builder": "active"}
    assert "stale" in capsys.readouterr().out


def test_a_sync_limited_to_another_source_leaves_the_team_alone(tmp_path):
    prepare(tmp_path)
    connection = db.connect(tmp_path / "delivery.sqlite")
    upsert_record(connection, commit(2, "bob@corp.example", "Bob Builder", stamp(1)), stamp(0))
    connection.close()
    other = FakeConnector(name="other", batches={"main": [Batch([])]})
    fake = FakeConnector(batches={"main": [Batch([])]})
    code = main(
        ["sync", "--source", "other"],
        env_path=tmp_path / "missing.env",
        environ={"GITHUB_ANALYSIS_RESULTS": str(tmp_path)},
        connectors=[other, fake],
    )
    assert code == 0
    assert roster(tmp_path) == {"Ann Example": "active"}


def test_a_connector_level_failure_does_not_retire_anyone(tmp_path):
    prepare(tmp_path)
    connection = db.connect(tmp_path / "delivery.sqlite")
    upsert_record(connection, commit(2, "bob@corp.example", "Bob Builder", stamp(1)), stamp(0))
    connection.close()
    broken = FakeConnector(problems=["token missing"])
    assert run_sync(tmp_path, broken) == 1
    assert roster(tmp_path) == {"Ann Example": "active", "Bob Builder": "active"}


def test_a_failing_team_makes_the_sync_exit_1_and_names_the_team(tmp_path, capsys, monkeypatch):
    import delivery_analysis.teams.reconcile as reconcile_module

    prepare(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("cannot reach tok-SECRET-999")

    monkeypatch.setattr(reconcile_module, "reconcile_team", boom)
    batch = Batch([commit(2, "bob@corp.example", "Bob Builder", stamp(1))], cursor=stamp(0))
    code = main(
        ["sync"],
        env_path=tmp_path / "missing.env",
        environ={"GITHUB_ANALYSIS_RESULTS": str(tmp_path), "ATLASSIAN": "tok-SECRET-999"},
        connectors=[FakeConnector(batches={"main": [batch]})],
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "Team Core: FAILED" in out
    assert "tok-SECRET-999" not in out
