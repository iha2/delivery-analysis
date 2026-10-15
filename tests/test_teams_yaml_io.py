import json

import pytest

from delivery_analysis.teams.yaml_io import TeamsFileError, export_teams, import_teams

NOW = "2026-10-15T00:00:00Z"
PAYLOAD = {
    "teams": [
        {
            "name": "Core",
            "members": [
                {"name": "Ann Example", "emails": ["Ann@Corp.Example", "ann@partner.example"]},
                {"name": "Gus Hub", "user": "gus-hub"},
            ],
        }
    ]
}


def write_json(tmp_path, payload, name="teams.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def counts(conn):
    return {
        table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        for table in ("team", "team_repo", "team_member", "person", "identity")
    }


def test_import_creates_the_team_people_and_identities(conn, tmp_path, make_id):
    lines = import_teams(conn, write_json(tmp_path, PAYLOAD), [("bitbucket", "r1")], NOW, make_id)
    assert lines == ["Team Core: 2 member(s) imported"]
    assert counts(conn) == {"team": 1, "team_repo": 1, "team_member": 2, "person": 2, "identity": 3}
    identities = {
        (row["source"], row["account_id"], row["manual"])
        for row in conn.execute("SELECT source, account_id, manual FROM identity")
    }
    assert identities == {
        ("email", "ann@corp.example", 1),
        ("email", "ann@partner.example", 1),
        ("github", "gus-hub", 1),
    }
    assert all(row["manual"] == 1 for row in conn.execute("SELECT manual FROM person"))
    assert {row["status"] for row in conn.execute("SELECT status FROM team_member")} == {"active"}
    assert all(row["manual"] == 0 for row in conn.execute("SELECT manual FROM team_member"))


def test_importing_the_same_file_twice_changes_nothing(conn, tmp_path, make_id):
    path = write_json(tmp_path, PAYLOAD)
    import_teams(conn, path, [], NOW, make_id)
    before = counts(conn)
    import_teams(conn, path, [], NOW, make_id)
    assert counts(conn) == before


def test_a_member_without_a_name_or_identity_rejects_the_whole_file(conn, tmp_path, make_id):
    bad = {"teams": [{"name": "Core", "members": [{"name": "Ann Example", "emails": ["a@x.example"]}, {"name": "Nobody"}]}]}
    with pytest.raises(TeamsFileError, match="needs a name and emails or user"):
        import_teams(conn, write_json(tmp_path, bad), [], NOW, make_id)
    assert counts(conn)["team"] == 0


@pytest.mark.parametrize(
    "filename, content, message",
    [
        ("teams.json", "{not json", "not valid JSON"),
        ("teams.json", json.dumps({"nope": []}), "'teams' list"),
        ("teams.txt", "x", ".json, .yaml or .yml"),
    ],
)
def test_bad_files_get_plain_messages(conn, tmp_path, make_id, filename, content, message):
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    with pytest.raises(TeamsFileError, match=message):
        import_teams(conn, path, [], NOW, make_id)


def test_export_writes_active_members_and_round_trips(conn, tmp_path, make_id):
    import_teams(conn, write_json(tmp_path, PAYLOAD), [], NOW, make_id)
    conn.execute(
        "UPDATE team_member SET status = 'inactive' WHERE person_id = "
        "(SELECT person_id FROM person WHERE display_name = 'Gus Hub')"
    )
    out = tmp_path / "out.json"
    assert export_teams(conn, out) == f"Exported 1 team(s) to {out}"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {
        "teams": [
            {"name": "Core", "members": [{"name": "Ann Example", "emails": ["ann@corp.example", "ann@partner.example"]}]}
        ]
    }


def test_export_of_an_unknown_team_is_an_error(conn, tmp_path):
    with pytest.raises(TeamsFileError, match="No team named 'Nope'"):
        export_teams(conn, tmp_path / "out.json", "Nope")


def test_yaml_round_trip(conn, tmp_path, make_id):
    pytest.importorskip("yaml")
    path = tmp_path / "teams.yaml"
    path.write_text(
        "teams:\n  - name: Core\n    members:\n      - name: Ann Example\n        emails: [ann@corp.example]\n",
        encoding="utf-8",
    )
    import_teams(conn, path, [], NOW, make_id)
    out = tmp_path / "out.yaml"
    export_teams(conn, out)
    assert "ann@corp.example" in out.read_text(encoding="utf-8")


def test_importing_a_listed_name_renames_an_existing_person_and_pins_the_name(conn, tmp_path, make_id):
    conn.execute("INSERT INTO person (person_id, display_name, manual) VALUES ('p1', 'Ann Example', 0)")
    conn.execute("INSERT INTO identity (source, account_id, person_id) VALUES ('email', 'ann@corp.example', 'p1')")
    payload = {"teams": [{"name": "Core", "members": [{"name": "Annie Renamed", "emails": ["ann@corp.example"]}]}]}
    import_teams(conn, write_json(tmp_path, payload), [], NOW, make_id)
    person = conn.execute("SELECT display_name, manual FROM person").fetchone()
    assert (person["display_name"], person["manual"]) == ("Annie Renamed", 1)


def test_members_with_only_a_github_login_are_pinned(conn, tmp_path, make_id):
    import_teams(conn, write_json(tmp_path, PAYLOAD), [], NOW, make_id)
    rows = conn.execute(
        "SELECT p.display_name AS name, m.pinned AS pinned FROM team_member m "
        "JOIN person p ON p.person_id = m.person_id"
    ).fetchall()
    assert {row["name"]: row["pinned"] for row in rows} == {"Ann Example": 0, "Gus Hub": 1}
