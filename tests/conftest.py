import itertools

import pytest

from delivery_analysis.model.records import Record
from delivery_analysis.store import db
from delivery_analysis.store.upsert import upsert_record


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "teams.sqlite")
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def add_commit(conn):
    counter = itertools.count(1)

    def _add(email, name, day, repo="r1", source="bitbucket", account=None):
        n = next(counter)
        values = {
            "source": source,
            "source_id": f"c{n}",
            "repository_id": repo,
            "sha": f"sha{n}",
            "author_email": email,
            "author_name": name,
            "committed_at": f"{day}T12:00:00Z",
        }
        if account:
            values["author_account"] = account
        upsert_record(conn, Record("vcs_commit", values), "2026-10-15T00:00:00Z")

    return _add


@pytest.fixture
def make_id():
    counter = itertools.count(1)
    return lambda: f"id{next(counter)}"
