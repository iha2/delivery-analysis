from delivery_analysis.connectors.registry import build_connectors
from delivery_analysis.settings import Settings


def test_jira_is_built_only_when_atlassian_is_set(tmp_path):
    settings = Settings(db_path=tmp_path / "d.sqlite")
    assert [c.name for c in build_connectors(settings, {})] == []
    built = build_connectors(settings, {"ATLASSIAN": "tok-a", "ATLASSIAN_EMAIL": "me@corp.example", "BITBUCKET": "tok-b"})
    assert sorted(c.name for c in built) == ["bitbucket", "jira"]


def test_the_email_can_ride_inside_the_token_and_the_site_can_be_overridden(tmp_path):
    settings = Settings(db_path=tmp_path / "d.sqlite")
    (jira,) = build_connectors(
        settings, {"ATLASSIAN": "me@corp.example:tok-a", "JIRA_BASE_URL": "https://api.atlassian.com/ex/jira/abc"}
    )
    assert jira.name == "jira"
    assert jira._client.email == "me@corp.example"
    assert jira._client._base == "https://api.atlassian.com/ex/jira/abc/rest/api/3"
