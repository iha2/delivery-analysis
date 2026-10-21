"""Rankings list the same people as the People page, whether or not they have data for the metric."""
import pytest

from test_app_api import make

WINDOW = {"team": "t1", "window": "month:2026-09"}


def matrix(client, **params):
    return client.get("/api/people-matrix", params={**WINDOW, **params}).json()


def ready_metrics(client):
    return [c["name"] for c in matrix(client)["columns"] if c["status"] == "ok"]


def test_the_seeded_team_has_ranking_metrics_that_are_ready(tmp_path):
    client, *_ = make(tmp_path)
    assert {"prs_reviewed", "review_value"} <= set(ready_metrics(client))


@pytest.mark.parametrize("inactive", [False, True])
def test_every_person_on_the_people_page_is_on_every_ready_ranking(tmp_path, inactive):
    client, *_ = make(tmp_path)
    params = {"include_inactive": "true"} if inactive else {}
    expected = {r["person_id"] for r in matrix(client, **params)["rows"] if r["person_id"]}
    assert expected
    for name in ready_metrics(client):
        body = client.get(f"/api/metrics/{name}", params={**WINDOW, **params}).json()
        listed = {row["person_id"] for row in body["rows"] if row["person_id"]}
        assert expected <= listed, (name, expected - listed)


def test_people_without_data_are_listed_as_unranked_not_dropped(tmp_path):
    client, *_ = make(tmp_path)
    rows = client.get("/api/metrics/review_value", params=WINDOW).json()["rows"]
    ann = [row for row in rows if row["person_id"] == "p-ann"][0]
    assert ann["value"] == 0.0 and ann["ranked"] is False and ann["rank"] is None


def test_inactive_members_appear_only_when_asked_and_excluded_people_never(tmp_path):
    client, *_ = make(tmp_path)
    default = {r["person_id"] for r in client.get("/api/metrics/review_value", params=WINDOW).json()["rows"]}
    wide = {r["person_id"] for r in client.get(
        "/api/metrics/review_value", params={**WINDOW, "include_inactive": "true"}).json()["rows"]}
    assert default < wide
    status = {m["person_id"]: m["status"] for m in client.get("/api/teams/t1").json()["members"]}
    assert {pid for pid in wide if pid} <= {pid for pid, s in status.items() if s != "excluded"}
