from test_app_api import make


def test_default_comparison_is_every_active_member(tmp_path):
    client, *_ = make(tmp_path)
    body = client.get("/api/teams/t1/comparison").json()
    assert body["custom"] is False
    assert [(p["person_id"], p["selected"]) for p in body["people"]] == [("p-ann", True), ("p-bob", True)]
    assert client.get("/api/teams/nope/comparison").status_code == 404


def test_choosing_a_group_is_saved_and_reset_clears_it(tmp_path):
    client, *_ = make(tmp_path)
    saved = client.put("/api/teams/t1/comparison", json={"person_ids": ["p-ann"]})
    assert saved.status_code == 200 and saved.json()["custom"] is True
    again = client.get("/api/teams/t1/comparison").json()
    assert [(p["person_id"], p["selected"]) for p in again["people"]] == [("p-ann", True), ("p-bob", False)]
    reset = client.put("/api/teams/t1/comparison", json={"person_ids": None})
    assert reset.status_code == 200 and reset.json()["custom"] is False


def test_bad_choices_are_rejected(tmp_path):
    client, *_ = make(tmp_path)
    for bad in ([], ["p-cy"], ["nobody"]):
        assert client.put("/api/teams/t1/comparison", json={"person_ids": bad}).status_code == 400
    assert client.put("/api/teams/nope/comparison", json={"person_ids": ["p-ann"]}).status_code == 404
    assert client.get("/api/teams/t1/comparison").json()["custom"] is False


def test_the_series_median_follows_the_saved_group(tmp_path):
    client, *_ = make(tmp_path)
    before = client.get("/api/person/p-ann/series", params={"team": "t1"}).json()
    assert before["comparison"] == {"custom": False, "size": 2}
    client.put("/api/teams/t1/comparison", json={"person_ids": ["p-bob"]})
    after = client.get("/api/person/p-ann/series", params={"team": "t1"}).json()
    assert after["comparison"] == {"custom": True, "size": 1}
    nothing = client.get("/api/person/p-ann/series").json()
    assert nothing["comparison"] == {"custom": False, "size": 3}  # no team: everyone not excluded
