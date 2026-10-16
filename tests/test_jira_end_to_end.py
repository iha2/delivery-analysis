from bitbucket_fakes import FakeBitbucket, commit, pr, recent
from delivery_analysis.cli.main import main
from delivery_analysis.connectors.bitbucket.client import BitbucketClient
from delivery_analysis.connectors.bitbucket.connector import BitbucketConnector
from delivery_analysis.connectors.jira.client import JiraClient
from delivery_analysis.connectors.jira.connector import JiraConnector
from delivery_analysis.connectors.jira.statuses import SEED
from delivery_analysis.linking.pr_keys import link_pull_requests
from delivery_analysis.store import db, repo_selection
from delivery_analysis.store import project_selection as ps
from delivery_analysis.sync.runner import run_sync, utc_now_iso
from jira_fakes import FakeJira, history, issue, jira_ts, user

UUID = "{11111111-1111-1111-1111-111111111111}"
EMAIL = "me@corp.example"
TOKEN = "tok-jira-LEAK-CHECK-1"
ANN = user("acc-ann", "Ann Example", "ann@corp.example")


def jira_fake():
    api = FakeJira(email=EMAIL, token=TOKEN)
    api.add_project("MD", 10001, "Move Docs", list(SEED))
    api.add_issue(
        issue(5001, "MD-1", status="COMPLETED", assignee=ANN, points=5, updated=jira_ts(3)),
        [history(1, "2026-10-02T10:00:00Z", "To Do", "In Progress"), history(2, "2026-10-09T10:00:00Z", "In Progress", "COMPLETED")],
    )
    api.add_issue(issue(5002, "MD-2", status="In Progress", assignee=ANN, points=3, updated=jira_ts(2)))
    return api


def test_both_connectors_sync_then_the_key_pass_links_on_the_shared_account_id(tmp_path):
    bb = FakeBitbucket()
    bb.add_repo(
        "movedocs_v1.0", UUID,
        commits=[commit("h1", "Ann Example <ann@corp.example>", recent(1), account="acc-ann")],
        prs=[
            pr(1, "MERGED", recent(2), title="MD-1 export documents", branch="feature/export"),
            pr(2, "OPEN", recent(1), title="Spike", branch="feature/MD-2-spike"),
            pr(3, "OPEN", recent(1), title="Chore", branch="chore/deps"),
        ],
    )
    jira = jira_fake()
    path = tmp_path / "delivery.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    repo_selection.add_repo(conn, "bitbucket", UUID, "keyhealthtech", "movedocs_v1.0", utc_now_iso())
    ps.add_project(conn, "jira", "MD", "10001", "Move Docs", "customfield_10004", utc_now_iso())
    ps.seed_statuses(conn, "jira", "MD", SEED)
    connectors = [
        BitbucketConnector(BitbucketClient("tok-bb-1", transport=bb.transport()), path, workspace="keyhealthtech"),
        JiraConnector(JiraClient(EMAIL, TOKEN, transport=jira.transport(), sleep=lambda s: None), path),
    ]
    results = run_sync(conn, connectors)
    assert {(r.connector, r.status) for r in results} == {("bitbucket", "ok"), ("jira", "ok")}

    coverage = link_pull_requests(conn, utc_now_iso())
    assert (coverage.total, coverage.linked, coverage.links) == (3, 2, 2)
    assert coverage.lines()[0] == "Issue links: 2 of 3 pull requests have an issue key."
    pairs = {
        (r["number"], r["key"], r["found_by"])
        for r in conn.execute(
            "SELECT c.number AS number, w.key AS key, l.found_by AS found_by FROM link l "
            "JOIN change_request c ON c.source_id = l.from_id JOIN work_item w ON w.source_id = l.to_id "
            "WHERE l.source = 'linker'"
        )
    }
    assert pairs == {("1", "MD-1", "pr_title"), ("2", "MD-2", "pr_branch")}

    # Bitbucket's account_id and Jira's accountId are the same value: the join between systems.
    joined = conn.execute(
        "SELECT COUNT(*) AS n FROM work_item w JOIN change_request c ON c.author_account = w.assignee_account "
        "WHERE w.source = 'jira' AND c.source = 'bitbucket'"
    ).fetchone()["n"]
    assert joined > 0
    done = conn.execute("SELECT status_category, story_points, resolved_at FROM work_item WHERE key = 'MD-1'").fetchone()
    assert (done["status_category"], done["story_points"], done["resolved_at"]) == ("done", 5.0, "2026-10-09T10:00:00Z")


def test_the_jira_sync_through_the_cli_never_leaks_the_token_or_the_email(tmp_path, capsys):
    jira = jira_fake()
    environ = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path), "ATLASSIAN": TOKEN, "ATLASSIAN_EMAIL": EMAIL}

    def run(args, env=None):
        return main(args, env_path=tmp_path / "missing.env", environ=env or environ, transport=jira.transport())

    assert run(["projects", "add", "jira:MD", "--points-field", "customfield_10004"]) == 0
    assert run(["sync", "--source", "jira"]) == 0
    assert run(["projects", "list"]) == 0
    assert run(["doctor"]) == 0
    jira.errors["/search/jql"] = 401
    assert run(["sync", "--source", "jira"]) == 1
    out = capsys.readouterr()
    assert "jira/MD: ok" in out.out and "FAILED" in out.out
    for text in (TOKEN, EMAIL):
        assert text not in out.out and text not in out.err
    for path in tmp_path.glob("delivery.sqlite*"):
        data = path.read_bytes()
        assert TOKEN.encode("utf-8") not in data and EMAIL.encode("utf-8") not in data
    conn = db.connect(tmp_path / "delivery.sqlite")
    assert conn.execute("SELECT COUNT(*) AS n FROM work_item").fetchone()["n"] == 2


def test_a_rejected_token_is_reported_without_the_token(tmp_path, capsys):
    jira = jira_fake()
    environ = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path), "ATLASSIAN": "tok-wrong-LEAK", "ATLASSIAN_EMAIL": EMAIL}
    code = main(["projects", "add", "jira:MD"], env_path=tmp_path / "missing.env", environ=environ, transport=jira.transport())
    out = capsys.readouterr().out
    assert code == 2 and "rejected the email or token" in out and "tok-wrong-LEAK" not in out
