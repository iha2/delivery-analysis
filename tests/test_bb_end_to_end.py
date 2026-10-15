from bitbucket_fakes import FakeBitbucket, approval, comment, commit, pr, recent, update
from delivery_analysis.cli.main import main
from delivery_analysis.store import db

UUID = "{11111111-1111-1111-1111-111111111111}"
TOKEN = "tok-bb-LEAK-CHECK-1"


def test_add_sync_and_discover_work_together_and_the_token_never_leaks(tmp_path, capsys):
    fake = FakeBitbucket(token=TOKEN)
    reviewed = pr(1, "MERGED", recent(1))
    reviewed["participants"] = [{"role": "REVIEWER", "approved": True, "user": {"account_id": "acc-bob"}}]
    fake.add_repo(
        "movedocs_v1.0", UUID,
        commits=[
            commit("h1", "Ann Example <ann@corp.example>", recent(1), account="acc-ann"),
            commit("h2", "Ann Example <ann@partner.example>", recent(2), account="acc-ann"),
            commit("h3", "Bob Builder <bob@corp.example>", recent(3), account="acc-bob"),
            commit("h4", "Build Bot <noreply@corp.example>", recent(3)),
        ],
        prs=[reviewed],
        activity={1: [comment(5, recent(2)), approval(recent(2)), update("MERGED", recent(1))]},
        pr_commits={1: [{"hash": "h1"}]},
        diffstat={1: [{"status": "modified"}]},
    )
    environ = {
        "GITHUB_ANALYSIS_RESULTS": str(tmp_path),
        "BITBUCKET": TOKEN,
        "BITBUCKET_WORKSPACE": "keyhealthtech",
    }

    def run(args):
        return main(args, env_path=tmp_path / "missing.env", environ=environ, transport=fake.transport())

    assert run(["repos", "add", "bitbucket:movedocs_v1.0"]) == 0
    assert run(["sync", "--source", "bitbucket"]) == 0
    assert run(["teams", "discover", "--repo", "bitbucket:movedocs_v1.0"]) == 0
    assert run(["teams", "discover", "--repo", "bitbucket:movedocs_v1.0", "--save", "Core"]) == 0
    out = capsys.readouterr().out
    assert "Ann Example" in out and "Bob Builder" in out
    assert "ann@corp.example" in out and "ann@partner.example" in out  # one person, two emails
    assert "[bot]" in out
    assert TOKEN not in out

    conn = db.connect(tmp_path / "delivery.sqlite")
    try:
        members = conn.execute(
            "SELECT p.display_name AS name, m.status AS status FROM team_member m "
            "JOIN person p ON p.person_id = m.person_id ORDER BY p.display_name"
        ).fetchall()
        assert {r["name"]: r["status"] for r in members} == {
            "Ann Example": "active", "Bob Builder": "active", "Build Bot": "excluded",
        }
        reviewer = conn.execute(
            "SELECT value FROM property WHERE name = 'reviewer:acc-bob'"
        ).fetchone()
        assert reviewer["value"] == "approved"
    finally:
        conn.close()
    for path in tmp_path.glob("delivery.sqlite*"):
        assert TOKEN.encode("utf-8") not in path.read_bytes()


def test_a_rejected_token_is_reported_without_the_token(tmp_path, capsys):
    fake = FakeBitbucket(token="tok-real")
    fake.add_repo("movedocs_v1.0", UUID)
    environ = {
        "GITHUB_ANALYSIS_RESULTS": str(tmp_path),
        "BITBUCKET": "tok-wrong-LEAK",
        "BITBUCKET_WORKSPACE": "keyhealthtech",
    }
    code = main(
        ["repos", "add", "bitbucket:movedocs_v1.0"],
        env_path=tmp_path / "missing.env", environ=environ, transport=fake.transport(),
    )
    out = capsys.readouterr().out
    assert code == 2 and "rejected the token" in out and "tok-wrong-LEAK" not in out
