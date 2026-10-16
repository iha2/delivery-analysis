import pytest

from delivery_analysis.cli.main import main
from delivery_analysis.connectors.jira.statuses import SEED
from delivery_analysis.store import db
from delivery_analysis.store import project_selection as ps
from jira_fakes import FakeJira, issue, jira_ts

EMAIL = "me@corp.example"
TOKEN = "tok-jira-LEAK-1"


@pytest.fixture
def fake():
    api = FakeJira(email=EMAIL, token=TOKEN)
    api.add_project("MD", 10001, "Move Docs", list(SEED) + ["Brand New"])
    for number in range(1, 11):
        api.add_issue(
            issue(number, f"MD-{number}", points=3 if number <= 8 else None, updated=jira_ts(3),
                  extra={"customfield_11168": 2 if number == 1 else None})
        )
    return api


def run(args, tmp_path, fake, *, email=EMAIL, token=TOKEN):
    environ = {"GITHUB_ANALYSIS_RESULTS": str(tmp_path)}
    if token:
        environ["ATLASSIAN"] = token
    if email:
        environ["ATLASSIAN_EMAIL"] = email
    return main(args, env_path=tmp_path / "missing.env", environ=environ, transport=fake.transport())


def store(tmp_path):
    conn = db.connect(tmp_path / "delivery.sqlite")
    db.migrate(conn)
    return conn


def test_add_selects_the_project_detects_points_and_seeds_the_status_map(tmp_path, fake, capsys):
    assert run(["projects", "add", "jira:MD"], tmp_path, fake) == 0
    out = capsys.readouterr().out
    assert "jira:MD" in out and "Move Docs" in out
    assert "customfield_10004" in out and "8 of 10" in out
    assert "Brand New" in out and 'projects map jira:MD "<status>"' in out
    conn = store(tmp_path)
    row = ps.get_project(conn, "jira", "MD")
    assert (row["project_id"], row["name"], row["story_points_field"]) == ("10001", "Move Docs", "customfield_10004")
    assert len(ps.status_map(conn, "jira", "MD")) == 19
    assert TOKEN not in out and EMAIL not in out


def test_add_is_idempotent_and_keeps_manual_status_choices(tmp_path, fake):
    assert run(["projects", "add", "jira:MD"], tmp_path, fake) == 0
    assert run(["projects", "map", "jira:MD", "Dev Done", "in_review"], tmp_path, fake) == 0
    assert run(["projects", "add", "jira:md"], tmp_path, fake) == 0
    conn = store(tmp_path)
    assert len(ps.list_projects(conn, "jira")) == 1
    assert ps.status_map(conn, "jira", "MD")["Dev Done"] == "in_review"


def test_an_explicit_points_field_wins_and_unknown_fields_are_refused(tmp_path, fake, capsys):
    assert run(["projects", "add", "jira:MD", "--points-field", "customfield_11168"], tmp_path, fake) == 0
    assert ps.get_project(store(tmp_path), "jira", "MD")["story_points_field"] == "customfield_11168"
    capsys.readouterr()
    assert run(["projects", "add", "jira:MD", "--points-field", "customfield_00000"], tmp_path, fake) == 2
    assert "was not found" in capsys.readouterr().out


def test_a_near_tie_between_two_fields_asks_for_an_explicit_choice(tmp_path, capsys):
    api = FakeJira(email=EMAIL, token=TOKEN)
    api.add_project("MD", 10001, "Move Docs", list(SEED))
    for number in range(1, 6):
        api.add_issue(issue(number, f"MD-{number}", points=3, extra={"customfield_11168": 3}))
    assert run(["projects", "add", "jira:MD"], tmp_path, api) == 2
    out = capsys.readouterr().out
    assert "--points-field" in out and "customfield_10004" in out and "customfield_11168" in out
    assert ps.list_projects(store(tmp_path), "jira") == []


@pytest.mark.parametrize(
    "args, kwargs, message",
    [
        (["projects", "add", "jira:ZZ"], {}, "was not found"),
        (["projects", "add", "jira:MD"], {"token": ""}, "ATLASSIAN is not set"),
        (["projects", "add", "jira:MD"], {"email": ""}, "ATLASSIAN_EMAIL"),
        (["projects", "add", "jira:MD"], {"token": "wrong-LEAK"}, "rejected the email or token"),
        (["projects", "add", "bitbucket:repo"], {}, "Only jira"),
        (["projects", "add", "MD"], {}, "jira:"),
        (["projects", "add", "jira:M D"], {}, "project key"),
    ],
)
def test_add_failures_are_plain_messages_with_exit_2(tmp_path, fake, capsys, args, kwargs, message):
    assert run(args, tmp_path, fake, **kwargs) == 2
    out = capsys.readouterr().out
    assert message in out
    for secret in (TOKEN, "wrong-LEAK", EMAIL):
        assert secret not in out
    assert ps.list_projects(store(tmp_path), "jira") == []


def test_map_sets_one_status_and_refuses_bad_input(tmp_path, fake, capsys):
    run(["projects", "add", "jira:MD"], tmp_path, fake)
    capsys.readouterr()
    assert run(["projects", "map", "jira:MD", "Brand New", "in_review"], tmp_path, fake) == 0
    assert ps.status_map(store(tmp_path), "jira", "MD")["Brand New"] == "in_review"
    assert run(["projects", "map", "jira:ZZ", "Brand New", "done"], tmp_path, fake) == 2
    assert "not selected" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        run(["projects", "map", "jira:MD", "Brand New", "finished"], tmp_path, fake)


def test_list_shows_status_issue_count_points_field_and_unmapped_statuses(tmp_path, fake, capsys):
    assert run(["projects", "list"], tmp_path, fake) == 0
    assert "No Jira projects are selected" in capsys.readouterr().out
    run(["projects", "add", "jira:MD"], tmp_path, fake)
    run(["projects", "map", "jira:MD", "Brand New", "in_review"], tmp_path, fake)
    capsys.readouterr()
    run(["projects", "list"], tmp_path, fake)
    before = capsys.readouterr().out
    assert "MD" in before and "never" in before and "issues: 0" in before and "customfield_10004" in before
    assert run(["sync", "--source", "jira"], tmp_path, fake) == 0
    capsys.readouterr()
    conn = store(tmp_path)
    conn.execute("UPDATE work_item SET status = 'Odd Status' WHERE key = 'MD-1'")
    run(["projects", "list"], tmp_path, fake)
    after = capsys.readouterr().out
    assert "status: ok" in after and "issues: 10" in after and "unmapped statuses: Odd Status" in after


def test_remove_stops_syncing_but_keeps_data(tmp_path, fake, capsys):
    run(["projects", "add", "jira:MD"], tmp_path, fake)
    run(["projects", "map", "jira:MD", "Brand New", "in_review"], tmp_path, fake)
    assert run(["sync", "--source", "jira"], tmp_path, fake) == 0
    capsys.readouterr()
    assert run(["projects", "remove", "jira:MD"], tmp_path, fake) == 0
    conn = store(tmp_path)
    assert ps.list_projects(conn, "jira") == []
    assert ps.issue_count(conn, "jira", "MD") == 10
    assert run(["projects", "remove", "jira:MD"], tmp_path, fake) == 2


def test_doctor_lists_the_email_name_and_never_its_value(tmp_path, fake, capsys):
    assert run(["doctor"], tmp_path, fake) == 0
    out = capsys.readouterr().out
    assert "ATLASSIAN_EMAIL: present" in out and EMAIL not in out
    assert run(["doctor"], tmp_path, fake, email="") == 0
    assert "ATLASSIAN_EMAIL: missing" in capsys.readouterr().out
