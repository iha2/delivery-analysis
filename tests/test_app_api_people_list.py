from test_app_api import make


def test_a_teams_people_list_is_its_active_members_by_name(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/people", params={"team": "t1"}).json()
    assert [(p["person_id"], p["name"], p["status"]) for p in body["people"]] == [
        ("p-ann", "Ann Example", "active"), ("p-bob", "Bob Builder", "active")]


def test_inactive_members_are_listed_only_when_asked(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/people", params={"team": "t1", "include_inactive": "true"}).json()
    assert [(p["person_id"], p["status"]) for p in body["people"]] == [
        ("p-ann", "active"), ("p-bob", "active"), ("p-cy", "inactive")]


def test_without_a_team_everyone_not_excluded_is_listed(tmp_path):
    client, *_ = make(tmp_path)
    ids = [p["person_id"] for p in client.get("/api/people").json()["people"]]
    assert ids == ["p-ann", "p-bob", "p-cy"]


def test_an_unknown_team_is_a_404(tmp_path):
    client, *_ = make(tmp_path)
    assert client.get("/api/people", params={"team": "nope"}).status_code == 404
