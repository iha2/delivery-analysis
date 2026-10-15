from bitbucket_fakes import FakeBitbucket
from metrics_seed import REPO
from test_app_api import TOKEN, FakeRun, make
from delivery_analysis.store import db, sync_state

UUID_NEW = "{33333333-3333-3333-3333-333333333333}"


def test_create_team_from_a_selected_repo_slug_and_reconcile(tmp_path):
    client, *_ = make(tmp_path)
    response = client.post("/api/teams", json={"name": "Platform", "repos": ["bitbucket:core-repo"]})
    assert response.status_code == 200
    body = response.json()
    assert body["team_id"] and "added" in body["summary"]
    team = client.get(f"/api/teams/{body['team_id']}").json()
    assert team["repos"][0]["repository_id"] == REPO
    assert client.post("/api/teams", json={"name": "Platform", "repos": ["bitbucket:core-repo"]}).status_code == 400
    assert client.post("/api/teams", json={"name": "Empty", "repos": []}).status_code == 400


def test_member_status_edits_are_manual_and_validated(tmp_path):
    client, path, *_ = make(tmp_path)
    assert client.post("/api/teams/t1/members/p-ann", json={"status": "excluded"}).json() == {
        "team_id": "t1", "person_id": "p-ann", "status": "excluded"
    }
    conn = db.connect(path)
    row = conn.execute("SELECT status, manual FROM team_member WHERE person_id = 'p-ann'").fetchone()
    conn.close()
    assert (row["status"], row["manual"]) == ("excluded", 1)
    assert client.post("/api/teams/t1/members/p-ann", json={"status": "inactive"}).status_code == 400
    assert client.post("/api/teams/nope/members/p-ann", json={"status": "active"}).status_code == 404


def test_mapping_an_unmapped_reviewer_into_the_team_puts_them_in_review_rankings(tmp_path):
    client, *_ = make(tmp_path)
    mapped = client.post("/api/identities", json={
        "source": "bitbucket", "account": "acc-zed", "new_name": "Zed Reviewer", "team_id": "t1"
    })
    assert mapped.status_code == 200
    rows = client.get("/api/metrics/reviews_given", params={"team": "t1", "window": "month:2026-09"}).json()["rows"]
    assert ("Zed Reviewer", 1.0) in [(r["name"], r["value"]) for r in rows]
    assert not any(r["person_id"] is None for r in rows)
    assert client.post("/api/identities", json={"source": "bitbucket", "account": "acc-q"}).status_code == 400
    assert client.post("/api/identities", json={"source": "bitbucket", "account": "acc-q",
                                                "person_id": "nobody"}).status_code == 404


def test_add_and_remove_repositories_through_the_api(tmp_path):
    fake = FakeBitbucket(token=TOKEN)
    fake.add_repo("new-repo", UUID_NEW)
    client, *_ = make(tmp_path, environ={"BITBUCKET": TOKEN, "BITBUCKET_WORKSPACE": "keyhealthtech"},
                      transport=fake.transport())
    added = client.post("/api/repos", json={"repo": "bitbucket:keyhealthtech/new-repo"})
    assert added.status_code == 200 and added.json()["repository_id"] == UUID_NEW
    assert UUID_NEW in [r["repository_id"] for r in client.get("/api/repos").json()["repos"]]
    missing = client.post("/api/repos", json={"repo": "bitbucket:keyhealthtech/nope"})
    assert missing.status_code == 400 and "was not found" in missing.json()["detail"]
    assert TOKEN not in missing.text
    assert client.delete(f"/api/repos/{UUID_NEW}").json() == {"removed": 1}
    assert client.delete(f"/api/repos/{UUID_NEW}").status_code == 404


def test_adding_a_repository_without_a_token_is_explained(tmp_path):
    client, *_ = make(tmp_path)
    response = client.post("/api/repos", json={"repo": "bitbucket:ws/x"})
    assert response.status_code == 400 and "BITBUCKET" in response.json()["detail"]


def test_refresh_starts_once_and_only_stale_skips_fresh_sources(tmp_path):
    run = FakeRun()
    client, path, worker, _ = make(tmp_path, environ={"BITBUCKET": TOKEN}, run=run)
    first = client.post("/api/refresh", json={"only_stale": True}).json()
    assert first["started"] is True  # never synced counts as stale
    worker.wait()
    conn = db.connect(path)
    sync_state.save_state(conn, "bitbucket", REPO, status="ok", error=None, records=1, now="2026-10-15T15:50:00Z")
    conn.close()
    fresh = client.post("/api/refresh", json={"only_stale": True}).json()
    assert fresh["started"] is False
    forced = client.post("/api/refresh", json={"source": "bitbucket", "full": True}).json()
    assert forced["started"] is True
    worker.wait()
    assert run.calls == [(None, False), ("bitbucket", True)]


def test_a_failed_refresh_error_is_redacted(tmp_path):
    run = FakeRun(error=f"boom {TOKEN}")
    client, _, worker, _ = make(tmp_path, environ={"BITBUCKET": TOKEN}, run=run)
    client.post("/api/refresh", json={})
    worker.wait()
    refresh = client.get("/api/sources").json()["refresh"]
    assert refresh["error"] == "boom ***" and TOKEN not in str(refresh)


def test_cross_site_writes_are_refused_but_same_origin_is_fine(tmp_path):
    client, *_ = make(tmp_path)
    blocked = client.post("/api/refresh", json={}, headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403
    ok = client.post("/api/teams/t1/members/p-bob", json={"status": "active"},
                     headers={"Origin": "http://127.0.0.1:8000"})
    assert ok.status_code == 200


def _failing_refresh_client(tmp_path):
    run = FakeRun(error=f"boom {TOKEN}")
    client, path, worker, _ = make(tmp_path, environ={"BITBUCKET": TOKEN}, run=run)
    return client, path, worker


def test_refresh_response_hides_the_token_when_nothing_is_started(tmp_path):
    client, path, worker = _failing_refresh_client(tmp_path)
    client.post("/api/refresh", json={})
    worker.wait()
    conn = db.connect(path)
    sync_state.save_state(conn, "bitbucket", REPO, status="ok", error=None, records=1, now="2026-10-15T15:50:00Z")
    conn.close()
    response = client.post("/api/refresh", json={"only_stale": True})
    assert response.json()["started"] is False
    assert TOKEN not in response.text


def test_refresh_response_hides_the_token_when_a_fast_run_already_failed(tmp_path):
    client, _, worker = _failing_refresh_client(tmp_path)
    start = worker.start

    def start_and_finish(*args):
        started = start(*args)
        worker.wait()
        return started

    worker.start = start_and_finish
    response = client.post("/api/refresh", json={})
    assert response.json()["started"] is True
    assert TOKEN not in response.text


def test_write_guard_checks_the_origin_port_and_fetch_metadata(tmp_path):
    client, *_ = make(tmp_path)
    body = {"status": "active"}
    url = "/api/teams/t1/members/p-bob"
    for origin in ("http://localhost:3000", "https://127.0.0.1:8000"):
        assert client.post(url, json=body, headers={"Origin": origin}).status_code == 403, origin
    assert client.post(url, json=body, headers={"Origin": "http://127.0.0.1:8000"}).status_code == 200
    for site in ("same-site", "cross-site"):
        assert client.post(url, json=body, headers={"Sec-Fetch-Site": site}).status_code == 403, site
    assert client.post(url, json=body, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 200


def test_team_window_days_must_be_in_range(tmp_path):
    client, *_ = make(tmp_path)
    for days in (0, 10000):
        response = client.post("/api/teams", json={"name": "Z", "repos": ["bitbucket:core-repo"], "window_days": days})
        assert response.status_code == 422, days
    assert [t["name"] for t in client.get("/api/teams").json()["teams"]] == ["Core"]


def test_a_recently_failed_source_does_not_restart_a_sync_but_an_old_failure_does(tmp_path):
    run = FakeRun()
    client, path, worker, _ = make(tmp_path, environ={"BITBUCKET": TOKEN}, run=run)
    conn = db.connect(path)
    sync_state.save_state(conn, "bitbucket", REPO, status="failed", error="rate limited", records=0,
                          now="2026-10-15T15:55:00Z")
    conn.close()
    assert client.post("/api/refresh", json={"only_stale": True}).json()["started"] is False
    conn = db.connect(path)
    sync_state.save_state(conn, "bitbucket", REPO, status="failed", error="rate limited", records=0,
                          now="2026-10-15T14:59:00Z")
    conn.close()
    assert client.post("/api/refresh", json={"only_stale": True}).json()["started"] is True
    worker.wait()
