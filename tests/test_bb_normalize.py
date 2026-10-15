import json

import pytest

from delivery_analysis.connectors.bitbucket import normalize as n

UUID = "{11111111-1111-1111-1111-111111111111}"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Ann Example <Ann@Corp.Example>", ("Ann Example", "ann@corp.example")),
        ("Ann Example <>", ("Ann Example", "")),
        ("Ann Example", ("Ann Example", "")),
        ("ann@corp.example", ("", "ann@corp.example")),
        ("", ("", "")),
        (None, ("", "")),
        ("Build Bot <noreply@corp.example>", ("Build Bot", "noreply@corp.example")),
        ("Odd <Name> <x@corp.example>", ("Odd <Name>", "x@corp.example")),
    ],
)
def test_parse_author_raw(raw, expected):
    assert n.parse_author_raw(raw) == expected


def test_repository_record_uses_the_uuid_and_slug():
    data = {"uuid": UUID, "slug": "movedocs_v1.0", "mainbranch": {"name": "main"}}
    record, raw = n.repository_record("keyhealthtech", data)
    assert record.table == "repository"
    assert record.values == {
        "source": "bitbucket", "source_id": UUID, "workspace": "keyhealthtech",
        "name": "movedocs_v1.0", "default_branch": "main",
    }
    assert (raw.kind, raw.source_id) == ("repository", UUID)
    assert json.loads(raw.json)["slug"] == "movedocs_v1.0"


def test_repository_record_tolerates_an_empty_repository():
    record, _ = n.repository_record("ws", {"uuid": UUID, "slug": "empty"})
    assert record.values["default_branch"] is None


def commit(**overrides):
    base = {
        "hash": "abc123",
        "date": "2026-09-01T12:00:00+00:00",
        "author": {"raw": "Ann Example <ann@corp.example>", "user": {"account_id": "acc-ann"}},
        "parents": [{"hash": "p1"}],
    }
    base.update(overrides)
    return base


def test_commit_record_fields():
    records, raw = n.commit_records(UUID, commit())
    assert [r.table for r in records] == ["vcs_commit"]
    assert records[0].values == {
        "source": "bitbucket", "source_id": f"{UUID}:abc123", "repository_id": UUID, "sha": "abc123",
        "author_account": "acc-ann", "author_name": "Ann Example", "author_email": "ann@corp.example",
        "committed_at": "2026-09-01T12:00:00Z",
    }
    assert raw.kind == "commit"


def test_a_merge_commit_gets_a_property():
    records, _ = n.commit_records(UUID, commit(parents=[{"hash": "p1"}, {"hash": "p2"}]))
    props = [r for r in records if r.table == "property"]
    assert [(p.values["record_kind"], p.values["name"], p.values["value"]) for p in props] == [
        ("vcs_commit", "is_merge", "1")
    ]


def test_unmapped_and_blank_authors_become_empty_not_errors():
    bare = commit(author={"raw": "Build Bot <>"})
    records, _ = n.commit_records(UUID, bare)
    values = records[0].values
    assert (values["author_account"], values["author_name"], values["author_email"]) == (None, "Build Bot", None)
    records, _ = n.commit_records(UUID, commit(author={}))
    assert records[0].values["author_email"] is None


def pr(**overrides):
    base = {
        "id": 7, "title": "Change", "state": "MERGED", "author": {"account_id": "acc-ann"},
        "source": {"branch": {"name": "feature/x"}},
        "created_on": "2026-09-01T10:00:00.123456+00:00", "updated_on": "2026-09-03T11:30:00.654321+00:00",
    }
    base.update(overrides)
    return base


def by_table(records):
    out = {}
    for record in records:
        out.setdefault(record.table, []).append(record)
    return out


def test_a_merged_pull_request_gets_approximate_times_from_updated_on():
    records, raw = n.pull_request_records(UUID, pr())
    parts = by_table(records)
    values = parts["change_request"][0].values
    assert values["source_id"] == f"{UUID}#7" and values["number"] == "7"
    assert values["merged_at"] == values["closed_at"] == "2026-09-03T11:30:00Z"
    assert values["created_at"] == "2026-09-01T10:00:00Z"
    assert (values["branch"], values["title"], values["state"]) == ("feature/x", "Change", "MERGED")
    props = {p.values["name"]: p.values["value"] for p in parts["property"]}
    assert props == {"updated_on": "2026-09-03T11:30:00Z", "times_from": "updated_on"}
    assert raw.kind == "pull_request"


def test_declined_and_open_pull_requests_get_the_right_approximations():
    declined = by_table(n.pull_request_records(UUID, pr(state="DECLINED"))[0])["change_request"][0].values
    assert declined["closed_at"] == "2026-09-03T11:30:00Z" and "merged_at" not in declined
    opened = by_table(n.pull_request_records(UUID, pr(state="OPEN"))[0])["change_request"][0].values
    assert "merged_at" not in opened and "closed_at" not in opened


def test_assigned_reviewers_are_stored_with_their_state():
    participants = [
        {"role": "REVIEWER", "approved": True, "user": {"account_id": "acc-bob"}},
        {"role": "REVIEWER", "approved": False, "user": {"account_id": "acc-cy"}},
        {"role": "PARTICIPANT", "approved": False, "user": {"account_id": "acc-dee"}},
        {"role": "REVIEWER", "approved": False, "user": {}},
    ]
    records, _ = n.pull_request_records(UUID, pr(participants=participants))
    props = {p.values["name"]: p.values["value"] for p in by_table(records)["property"]}
    assert props["reviewer:acc-bob"] == "approved"
    assert props["reviewer:acc-cy"] == "pending"
    assert not any(name.startswith("reviewer:acc-dee") for name in props)
    assert sum(1 for name in props if name.startswith("reviewer:")) == 2


def test_a_detailed_pull_request_is_not_given_approximate_times():
    records, _ = n.pull_request_records(UUID, pr(), include_times=False)
    parts = by_table(records)
    assert "merged_at" not in parts["change_request"][0].values
    assert [p.values["name"] for p in parts["property"]] == ["updated_on"]


def test_activity_becomes_events_and_exact_times():
    sid = f"{UUID}#7"
    items = [
        {"comment": {"id": 11, "created_on": "2026-09-02T09:00:00.1+00:00", "user": {"account_id": "acc-bob"}}},
        {"comment": {"id": 12, "created_on": "2026-09-02T09:05:00+00:00", "deleted": True, "user": {"account_id": "acc-bob"}}},
        {"approval": {"date": "2026-09-02T10:00:00+00:00", "user": {"account_id": "acc-bob"}}},
        {"update": {"state": "OPEN", "date": "2026-09-01T10:00:00+00:00", "author": {"account_id": "acc-ann"}}},
        {"update": {"state": "MERGED", "date": "2026-09-03T11:00:00+00:00", "author": {"account_id": "acc-ann"}}},
    ]
    events, summary = n.activity_records(sid, items)
    got = sorted((e.values["type"], e.values["occurred_at"], e.values["actor_account"]) for e in events)
    assert got == [
        ("approved", "2026-09-02T10:00:00Z", "acc-bob"),
        ("comment", "2026-09-02T09:00:00Z", "acc-bob"),
        ("merged", "2026-09-03T11:00:00Z", "acc-ann"),
        ("update", "2026-09-01T10:00:00Z", "acc-ann"),
    ]
    assert all(e.values["change_request_id"] == sid for e in events)
    assert len({e.values["source_id"] for e in events}) == 4
    assert (summary.merged_at, summary.closed_at) == ("2026-09-03T11:00:00Z", "2026-09-03T11:00:00Z")


def test_a_declined_pull_request_has_a_close_time_but_no_merge_time():
    items = [{"update": {"state": "DECLINED", "date": "2026-09-04T08:00:00+00:00", "author": {"account_id": "acc-ann"}}}]
    events, summary = n.activity_records("sid", items)
    assert [e.values["type"] for e in events] == ["declined"]
    assert (summary.merged_at, summary.closed_at) == (None, "2026-09-04T08:00:00Z")


def test_commit_links_only_carry_the_link_columns():
    records = n.commit_link_records(UUID, f"{UUID}#7", [{"hash": "abc123"}, {"hash": "def456"}])
    assert [r.table for r in records] == ["vcs_commit", "vcs_commit"]
    assert records[0].values == {
        "source": "bitbucket", "source_id": f"{UUID}:abc123", "repository_id": UUID,
        "sha": "abc123", "change_request_id": f"{UUID}#7",
    }
