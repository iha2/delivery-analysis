import pytest

from delivery_analysis.teams.reconcile import create_team, reconcile_all, reconcile_team

NOW = "2026-10-15T00:00:00Z"
LATER = "2027-02-15T00:00:00Z"  # window start 2026-11-17
REPOS = [("bitbucket", "r1")]


@pytest.fixture
def team(conn, make_id):
    return create_team(conn, "Core", REPOS, 90, now=NOW, make_id=make_id)


def roster(conn, team_id):
    rows = conn.execute(
        "SELECT p.display_name AS name, m.status AS status FROM team_member m "
        "JOIN person p ON p.person_id = m.person_id WHERE m.team_id = ? ORDER BY p.display_name",
        (team_id,),
    ).fetchall()
    return {row["name"]: row["status"] for row in rows}


def snapshot(conn):
    parts = []
    for table in ("person", "identity", "team_member", "possible_duplicate"):
        parts.append([tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2")])
    return parts


def seed_core(add_commit):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    add_commit("ann@partner.example", "Ann Example", "2026-09-02")
    add_commit("bob@corp.example", "Bob Builder", "2026-09-03")
    add_commit("build-bot@corp.example", "Build Bot", "2026-09-04")


def test_creating_a_team_twice_with_one_name_is_an_error(conn, team, make_id):
    with pytest.raises(ValueError, match="already exists"):
        create_team(conn, "Core", REPOS, now=NOW, make_id=make_id)


def test_initial_load_creates_people_identities_and_members(conn, add_commit, team, make_id):
    seed_core(add_commit)
    result = reconcile_team(conn, team, NOW, make_id=make_id)
    assert (result.added, result.excluded) == (2, 1)
    assert roster(conn, team) == {"Ann Example": "active", "Bob Builder": "active", "Build Bot": "excluded"}
    assert conn.execute("SELECT COUNT(*) AS n FROM person").fetchone()["n"] == 3
    assert conn.execute("SELECT COUNT(*) AS n FROM identity WHERE source = 'email'").fetchone()["n"] == 4
    assert conn.execute("SELECT excluded FROM person WHERE display_name = 'Build Bot'").fetchone()["excluded"] == 1


def test_running_twice_changes_nothing(conn, add_commit, team, make_id):
    seed_core(add_commit)
    reconcile_team(conn, team, NOW, make_id=make_id)
    before = snapshot(conn)
    second = reconcile_team(conn, team, NOW, make_id=make_id)
    assert (second.added, second.reactivated, second.inactivated, second.duplicates) == (0, 0, 0, 0)
    assert snapshot(conn) == before


def test_a_new_committer_is_added(conn, add_commit, team, make_id):
    seed_core(add_commit)
    reconcile_team(conn, team, NOW, make_id=make_id)
    add_commit("cy@corp.example", "Cy Source", "2026-10-01")
    result = reconcile_team(conn, team, NOW, make_id=make_id)
    assert result.added == 1
    assert roster(conn, team)["Cy Source"] == "active"


def test_a_silent_member_becomes_inactive_and_returns(conn, add_commit, team, make_id):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    add_commit("bob@corp.example", "Bob Builder", "2026-09-02")
    reconcile_team(conn, team, NOW, make_id=make_id)
    add_commit("bob@corp.example", "Bob Builder", "2027-02-01")
    quiet = reconcile_team(conn, team, LATER, make_id=make_id)
    assert quiet.inactivated == 1
    assert roster(conn, team) == {"Ann Example": "inactive", "Bob Builder": "active"}
    kept = conn.execute(
        "SELECT m.last_commit AS last FROM team_member m JOIN person p ON p.person_id = m.person_id "
        "WHERE p.display_name = 'Ann Example'"
    ).fetchone()
    assert kept["last"] == "2026-09-01T12:00:00Z"
    add_commit("ann@corp.example", "Ann Example", "2027-02-10")
    back = reconcile_team(conn, team, LATER, make_id=make_id)
    assert back.reactivated == 1
    assert roster(conn, team)["Ann Example"] == "active"


def test_a_manual_rename_survives(conn, add_commit, team, make_id):
    seed_core(add_commit)
    reconcile_team(conn, team, NOW, make_id=make_id)
    conn.execute("UPDATE person SET display_name = 'Annie', manual = 1 WHERE display_name = 'Ann Example'")
    add_commit("ann@corp.example", "Ann Example", "2026-09-20")
    reconcile_team(conn, team, NOW, make_id=make_id)
    assert roster(conn, team)["Annie"] == "active"
    assert "Ann Example" not in roster(conn, team)


def test_a_pinned_member_stays_active(conn, add_commit, team, make_id):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    add_commit("bob@corp.example", "Bob Builder", "2026-09-02")
    reconcile_team(conn, team, NOW, make_id=make_id)
    conn.execute(
        "UPDATE team_member SET pinned = 1 WHERE person_id = "
        "(SELECT person_id FROM person WHERE display_name = 'Ann Example')"
    )
    add_commit("bob@corp.example", "Bob Builder", "2027-02-01")
    reconcile_team(conn, team, LATER, make_id=make_id)
    assert roster(conn, team) == {"Ann Example": "active", "Bob Builder": "active"}


def test_a_stale_repository_deactivates_nobody(conn, add_commit, team, make_id):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    add_commit("bob@corp.example", "Bob Builder", "2026-09-02")
    reconcile_team(conn, team, NOW, make_id=make_id)
    add_commit("bob@corp.example", "Bob Builder", "2027-02-01")
    result = reconcile_team(conn, team, LATER, stale_repos=REPOS, make_id=make_id)
    assert result.skipped_inactive_step is True
    assert roster(conn, team) == {"Ann Example": "active", "Bob Builder": "active"}


def test_no_commits_in_the_window_leaves_the_roster_alone(conn, add_commit, team, make_id):
    seed_core(add_commit)
    reconcile_team(conn, team, NOW, make_id=make_id)
    before = snapshot(conn)
    result = reconcile_team(conn, team, "2028-06-01T00:00:00Z", make_id=make_id)
    assert result.inactivated == 0
    assert any("no commits" in message for message in result.messages)
    assert snapshot(conn) == before


def test_a_team_without_repositories_is_reported_not_crashed(conn, make_id):
    empty = create_team(conn, "Empty", [], 90, now=NOW, make_id=make_id)
    result = reconcile_team(conn, empty, NOW, make_id=make_id)
    assert any("no repositories" in message for message in result.messages)


def test_a_manually_linked_email_keeps_its_person(conn, add_commit, team, make_id):
    conn.execute("INSERT INTO person (person_id, display_name, manual) VALUES ('pp', 'Pinned Person', 0)")
    conn.execute(
        "INSERT INTO identity (source, account_id, person_id, manual) "
        "VALUES ('email', 'ann@corp.example', 'pp', 1)"
    )
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    reconcile_team(conn, team, NOW, make_id=make_id)
    member = conn.execute("SELECT person_id FROM team_member WHERE team_id = ?", (team,)).fetchone()
    assert member["person_id"] == "pp"
    assert conn.execute("SELECT COUNT(*) AS n FROM person").fetchone()["n"] == 1


def test_possible_duplicates_are_recorded_once_and_dismissals_stick(conn, add_commit, team, make_id):
    add_commit("john@a.example", "John Smith", "2026-09-01")
    add_commit("john@b.example", "John Doe", "2026-09-02")
    first = reconcile_team(conn, team, NOW, make_id=make_id)
    assert first.duplicates == 1
    conn.execute("UPDATE possible_duplicate SET status = 'dismissed'")
    second = reconcile_team(conn, team, NOW, make_id=make_id)
    assert second.duplicates == 0
    assert conn.execute("SELECT status FROM possible_duplicate").fetchone()["status"] == "dismissed"


def test_reconcile_all_returns_one_summary_per_team(conn, add_commit, team, make_id):
    seed_core(add_commit)
    other = create_team(conn, "Other", [("bitbucket", "r9")], 90, now=NOW, make_id=make_id)
    assert other
    lines = reconcile_all(conn, NOW)
    assert [line.split(":")[0] for line in lines] == ["Team Core", "Team Other"]
