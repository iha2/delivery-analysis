from bitbucket_fakes import FakeBitbucket, api_comment, approval, comment, commit, pr, recent, update
from delivery_analysis.connectors.bitbucket import normalize
from delivery_analysis.connectors.bitbucket.client import BitbucketClient
from delivery_analysis.connectors.bitbucket.connector import BitbucketConnector
from delivery_analysis.store import db, repo_selection
from delivery_analysis.sync.runner import run_sync

UUID_A = "{11111111-1111-1111-1111-111111111111}"
NOW = "2026-10-15T00:00:00Z"
ANN = "Ann Example <ann@corp.example>"
PR = f"{UUID_A}#3"


def build(tmp_path, fake):
    path = tmp_path / "d.sqlite"
    conn = db.connect(path)
    db.migrate(conn)
    repo_selection.add_repo(conn, "bitbucket", UUID_A, fake.workspace, "movedocs_v1.0", NOW)
    return conn, path


def connector_for(path, fake, budget=900):
    client = BitbucketClient(fake.token, transport=fake.transport(), sleep=lambda s: None, budget=budget)
    return BitbucketConnector(client, path, window_days=90)


def rows(conn, sql, *params):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def standard(fake):
    fake.add_repo(
        "movedocs_v1.0", UUID_A,
        commits=[commit("h1", ANN, recent(1))],
        prs=[pr(3, "MERGED", recent(1)), pr(2, "OPEN", recent(2)), pr(1, "DECLINED", recent(3))],
        activity={
            3: [update("OPEN", recent(4)), comment(31, recent(3)), comment(32, recent(3), deleted=True),
                comment(33, recent(3)), comment(34, recent(3)), approval(recent(2)), update("MERGED", recent(2))],
            2: [comment(21, recent(2))],
            1: [update("DECLINED", recent(3))],
        },
        pr_commits={3: [{"hash": "h1"}], 2: [], 1: []},
        diffstat={3: [{"status": "modified"}], 2: [], 1: []},
        comments={
            3: [
                api_comment(31, "2026-10-10T12:00:00-04:00", path="src/app.py", to=42, from_=40, resolution={"type": "x"}),
                api_comment(32, recent(3), deleted=True),
                api_comment(33, recent(3), account="acc-ann", parent=31),
                api_comment(34, recent(3), path="src/old.py", from_=7),
            ],
            2: [api_comment(21, recent(2))],
            1: [],
        },
    )


# --- mapping ---------------------------------------------------------------------------------

def test_mapping_inline_general_reply_deleted_and_resolved():
    items = [
        api_comment(31, "2026-10-10T12:00:00-04:00", path="src/app.py", to=42, from_=40, resolution={"type": "x"}),
        api_comment(32, "2026-10-10T12:00:00Z", deleted=True),
        api_comment(33, "2026-10-10T13:00:00Z", account="acc-ann", parent=31),
        api_comment(34, "2026-10-10T14:00:00Z", path="src/old.py", from_=7),
    ]
    records = normalize.review_comment_records(PR, items)
    assert {r.table for r in records} == {"review_comment"}
    by_id = {r.values["source_id"]: r.values for r in records}
    assert set(by_id) == {f"{PR}:comment:31", f"{PR}:comment:33", f"{PR}:comment:34"}
    inline = by_id[f"{PR}:comment:31"]
    assert inline["source"] == "bitbucket"
    assert inline["change_request_id"] == PR
    assert inline["actor_account"] == "acc-bob"
    assert inline["created_at"] == "2026-10-10T16:00:00Z"
    assert (inline["path"], inline["line"], inline["parent_id"], inline["resolved"]) == ("src/app.py", 42, None, 1)
    reply = by_id[f"{PR}:comment:33"]
    assert (reply["path"], reply["line"], reply["resolved"]) == (None, None, 0)
    assert reply["parent_id"] == f"{PR}:comment:31"
    assert by_id[f"{PR}:comment:34"]["line"] == 7  # only the old side: falls back to `from`


def test_mapping_empty_list():
    assert normalize.review_comment_records(PR, []) == []


# --- detail stage ----------------------------------------------------------------------------

def test_detail_stores_comments_and_marker(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    stored = rows(conn, "SELECT * FROM review_comment WHERE change_request_id = ? ORDER BY source_id", PR)
    assert [r["source_id"].rsplit(":", 1)[1] for r in stored] == ["31", "33", "34"]
    inline = stored[0]
    assert (inline["path"], inline["line"], inline["resolved"]) == ("src/app.py", 42, 1)
    # same ids as the change_event rows
    event_ids = {r["source_id"] for r in rows(conn, "SELECT source_id FROM change_event WHERE type = 'comment'")}
    assert {r["source_id"] for r in stored} <= event_ids
    markers = rows(conn, "SELECT record_id, value FROM property WHERE name = 'comments_detail_on'")
    assert len(markers) == 3
    detail = {r["record_id"]: r["value"] for r in rows(conn, "SELECT record_id, value FROM property WHERE name = 'detail_updated_on'")}
    assert {r["record_id"]: r["value"] for r in markers} == detail


def test_comments_request_uses_pagelen_100_and_fields(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    calls = [params for p, params in fake.requests if p.endswith("/pullrequests/3/comments")]
    assert len(calls) == 1
    assert calls[0]["pagelen"] == ["100"]
    fields = calls[0]["fields"][0]
    for name in ("next", "values.id", "values.user.account_id", "values.created_on", "values.deleted",
                 "values.inline", "values.parent.id", "values.resolution"):
        assert name in fields.split(",")


def test_a_second_sync_does_not_refetch_comments(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    before = fake.count("/comments")
    run_sync(conn, [connector_for(path, fake)])
    assert fake.count("/comments") == before


def test_missing_comments_endpoint_still_marks_the_pull_request(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    fake.errors["/pullrequests/2/comments"] = 404
    conn, path = build(tmp_path, fake)
    results = run_sync(conn, [connector_for(path, fake)])
    assert results[0].status == "ok"
    marker = rows(conn, "SELECT value FROM property WHERE record_id = ? AND name = 'comments_detail_on'", f"{UUID_A}#2")
    assert len(marker) == 1
    assert rows(conn, "SELECT 1 FROM review_comment WHERE change_request_id = ?", f"{UUID_A}#2") == []


# --- backfill --------------------------------------------------------------------------------

def forget_comments(conn):
    conn.execute("DELETE FROM property WHERE name = 'comments_detail_on'")
    conn.execute("DELETE FROM review_comment")
    conn.commit()


def test_backfill_fetches_only_comments_for_previously_detailed_prs(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    forget_comments(conn)
    activity_before = fake.count("/activity")
    comments_before = fake.count("/comments")
    run_sync(conn, [connector_for(path, fake)])
    assert fake.count("/activity") == activity_before
    assert fake.count("/comments") == comments_before + 3
    assert len(rows(conn, "SELECT 1 FROM review_comment")) == 4
    assert len(rows(conn, "SELECT 1 FROM property WHERE name = 'comments_detail_on'")) == 3


def test_backfill_is_newest_first_and_respects_the_budget_then_resumes(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    run_sync(conn, [connector_for(path, fake)])
    forget_comments(conn)
    before = fake.count("/comments")
    # validate 2 + repository 1 + commits 1 + pull request list 1 = 5; two comment requests left
    first = run_sync(conn, [connector_for(path, fake, budget=7)])
    assert first[0].status == "ok"
    assert fake.count("/comments") == before + 2
    done = {r["record_id"] for r in rows(conn, "SELECT record_id FROM property WHERE name = 'comments_detail_on'")}
    assert done == {f"{UUID_A}#3", f"{UUID_A}#2"}
    second = run_sync(conn, [connector_for(path, fake, budget=6)])
    assert second[0].status == "ok"
    assert fake.count("/comments") == before + 3
    assert len(rows(conn, "SELECT 1 FROM property WHERE name = 'comments_detail_on'")) == 3


def test_detail_resumes_across_runs_and_collects_comments_for_every_pr(tmp_path):
    fake = FakeBitbucket()
    standard(fake)
    conn, path = build(tmp_path, fake)
    # 5 requests before detail; each detailed pull request is 4 requests (activity, commits, diffstat, comments)
    run_sync(conn, [connector_for(path, fake, budget=9)])
    assert repo_selection.detail_progress(conn, UUID_A) == (1, 3)
    assert len(rows(conn, "SELECT 1 FROM property WHERE name = 'comments_detail_on'")) == 1
    run_sync(conn, [connector_for(path, fake, budget=13)])
    assert repo_selection.detail_progress(conn, UUID_A) == (3, 3)
    assert len(rows(conn, "SELECT 1 FROM property WHERE name = 'comments_detail_on'")) == 3
    assert len(rows(conn, "SELECT 1 FROM review_comment")) == 4
