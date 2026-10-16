import hashlib

import pytest

from delivery_analysis.linking import pr_keys as pk
from delivery_analysis.model.records import Record
from delivery_analysis.store.upsert import upsert_record

NOW = "2026-10-15T12:00:00Z"
REPO = "{11111111-1111-1111-1111-111111111111}"


def jira_item(conn, issue_id, key, project="MD"):
    upsert_record(conn, Record("work_item", {"source": "jira", "source_id": issue_id, "project": project, "key": key}), NOW)


def pr(conn, number, title, branch, author="acc-ann", source="bitbucket"):
    upsert_record(
        conn,
        Record("change_request", {
            "source": source, "source_id": f"{REPO}#{number}", "repository_id": REPO, "number": str(number),
            "author_account": author, "title": title, "branch": branch, "state": "MERGED",
        }),
        NOW,
    )
    return f"{REPO}#{number}"


def links(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM link ORDER BY from_id, to_id, found_by")]


def test_a_key_in_the_title_links_the_pull_request_to_the_issue(conn):
    jira_item(conn, "1001", "MD-12")
    sid = pr(conn, 1, "MD-12 add export", "feature/export")
    coverage = pk.link_pull_requests(conn, NOW)
    (row,) = links(conn)
    assert row["source"] == "linker" and row["kind"] == "implements" and row["found_by"] == "pr_title"
    assert (row["from_kind"], row["from_id"], row["to_kind"], row["to_id"]) == ("change_request", sid, "work_item", "1001")
    assert row["source_id"] == hashlib.sha1(f"{sid}|1001|implements|pr_title".encode()).hexdigest()
    assert (coverage.total, coverage.linked, coverage.links) == (1, 1, 1)


def test_a_key_in_the_branch_links_and_title_plus_branch_give_two_rows_but_one_linked_pull_request(conn):
    jira_item(conn, "1001", "MD-12")
    pr(conn, 1, "export", "feature/MD-12-export")
    pr(conn, 2, "MD-12 export", "bugfix/MD-12_x")
    coverage = pk.link_pull_requests(conn, NOW)
    assert [(r["found_by"]) for r in links(conn)] == ["pr_branch", "pr_branch", "pr_title"]
    assert (coverage.total, coverage.linked, coverage.links) == (2, 2, 3)


def test_several_keys_make_several_links(conn):
    jira_item(conn, "1001", "MD-1")
    jira_item(conn, "1002", "MD-2")
    pr(conn, 1, "MD-1 and MD-2 together", "feature/x")
    pk.link_pull_requests(conn, NOW)
    assert sorted(r["to_id"] for r in links(conn)) == ["1001", "1002"]


@pytest.mark.parametrize(
    "title",
    ["md-1 lowercase", "XMD-1 prefixed", "MD-1abc suffixed", "MD-123456789 too long", "UTF-8 and SHA-256", "OTHER-1 elsewhere"],
)
def test_text_that_only_looks_like_a_key_is_ignored(conn, title):
    jira_item(conn, "1001", "MD-1")
    pr(conn, 1, title, "feature/none")
    coverage = pk.link_pull_requests(conn, NOW)
    assert links(conn) == [] and coverage.linked == 0 and coverage.unknown_keys == 0


def test_a_key_that_is_not_in_the_store_is_counted_but_not_linked(conn):
    jira_item(conn, "1001", "MD-1")
    pr(conn, 1, "MD-999 never synced", "feature/x")
    coverage = pk.link_pull_requests(conn, NOW)
    assert links(conn) == [] and coverage.unknown_keys == 1 and coverage.linked == 0


def test_only_bitbucket_pull_requests_are_scanned(conn):
    jira_item(conn, "1001", "MD-1")
    pr(conn, 1, "MD-1 from elsewhere", "feature/x", source="github")
    coverage = pk.link_pull_requests(conn, NOW)
    assert links(conn) == [] and coverage.total == 0


def test_a_rerun_writes_the_same_rows(conn):
    jira_item(conn, "1001", "MD-1")
    pr(conn, 1, "MD-1 thing", "feature/MD-1")
    pk.link_pull_requests(conn, NOW)
    first = [r["source_id"] for r in links(conn)]
    pk.link_pull_requests(conn, "2026-10-16T12:00:00Z")
    assert [r["source_id"] for r in links(conn)] == first


def test_coverage_lines_name_the_authors_with_the_most_unlinked_pull_requests(conn):
    jira_item(conn, "1001", "MD-1")
    pr(conn, 1, "MD-1 done", "feature/a", author="acc-ann")
    pr(conn, 2, "no key", "feature/b", author="acc-bob")
    pr(conn, 3, "no key either", "feature/c", author="acc-bob")
    pr(conn, 4, "none", "feature/d", author=None)
    coverage = pk.link_pull_requests(conn, NOW)
    assert coverage.lines() == [
        "Issue links: 1 of 4 pull requests have an issue key.",
        "  most unlinked pull requests by author: acc-bob (2), unknown (1)",
    ]


def test_without_any_jira_project_the_pass_says_so_and_writes_nothing(conn):
    pr(conn, 1, "MD-1 thing", "feature/MD-1")
    coverage = pk.link_pull_requests(conn, NOW)
    assert links(conn) == [] and coverage.projects == 0
    assert "no Jira project has been synced" in coverage.lines()[0]


def test_the_pattern_is_built_from_known_projects_longest_first():
    pattern = pk.key_pattern(["M", "MD", "MD2"])
    assert [m.group(0) for m in pattern.finditer("MD2-5 MD-7 M-1")] == ["MD2-5", "MD-7", "M-1"]
    assert pk.key_pattern([]) is None
