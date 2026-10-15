import pytest

from metrics_seed import NOW, OTHER, REPO, put, seed
from delivery_analysis.metrics import people as pp


def test_team_scope_has_the_repositories_and_active_members(conn):
    seed(conn)
    scope = pp.team_scope(conn, "t1")
    assert scope.repos == (REPO,)
    assert scope.members == {"p-ann": "active", "p-bob": "active"}
    assert pp.team_scope(conn, "t1", include_inactive=True).members == {
        "p-ann": "active", "p-bob": "active", "p-cy": "inactive"
    }
    assert pp.team_scope(conn, None) == pp.Scope()
    with pytest.raises(LookupError):
        pp.team_scope(conn, "nope")


def test_repo_filter_covers_all_none_and_some():
    assert pp.Scope().repo_filter("c.repository_id") == ("1=1", [])
    assert pp.Scope(repos=()).repo_filter("c.repository_id") == ("0=1", [])
    assert pp.Scope(repos=(REPO, OTHER)).repo_filter("x") == ("x IN (?, ?)", [REPO, OTHER])


def test_actor_keys_and_resolution_fall_back_from_account_to_email(conn):
    seed(conn)
    people = pp.People(conn)
    assert pp.actor_key(("bitbucket", "acc-x"), ("email", "ann@corp.example")) == "bitbucket:acc-x|email:ann@corp.example"
    assert pp.actor_key(("bitbucket", None)) is None
    assert people.resolve("bitbucket:acc-x|email:ann@corp.example") == "p-ann"
    assert people.resolve("bitbucket:acc-zed") is None
    assert people.name("p-bob") == "Bob Builder"
    assert people.is_excluded("p-dee") and not people.is_excluded("p-ann")


def test_unmapped_accounts_include_reviewers_and_count_their_activity(conn):
    seed(conn)
    assert pp.unmapped_accounts(conn) == [
        {"source": "bitbucket", "account": "acc-zed", "activity": 2, "name_hint": None}
    ]


def test_a_display_name_hint_comes_from_stored_raw_activity(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO raw_payload (source, source_id, kind, json, fetched_at) VALUES (?, ?, ?, ?, ?)",
        ("bitbucket", f"{REPO}#2", "pr_activity",
         '[{"comment": {"user": {"account_id": "acc-zed", "display_name": "Zed Reviewer"}}}]', NOW),
    )
    assert pp.unmapped_accounts(conn)[0]["name_hint"] == "Zed Reviewer"


def test_map_identity_to_a_new_person_and_into_the_team(conn):
    seed(conn)
    person_id = pp.map_identity(conn, "bitbucket", "acc-zed", new_name="Zed Reviewer", team_id="t1", now=NOW)
    assert pp.People(conn).resolve("bitbucket:acc-zed") == person_id
    member = conn.execute(
        "SELECT status, manual FROM team_member WHERE team_id = 't1' AND person_id = ?", (person_id,)
    ).fetchone()
    assert (member["status"], member["manual"]) == ("active", 1)
    assert pp.unmapped_accounts(conn) == []


def test_map_identity_to_an_existing_person_and_the_errors(conn):
    seed(conn)
    assert pp.map_identity(conn, "bitbucket", "acc-zed", person_id="p-bob", now=NOW) == "p-bob"
    with pytest.raises(LookupError):
        pp.map_identity(conn, "bitbucket", "acc-q", person_id="nobody", now=NOW)
    with pytest.raises(ValueError):
        pp.map_identity(conn, "bitbucket", "acc-q", now=NOW)
    with pytest.raises(ValueError):
        pp.map_identity(conn, "bitbucket", " ", new_name="X", now=NOW)


def test_set_member_status_is_manual_and_validated(conn):
    seed(conn)
    pp.set_member_status(conn, "t1", "p-ann", "excluded", NOW)
    row = conn.execute("SELECT status, manual FROM team_member WHERE person_id = 'p-ann'").fetchone()
    assert (row["status"], row["manual"]) == ("excluded", 1)
    with pytest.raises(ValueError):
        pp.set_member_status(conn, "t1", "p-ann", "inactive", NOW)
    with pytest.raises(LookupError):
        pp.set_member_status(conn, "t1", "nobody", "active", NOW)
