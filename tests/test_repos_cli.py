import pytest

from bitbucket_fakes import FakeBitbucket, commit, pr, recent
from delivery_analysis.cli.main import main
from delivery_analysis.store import db

UUID = "{11111111-1111-1111-1111-111111111111}"


@pytest.fixture
def fake():
    api = FakeBitbucket()
    api.add_repo(
        "movedocs_v1.0", UUID,
        commits=[commit("h1", "Ann Example <ann@corp.example>", recent(1), account="acc-ann")],
        prs=[pr(1, "OPEN", recent(1))],
    )
    return api


def run(args, tmp_path, fake, token="tok-bb-1", workspace="keyhealthtech"):
    environ = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path)}
    if token:
        environ["BITBUCKET"] = token
    if workspace:
        environ["BITBUCKET_WORKSPACE"] = workspace
    return main(args, env_path=tmp_path / "missing.env", environ=environ, transport=fake.transport())


def selected(tmp_path):
    conn = db.connect(tmp_path / "delivery.sqlite")
    try:
        return [dict(r) for r in conn.execute("SELECT repository_id, workspace, slug FROM repo_selection")]
    finally:
        conn.close()


@pytest.mark.parametrize("text", ["movedocs_v1.0", "keyhealthtech/movedocs_v1.0", UUID])
def test_add_accepts_slug_full_name_and_uuid_and_is_idempotent(tmp_path, fake, capsys, text):
    assert run(["repos", "add", f"bitbucket:{text}"], tmp_path, fake) == 0
    assert run(["repos", "add", f"bitbucket:{text}"], tmp_path, fake) == 0
    assert selected(tmp_path) == [{"repository_id": UUID, "workspace": "keyhealthtech", "slug": "movedocs_v1.0"}]
    assert "keyhealthtech/movedocs_v1.0" in capsys.readouterr().out


@pytest.mark.parametrize(
    "args, kwargs, message",
    [
        (["repos", "add", "bitbucket:keyhealthtech/nope"], {}, "was not found"),
        (["repos", "add", "bitbucket:movedocs_v1.0"], {"workspace": ""}, "BITBUCKET_WORKSPACE"),
        (["repos", "add", "bitbucket:movedocs_v1.0"], {"token": ""}, "BITBUCKET is not set"),
        (["repos", "add", "bitbucket:movedocs_v1.0"], {"token": "wrong-LEAK"}, "rejected the token"),
        (["repos", "add", "jira:MD"], {}, "Only bitbucket"),
        (["repos", "add", "movedocs_v1.0"], {}, "bitbucket:"),
    ],
)
def test_add_failures_are_plain_messages_with_exit_2(tmp_path, fake, capsys, args, kwargs, message):
    assert run(args, tmp_path, fake, **kwargs) == 2
    out = capsys.readouterr().out
    assert message in out
    assert "tok-bb-1" not in out and "wrong-LEAK" not in out
    assert selected(tmp_path) == []


def test_list_shows_status_and_detail_progress_and_remove_stops_syncing(tmp_path, fake, capsys):
    run(["repos", "add", "bitbucket:movedocs_v1.0"], tmp_path, fake)
    capsys.readouterr()
    run(["repos", "list"], tmp_path, fake)
    before = capsys.readouterr().out
    assert "keyhealthtech/movedocs_v1.0" in before and UUID in before and "never" in before and "detail: 0/0" in before
    assert run(["sync", "--source", "bitbucket"], tmp_path, fake) == 0
    capsys.readouterr()
    run(["repos", "list"], tmp_path, fake)
    after = capsys.readouterr().out
    assert "status: ok" in after and "detail: 1/1" in after
    assert run(["repos", "remove", "bitbucket:movedocs_v1.0"], tmp_path, fake) == 0
    assert selected(tmp_path) == []
    assert run(["repos", "remove", "bitbucket:movedocs_v1.0"], tmp_path, fake) == 2


def test_sync_says_so_when_nothing_is_selected(tmp_path, fake, capsys):
    assert run(["sync", "--source", "bitbucket"], tmp_path, fake) == 0
    assert "no repositories are selected" in capsys.readouterr().out.lower()


def test_teams_discover_resolves_a_slug_through_the_selection(tmp_path, fake, capsys):
    run(["repos", "add", "bitbucket:movedocs_v1.0"], tmp_path, fake)
    run(["sync", "--source", "bitbucket"], tmp_path, fake)
    capsys.readouterr()
    assert run(["teams", "discover", "--repo", "bitbucket:movedocs_v1.0"], tmp_path, fake) == 0
    out = capsys.readouterr().out
    assert "Ann Example" in out and "ann@corp.example" in out
    assert "has no stored commits" not in out
