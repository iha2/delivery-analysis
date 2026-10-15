import pytest

from delivery_analysis.model.records import Record
from delivery_analysis.store import repo_selection as rs
from delivery_analysis.store.upsert import upsert_record

NOW = "2026-10-15T00:00:00Z"
UUID_A = "{11111111-1111-1111-1111-111111111111}"
UUID_B = "{22222222-2222-2222-2222-222222222222}"


def test_add_is_an_upsert_and_list_is_sorted(conn):
    rs.add_repo(conn, "bitbucket", UUID_B, "keyhealthtech", "zeta", NOW)
    rs.add_repo(conn, "bitbucket", UUID_A, "keyhealthtech", "alpha", NOW)
    rs.add_repo(conn, "bitbucket", UUID_A, "keyhealthtech", "alpha-renamed", NOW)
    rows = rs.list_selected(conn, "bitbucket")
    assert [(r["slug"], r["repository_id"]) for r in rows] == [("alpha-renamed", UUID_A), ("zeta", UUID_B)]
    assert rs.list_selected(conn, "jira") == []
    assert len(rs.list_selected(conn)) == 2


@pytest.mark.parametrize("text", [UUID_A, "alpha", "ALPHA", "keyhealthtech/alpha", "KeyHealthTech/Alpha"])
def test_resolve_and_remove_accept_uuid_slug_and_full_name(conn, text):
    rs.add_repo(conn, "bitbucket", UUID_A, "keyhealthtech", "alpha", NOW)
    assert rs.resolve(conn, "bitbucket", text) == UUID_A
    assert rs.remove_repo(conn, "bitbucket", text) == 1
    assert rs.list_selected(conn) == []


def test_resolve_leaves_unknown_text_unchanged_and_remove_reports_zero(conn):
    assert rs.resolve(conn, "bitbucket", "nothing") == "nothing"
    assert rs.remove_repo(conn, "bitbucket", "nothing") == 0


def test_detail_progress_counts_pull_requests_by_marker(conn):
    def prop(record_id, name, value):
        upsert_record(
            conn,
            Record("property", {"record_kind": "change_request", "record_id": record_id, "name": name, "value": value}),
            NOW,
        )

    for number, detailed in ((1, "2026-09-01T00:00:00Z"), (2, "2026-08-01T00:00:00Z"), (3, None)):
        sid = f"{UUID_A}#{number}"
        prop(sid, "updated_on", "2026-09-01T00:00:00Z")
        if detailed:
            prop(sid, "detail_updated_on", detailed)
    prop(f"{UUID_B}#1", "updated_on", "2026-09-01T00:00:00Z")
    # PR 1 is current, PR 2 was detailed before its last update, PR 3 never was
    assert rs.detail_progress(conn, UUID_A) == (1, 3)
    assert rs.detail_progress(conn, UUID_B) == (0, 1)
