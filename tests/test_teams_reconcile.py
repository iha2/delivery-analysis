import pytest

import delivery_analysis.teams.reconcile as reconcile_module
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
    lines, failed = reconcile_all(conn, NOW)
    assert failed == 0
    assert [line.split(":")[0] for line in lines] == ["Team Core", "Team Other"]


def test_a_manual_split_is_replayed_and_both_people_stay_on_the_roster(conn, add_commit, team, make_id):
    conn.execute("INSERT INTO person (person_id, display_name, manual) VALUES ('pA', 'Ann Corp', 0)")
    conn.execute("INSERT INTO person (person_id, display_name, manual) VALUES ('pB', 'Ann Partner', 0)")
    conn.execute(
        "INSERT INTO identity (source, account_id, person_id, manual) VALUES ('email', 'ann@corp.example', 'pA', 1)"
    )
    conn.execute(
        "INSERT INTO identity (source, account_id, person_id, manual) VALUES ('email', 'ann@partner.example', 'pB', 1)"
    )
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    add_commit("ann@partner.example", "Ann Example", "2026-09-02")
    reconcile_team(conn, team, NOW, make_id=make_id)
    members = {row["person_id"] for row in conn.execute("SELECT person_id FROM team_member WHERE team_id = ?", (team,))}
    assert members == {"pA", "pB"}
    assert conn.execute("SELECT COUNT(*) AS n FROM person").fetchone()["n"] == 2


def test_two_stored_people_that_merge_become_one_member_with_the_better_status(conn, add_commit, team, make_id):
    other = create_team(conn, "Other", REPOS, 90, now=NOW, make_id=make_id)
    for person_id, email in (("p1", "pat@corp.example"), ("p2", "pat@partner.example")):
        conn.execute("INSERT INTO person (person_id, display_name) VALUES (?, 'Pat Lee')", (person_id,))
        conn.execute(
            "INSERT INTO identity (source, account_id, person_id) VALUES ('email', ?, ?)", (email, person_id)
        )
    conn.execute(
        "INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit) "
        "VALUES (?, 'p1', 'active', '2026-01-01', '2026-02-01T00:00:00Z')",
        (team,),
    )
    conn.execute(
        "INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit) "
        "VALUES (?, 'p2', 'inactive', '2025-12-01', '2026-03-01T00:00:00Z')",
        (team,),
    )
    conn.execute(
        "INSERT INTO team_member (team_id, person_id, status, first_seen) VALUES (?, 'p2', 'active', '2026-01-05')",
        (other,),
    )
    add_commit("pat@corp.example", "Pat Lee", "2026-09-01")
    add_commit("pat@partner.example", "Pat Lee", "2026-09-02")
    reconcile_team(conn, team, NOW, make_id=make_id)
    core = conn.execute("SELECT * FROM team_member WHERE team_id = ?", (team,)).fetchall()
    assert [(r["person_id"], r["status"], r["first_seen"]) for r in core] == [("p1", "active", "2025-12-01")]
    assert core[0]["last_commit"] == "2026-09-02T12:00:00Z"
    moved = conn.execute("SELECT person_id FROM team_member WHERE team_id = ?", (other,)).fetchall()
    assert [r["person_id"] for r in moved] == ["p1"]
    assert {r["person_id"] for r in conn.execute("SELECT person_id FROM identity")} == {"p1"}
    marked = conn.execute("SELECT person_a, person_b, status FROM possible_duplicate").fetchall()
    assert [(r["person_a"], r["person_b"], r["status"]) for r in marked] == [("p1", "p2", "merged")]


def test_a_changed_email_with_the_same_account_stays_one_person(conn, add_commit, team, make_id):
    add_commit("old@corp.example", "Sam Poole", "2026-09-01", account="{acc-9}")
    reconcile_team(conn, team, NOW, make_id=make_id)
    add_commit("new@corp.example", "Sam Poole", "2027-02-01", account="{acc-9}")
    reconcile_team(conn, team, LATER, make_id=make_id)
    assert conn.execute("SELECT COUNT(*) AS n FROM person").fetchone()["n"] == 1
    assert roster(conn, team) == {"Sam Poole": "active"}
    owners = {r["person_id"] for r in conn.execute("SELECT person_id FROM identity WHERE source = 'email'")}
    assert len(owners) == 1


def test_a_connector_level_failure_protects_every_repository_of_that_source(conn, add_commit, team, make_id):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    add_commit("bob@corp.example", "Bob Builder", "2026-09-02")
    reconcile_team(conn, team, NOW, make_id=make_id)
    add_commit("bob@corp.example", "Bob Builder", "2027-02-01")
    result = reconcile_team(conn, team, LATER, stale_repos=[("bitbucket", "*")], make_id=make_id)
    assert result.skipped_inactive_step is True
    assert roster(conn, team) == {"Ann Example": "active", "Bob Builder": "active"}


def test_unknown_repositories_are_named_in_the_result(conn, add_commit, make_id):
    add_commit("ann@corp.example", "Ann Example", "2026-09-01")
    typo = create_team(conn, "Typo", [("bitbucket", "r1"), ("bitbucket", "r-typo")], 90, now=NOW, make_id=make_id)
    result = reconcile_team(conn, typo, NOW, make_id=make_id)
    assert any("bitbucket:r-typo has no stored commits" in message for message in result.messages)
    assert not any("bitbucket:r1 has no stored commits" in message for message in result.messages)
    assert roster(conn, typo) == {"Ann Example": "active"}


def test_one_failing_team_does_not_stop_the_others(conn, add_commit, team, make_id, monkeypatch):
    seed_core(add_commit)
    bad = create_team(conn, "Bad", REPOS, 90, now=NOW, make_id=make_id)
    real = reconcile_module.reconcile_team

    def flaky(connection, team_id, now, stale_repos=(), *args, **kwargs):
        if team_id == bad:
            raise RuntimeError("boom tok-1")
        return real(connection, team_id, now, stale_repos, *args, **kwargs)

    monkeypatch.setattr(reconcile_module, "reconcile_team", flaky)
    lines, failed = reconcile_all(conn, NOW, redact=lambda text: text.replace("tok-1", "***"))
    assert failed == 1
    assert lines[0].startswith("Team Bad: FAILED") and "tok-1" not in lines[0] and "***" in lines[0]
    assert lines[1].startswith("Team Core:")
    assert roster(conn, team)["Ann Example"] == "active"


def test_teams_on_sources_that_were_not_synced_are_left_alone(conn, add_commit, team, make_id):
    seed_core(add_commit)
    lines, failed = reconcile_all(conn, NOW, sources={"jira"})
    assert (lines, failed) == ([], 0)
    assert roster(conn, team) == {}
    lines, _ = reconcile_all(conn, NOW, sources={"bitbucket"})
    assert len(lines) == 1 and roster(conn, team)["Ann Example"] == "active"
