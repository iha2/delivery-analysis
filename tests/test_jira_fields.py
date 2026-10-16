import json

import pytest

from delivery_analysis.connectors.jira import fields as f
from jira_fakes import DEFAULT_FIELDS


@pytest.fixture
def catalogue():
    return f.FieldCatalogue(DEFAULT_FIELDS)


def test_system_fields_use_snake_case_keys(catalogue):
    assert catalogue.property_name("labels") == "labels"
    assert catalogue.property_name("fixVersions") == "fix_versions"
    assert catalogue.property_name("priority") == "priority"
    assert catalogue.is_custom("labels") is False


def test_custom_fields_are_slug_plus_id_so_same_names_never_collide(catalogue):
    assert catalogue.property_name("customfield_10004") == "story_points_10004"
    assert catalogue.property_name("customfield_11168") == "story_point_estimate_11168"
    assert catalogue.property_name("customfield_11104") == "story_point_estimate_11104"
    assert catalogue.property_name("customfield_10006") == "sprint_10006"
    assert catalogue.property_name("customfield_99999") == "customfield_99999"
    assert catalogue.is_custom("customfield_10004") is True


def test_points_candidates_are_custom_number_fields_named_story_points(catalogue):
    assert catalogue.points_candidates() == ["customfield_10004", "customfield_11104", "customfield_11168"]


def test_flatten_scalars_objects_and_users():
    assert f.flatten_value("text") == "text"
    assert f.flatten_value(5.0) == "5"
    assert f.flatten_value(2.5) == "2.5"
    assert f.flatten_value(True) == "true"
    assert f.flatten_value({"name": "Medium", "id": "3"}) == "Medium"
    assert f.flatten_value({"value": "Yes"}) == "Yes"
    assert f.flatten_value({"accountId": "acc-ann", "displayName": "Ann Example", "emailAddress": "ann@corp.example"}) == "acc-ann"


@pytest.mark.parametrize("empty", [None, "", [], {}])
def test_empty_values_are_not_stored(empty):
    assert f.flatten_value(empty) is None


def test_rich_text_documents_are_skipped():
    assert f.flatten_value({"type": "doc", "version": 1, "content": [{"type": "paragraph"}]}) is None


def test_lists_are_json_with_only_plain_item_keys():
    assert json.loads(f.flatten_value(["a", "b"])) == ["a", "b"]
    sprints = [
        {"id": 7, "name": "Sprint 7", "state": "closed", "boardId": 3, "goal": "free text goal",
         "startDate": "2026-09-01T00:00:00.000Z", "endDate": "2026-09-14T00:00:00.000Z", "self": "https://x"},
    ]
    assert json.loads(f.flatten_value(sprints)) == [
        {"id": 7, "name": "Sprint 7", "state": "closed", "boardId": 3,
         "startDate": "2026-09-01T00:00:00Z", "endDate": "2026-09-14T00:00:00Z"}
    ]
    versions = [{"id": "9", "name": "1.2", "released": True, "releaseDate": "2026-10-01"}]
    assert json.loads(f.flatten_value(versions)) == [{"id": "9", "name": "1.2", "released": True, "releaseDate": "2026-10-01"}]
    assert json.loads(f.flatten_value([{"accountId": "acc-ann"}])) == ["acc-ann"]


def test_date_time_strings_normalize_to_utc():
    assert f.flatten_value("2026-10-01T09:00:00.832-0700") == "2026-10-01T16:00:00Z"
    assert f.flatten_value("not a date") == "not a date"


def test_points_value_is_a_number_or_none_never_zero_for_empty():
    assert f.points_value(5) == 5.0
    assert f.points_value(0.5) == 0.5
    assert f.points_value(0) == 0.0
    assert f.points_value(None) is None
    assert f.points_value("") is None
    assert f.points_value(True) is None
    assert f.points_value("5") is None


def test_detect_picks_the_clear_winner():
    assert f.detect_points_field({"customfield_10004": 71, "customfield_11168": 1, "customfield_11104": 0}) == (
        "customfield_10004", ""
    )


def test_detect_refuses_none_and_near_ties():
    chosen, why = f.detect_points_field({"customfield_10004": 0, "customfield_11168": 0})
    assert chosen is None and "--points-field" in why
    chosen, why = f.detect_points_field({"customfield_10004": 10, "customfield_11168": 9})
    assert chosen is None and "customfield_10004" in why and "customfield_11168" in why
    assert f.detect_points_field({}) [0] is None


def test_search_fields_exclude_the_rich_text_fields():
    assert f.SEARCH_FIELDS == ["*all", "-description", "-comment", "-worklog", "-attachment"]
    assert {"description", "comment", "worklog", "attachment"} <= f.EXCLUDED_FIELDS
    assert {"summary", "issuelinks", "parent"} <= f.SKIP_PROPERTY
