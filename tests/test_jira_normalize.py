import json

import pytest

from delivery_analysis.connectors.jira import normalize as n
from delivery_analysis.connectors.jira.fields import FieldCatalogue
from delivery_analysis.connectors.jira.statuses import SEED
from jira_fakes import DEFAULT_FIELDS, history, issue, user

CAT = FieldCatalogue(DEFAULT_FIELDS)
PROJECT = {"story_points_field": "customfield_10004", "excluded_types": "Epic,Initiative"}


def rows(result, table):
    return [r.values for r in result.records if r.table == table]


def props(result, kind="work_item"):
    return {r.values["name"]: r.values for r in result.records if r.table == "property" and r.values["record_kind"] == kind}


def make(issue_dict, histories=()):
    return n.issue_records(issue_dict, PROJECT, SEED, CAT, list(histories))


def test_timestamps_accept_offsets_without_a_colon_and_epoch_milliseconds():
    assert n.ts_to_utc_iso("2026-10-01T09:00:00.832-0700") == "2026-10-01T16:00:00Z"
    assert n.ts_to_utc_iso("2026-10-01T09:00:00.000+0000") == "2026-10-01T09:00:00Z"
    assert n.ts_to_utc_iso(1790000000000) == "2026-09-21T14:13:20Z"
    assert n.ts_to_utc_iso("1790000000000") == "2026-09-21T14:13:20Z"
    assert n.ts_to_utc_iso(None) is None and n.ts_to_utc_iso("") is None
    with pytest.raises(ValueError):
        n.ts_to_utc_iso("yesterday")
    with pytest.raises(ValueError):
        n.ts_to_utc_iso(True)


def test_status_transitions_keep_only_status_items_sorted_by_time():
    late = history(11, "2026-10-05T10:00:00Z", "In Progress", "COMPLETED")
    early = history(10, "2026-10-02T10:00:00Z", "To Do", "In Progress", author=None)
    other = history(12, "2026-10-03T10:00:00Z", "a", "b", field_id="assignee")
    found = n.status_transitions([late, other, early])
    assert [(t.history_id, t.from_status, t.to_status, t.actor, t.occurred_at) for t in found] == [
        ("10", "To Do", "In Progress", None, "2026-10-02T10:00:00Z"),
        ("11", "In Progress", "COMPLETED", "acc-ann", "2026-10-05T10:00:00Z"),
    ]
    assert n.status_transitions([{"id": "1", "created": "2026-10-02T10:00:00.000+0000", "items": [
        {"fieldId": "status", "fromString": "To Do", "toString": "In Progress"}]}])[0].occurred_at == "2026-10-02T10:00:00Z"


def lifecycle(steps, current):
    transitions = n.status_transitions(
        [history(i + 1, when, a, b) for i, (when, a, b) in enumerate(steps)]
    )
    return n.lifecycle(transitions, SEED, current)


def test_lifecycle_started_at_first_in_progress_and_resolved_at_last_done():
    result = lifecycle(
        [("2026-10-02T10:00:00Z", "To Do", "In Progress"),
         ("2026-10-03T10:00:00Z", "In Progress", "COMPLETED"),
         ("2026-10-04T10:00:00Z", "COMPLETED", "In Progress"),
         ("2026-10-06T10:00:00Z", "In Progress", "COMPLETED")],
        "done",
    )
    assert (result.started_at, result.resolved_at, result.reopen_count) == (
        "2026-10-02T10:00:00Z", "2026-10-06T10:00:00Z", 1
    )


def test_a_reopened_issue_that_is_not_done_now_has_no_resolved_time():
    result = lifecycle(
        [("2026-10-02T10:00:00Z", "To Do", "In Progress"),
         ("2026-10-03T10:00:00Z", "In Progress", "COMPLETED"),
         ("2026-10-04T10:00:00Z", "COMPLETED", "In Progress")],
        "in_progress",
    )
    assert (result.started_at, result.resolved_at, result.reopen_count) == ("2026-10-02T10:00:00Z", None, 1)


def test_dropped_is_never_done_and_a_skipped_in_progress_has_no_start():
    result = lifecycle([("2026-10-03T10:00:00Z", "To Do", "DISREGARD")], "dropped")
    assert (result.started_at, result.resolved_at, result.reopen_count) == (None, None, 0)
    skipped = lifecycle([("2026-10-03T10:00:00Z", "Code Review", "COMPLETED")], "done")
    assert (skipped.started_at, skipped.resolved_at) == (None, "2026-10-03T10:00:00Z")


def test_names_missing_from_the_map_are_reported_not_fatal():
    transitions = n.status_transitions([history(1, "2026-10-02T10:00:00Z", "Old Status", "In Progress")])
    result = n.lifecycle(transitions, SEED, "in_progress")
    assert result.unknown_statuses == ("Old Status",)
    assert result.started_at == "2026-10-02T10:00:00Z"


def test_work_item_columns():
    ann = user("acc-ann", "Ann Example", "ann@corp.example")
    bob = user("acc-bob", "Bob Builder")
    result = make(
        issue(7001, "MD-7", status="COMPLETED", assignee=ann, reporter=bob, points=5, type="Story"),
        [history(1, "2026-10-02T10:00:00Z", "To Do", "In Progress"),
         history(2, "2026-10-03T10:00:00Z", "In Progress", "COMPLETED")],
    )
    (item,) = rows(result, "work_item")
    assert item == {
        "source": "jira", "source_id": "7001", "project": "MD", "key": "MD-7", "type": "Story",
        "summary": "Summary of MD-7", "assignee_account": "acc-ann", "reporter_account": "acc-bob",
        "status": "COMPLETED", "status_category": "done", "created_at": "2026-10-01T16:00:00Z",
        "started_at": "2026-10-02T10:00:00Z", "resolved_at": "2026-10-03T10:00:00Z", "story_points": 5.0,
    }
    assert result.updated == "2026-10-14T17:00:00Z"


def test_unassigned_and_unpointed_issues_have_nulls_not_zeros():
    (item,) = rows(make(issue(7002, "MD-8")), "work_item")
    assert item["assignee_account"] is None and item["reporter_account"] is None
    assert item["story_points"] is None and item["started_at"] is None and item["resolved_at"] is None


def test_the_points_field_is_per_project_and_may_be_unset():
    other = n.issue_records(issue(1, "MD-1", points=3, extra={"customfield_11168": 8}),
                            {"story_points_field": "customfield_11168", "excluded_types": ""}, SEED, CAT, [])
    assert rows(other, "work_item")[0]["story_points"] == 8.0
    none = n.issue_records(issue(1, "MD-1", points=3), {"story_points_field": None, "excluded_types": ""}, SEED, CAT, [])
    assert rows(none, "work_item")[0]["story_points"] is None


def test_dropped_status_has_no_resolved_time():
    result = make(issue(7003, "MD-9", status="DISREGARD"), [history(1, "2026-10-03T10:00:00Z", "To Do", "DISREGARD")])
    (item,) = rows(result, "work_item")
    assert item["status_category"] == "dropped" and item["resolved_at"] is None


def test_an_unmapped_current_status_is_an_error():
    with pytest.raises(ValueError, match="Weird"):
        make(issue(1, "MD-1", status="Weird"))


def test_a_malformed_timestamp_fails_the_issue():
    with pytest.raises(ValueError):
        make(issue(1, "MD-1", created="someday"))


@pytest.mark.parametrize(
    "kind, subtask, expected",
    [("Story", False, "1"), ("Epic", False, "0"), ("Initiative", False, "0"), ("Sub-task", True, "0"), ("Bug", False, "1")],
)
def test_counts_for_impact(kind, subtask, expected):
    result = make(issue(1, "MD-1", type=kind, subtask=subtask))
    assert props(result)["counts_for_impact"]["value"] == expected


def test_transition_rows_and_the_derived_properties():
    result = make(
        issue(7001, "MD-7", status="COMPLETED", parent={"id": "9", "key": "MD-1"}, status_id="42"),
        [history(5, "2026-10-02T10:00:00Z", "To Do", "In Progress", author=None),
         history(6, "2026-10-03T10:00:00Z", "In Progress", "COMPLETED"),
         history(7, "2026-10-04T10:00:00Z", "COMPLETED", "In Progress"),
         history(8, "2026-10-05T10:00:00Z", "In Progress", "COMPLETED")],
    )
    transitions = rows(result, "work_item_transition")
    assert [t["source_id"] for t in transitions] == ["7001:5:0", "7001:6:0", "7001:7:0", "7001:8:0"]
    assert transitions[0] == {
        "source": "jira", "source_id": "7001:5:0", "work_item_id": "7001", "from_status": "To Do",
        "to_status": "In Progress", "actor_account": None, "occurred_at": "2026-10-02T10:00:00Z",
    }
    found = props(result)
    assert found["reopen_count"]["value"] == "1" and found["parent_key"]["value"] == "MD-1"
    assert found["status_id"]["value"] == "42"


def test_every_field_seen_becomes_a_property_but_never_free_text():
    result = make(issue(
        7001, "MD-7", labels=["api", "ui"], points=5,
        sprint=[{"id": 7, "name": "Sprint 7", "state": "active", "boardId": 3, "goal": "ship it"}],
        extra={"customfield_99999": "plain value", "customfield_88888": None, "fixVersions": []},
    ))
    found = props(result)
    assert json.loads(found["labels"]["value"]) == ["api", "ui"]
    assert found["priority"]["value"] == "Medium"
    assert found["story_points_10004"] == {
        "record_kind": "work_item", "record_id": "7001", "name": "story_points_10004",
        "value": "5", "source_field_id": "customfield_10004",
    }
    assert json.loads(found["sprint_10006"]["value"]) == [{"id": 7, "name": "Sprint 7", "state": "active", "boardId": 3}]
    assert found["customfield_99999"]["value"] == "plain value"
    assert "customfield_88888" not in found and "fix_versions" not in found
    for skipped in ("description", "summary", "issuelinks", "parent", "created", "updated"):
        assert skipped not in found
    assert "ship it" not in json.dumps([r.values for r in result.records if r.table == "property"])


def test_identities_carry_a_label_and_never_a_person_id():
    ann = user("acc-ann", "Ann Example", "Ann@Corp.Example")
    bot = user("acc-bot", "Build Bot", kind="app", active=False)
    result = make(issue(1, "MD-1", assignee=ann, reporter=bot))
    identities = rows(result, "identity")
    assert identities == [
        {"source": "jira", "account_id": "acc-ann", "label": "Ann Example"},
        {"source": "jira", "account_id": "acc-bot", "label": "Build Bot"},
    ]
    assert all("person_id" not in row for row in identities)
    emails = [r.values for r in result.records if r.table == "property" and r.values["record_kind"] == "identity"]
    by_name = {(v["record_id"], v["name"]): v["value"] for v in emails}
    assert by_name[("jira:acc-ann", "email")] == "ann@corp.example"
    assert by_name[("jira:acc-ann", "account_type")] == "atlassian"
    assert by_name[("jira:acc-bot", "account_type")] == "app"
    assert by_name[("jira:acc-bot", "active")] == "false"
    assert ("jira:acc-bot", "email") not in by_name


def test_the_email_never_appears_in_work_item_properties():
    ann = user("acc-ann", "Ann Example", "ann@corp.example")
    result = make(issue(1, "MD-1", assignee=ann, reporter=ann))
    texts = [r.values["value"] for r in result.records if r.table == "property" and r.values["record_kind"] == "work_item"]
    assert not any("ann@corp.example" in (text or "") for text in texts)


def test_issue_links_land_once_in_the_outward_direction_and_parent_is_a_link():
    blocks_out = {"id": "501", "type": {"name": "Blocks"}, "outwardIssue": {"id": "8002", "key": "MD-8"}}
    blocks_in = {"id": "502", "type": {"name": "Blocks"}, "inwardIssue": {"id": "8003", "key": "MD-9"}}
    result = make(issue(7001, "MD-7", links=[blocks_out, blocks_in], parent={"id": "9", "key": "MD-1"}))
    links = {r["source_id"]: r for r in rows(result, "link")}
    assert links["issuelink:501"] == {
        "source": "jira", "source_id": "issuelink:501", "from_kind": "work_item", "from_id": "7001",
        "to_kind": "work_item", "to_id": "8002", "kind": "Blocks", "found_by": "jira",
    }
    assert (links["issuelink:502"]["from_id"], links["issuelink:502"]["to_id"]) == ("8003", "7001")
    assert links["parent:7001:9"]["kind"] == "parent"
    assert (links["parent:7001:9"]["from_id"], links["parent:7001:9"]["to_id"]) == ("7001", "9")


def test_the_raw_payload_is_the_issue_json():
    result = make(issue(7001, "MD-7"))
    assert (result.raw.source, result.raw.source_id, result.raw.kind) == ("jira", "7001", "issue")
    assert json.loads(result.raw.json)["key"] == "MD-7"


def test_the_raw_payload_carries_no_email_or_avatar_at_any_depth():
    ann = user("acc-ann", "Ann Example", "ann@corp.example")
    bob = user("acc-bob", "Bob Example", "bob@corp.example")
    cat = user("acc-cat", "Cat Example", "cat@corp.example")
    for person in (ann, bob, cat):
        person["avatarUrls"] = {"48x48": "https://avatar.example/" + person["accountId"]}
    deep = [{"who": {"emailAddress": "deep@corp.example"}}]
    item = issue(1, "MD-1", assignee=ann, reporter=bob, extra={"creator": cat, "customfield_20000": deep})
    result = make(item)
    assert "emailAddress" not in result.raw.json and "avatarUrls" not in result.raw.json
    assert "@corp.example" not in result.raw.json
    assert json.loads(result.raw.json)["fields"]["assignee"]["accountId"] == "acc-ann"
    assert "emailAddress" in json.dumps(item)  # the caller's issue is not mutated


def test_a_history_entry_without_created_fails_the_page():
    entry = {"id": "1", "items": [{"fieldId": "status", "fromString": "To Do", "toString": "In Progress"}]}
    with pytest.raises(ValueError):
        n.status_transitions([entry])
