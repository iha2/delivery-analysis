from __future__ import annotations

import json

from delivery_analysis.code.changes import parse_hunks, read_commit_files
from delivery_analysis.store.db import connect, migrate
from tests.git_fakes import BO, git, make_repo, shas

REPO = "{r-1}"
NOW = "2026-01-01T00:00:00+00:00"


def _conn():
    conn = connect(":memory:")
    migrate(conn)
    return conn


def _add_commit(conn, sha, pr="pr1", repo=REPO):
    conn.execute(
        "INSERT INTO vcs_commit (source, source_id, repository_id, sha, change_request_id, fetched_at) "
        "VALUES ('bitbucket', ?, ?, ?, ?, ?)",
        (repo + ":" + sha, repo, sha, pr, NOW),
    )


def test_parse_hunks_ranges():
    diff = (
        "diff --git a/src/a.py b/src/a.py\n"
        "--- a/src/a.py\n+++ b/src/a.py\n"
        "@@ -1,0 +2,3 @@ def f\n+x\n+y\n+z\n"
        "@@ -10 +14 @@\n-a\n+b\n"
        "@@ -20,2 +30,0 @@\n-gone\n-gone\n"
        "diff --git a/old.txt b/old.txt\ndeleted file mode 100644\n"
        "--- a/old.txt\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"
        "diff --git a/new.txt b/new.txt\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1,2 @@\n+a\n+b\n"
    )
    got = parse_hunks(diff)
    assert got["src/a.py"] == [(2, 4), (14, 14), (30, 30)]
    assert "old.txt" not in got
    assert got["new.txt"] == [(1, 2)]


def test_parse_hunks_empty():
    assert parse_hunks("") == {}


def test_read_commit_files_rows(tmp_path):
    origin = make_repo(
        tmp_path,
        [
            {"files": {"src/a.py": "a\nb\nc\n", "keep.txt": "k\n"}},
            {"files": {"src/a.py": "a\nB\nc\nd\n", "src/new dir/n.py": "n\n", "keep.txt": None}},
            {"files": {"img.bin": b"\x00\x01\x02\xff" * 10}},
        ],
    )
    s = shas(origin)
    conn = _conn()
    for sha in s:
        _add_commit(conn, sha)
    summary = read_commit_files(conn, REPO, origin, NOW)
    assert (summary.read, summary.missing, summary.skipped_merges) == (3, 0, 0)

    rows = {
        (r["sha"], r["path"]): r
        for r in conn.execute("SELECT * FROM commit_file WHERE repository_id = ?", (REPO,))
    }
    a = rows[(s[1], "src/a.py")]
    assert (a["lines_added"], a["lines_removed"]) == (2, 1)
    assert json.loads(a["hunks"]) == [[2, 2], [4, 4]]
    assert rows[(s[1], "src/new dir/n.py")]["lines_added"] == 1
    gone = rows[(s[1], "keep.txt")]
    assert (gone["lines_added"], gone["lines_removed"]) == (0, 1)
    assert json.loads(gone["hunks"]) == []
    assert json.loads(rows[(s[0], "src/a.py")]["hunks"]) == [[1, 3]]
    binary = rows[(s[2], "img.bin")]
    assert (binary["lines_added"], binary["lines_removed"]) == (0, 0)
    assert json.loads(binary["hunks"]) == []
    assert a["fetched_at"] == NOW


def test_second_run_reads_nothing(tmp_path):
    origin = make_repo(tmp_path, [{"files": {"a.py": "x\n"}}])
    conn = _conn()
    _add_commit(conn, shas(origin)[0])
    assert read_commit_files(conn, REPO, origin, NOW).read == 1
    again = read_commit_files(conn, REPO, origin, NOW)
    assert (again.read, again.missing) == (0, 0)


def test_missing_sha_counted_not_error(tmp_path):
    origin = make_repo(tmp_path, [{"files": {"a.py": "x\n"}}])
    conn = _conn()
    _add_commit(conn, shas(origin)[0])
    _add_commit(conn, "f" * 40, pr="pr2")
    summary = read_commit_files(conn, REPO, origin, NOW)
    assert (summary.read, summary.missing) == (1, 1)


def test_commits_without_pr_or_other_repo_ignored(tmp_path):
    origin = make_repo(tmp_path, [{"files": {"a.py": "x\n"}}])
    sha = shas(origin)[0]
    conn = _conn()
    conn.execute(
        "INSERT INTO vcs_commit (source, source_id, repository_id, sha, change_request_id, fetched_at) "
        "VALUES ('bitbucket', 'x:1', ?, ?, NULL, ?)",
        (REPO, sha, NOW),
    )
    _add_commit(conn, sha, repo="{other}")
    summary = read_commit_files(conn, REPO, origin, NOW)
    assert (summary.read, summary.missing, summary.skipped_merges) == (0, 0, 0)


def test_merge_commit_skipped(tmp_path):
    origin = make_repo(tmp_path, [{"files": {"a.py": "1\n"}}])
    git(origin, "checkout", "-q", "-b", "side")
    (origin / "s.py").write_text("s\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "side", author=BO)
    git(origin, "checkout", "-q", "main")
    (origin / "m.py").write_text("m\n")
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", "main")
    git(origin, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    merge = git(origin, "rev-parse", "HEAD")
    conn = _conn()
    _add_commit(conn, merge)
    summary = read_commit_files(conn, REPO, origin, NOW)
    assert (summary.read, summary.skipped_merges) == (0, 1)
    assert conn.execute("SELECT COUNT(*) FROM commit_file").fetchone()[0] == 0


def test_rename_uses_new_path(tmp_path):
    body = "".join("line %d\n" % i for i in range(20))
    origin = make_repo(
        tmp_path,
        [{"files": {"old.py": body}}, {"files": {"old.py": None, "pkg/new.py": body}}],
    )
    conn = _conn()
    _add_commit(conn, shas(origin)[1])
    read_commit_files(conn, REPO, origin, NOW)
    paths = [r["path"] for r in conn.execute("SELECT path FROM commit_file")]
    assert paths == ["pkg/new.py"]
