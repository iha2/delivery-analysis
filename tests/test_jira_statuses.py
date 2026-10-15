from delivery_analysis.connectors.jira.statuses import SEED, seed_for
from delivery_analysis.settings import CONFIG_VARS, CREDENTIAL_VARS, credential_status


def test_the_seed_map_matches_the_agreed_buckets():
    assert SEED["COMPLETED"] == "done"
    assert SEED["DISREGARD"] == "dropped"
    assert SEED["In Progress"] == "in_progress" and SEED["Dev Done"] == "in_progress"
    assert {SEED[name] for name in ("Code Review", "Tech Review", "In Review", "Ready for QA", "In QA", "UAT",
                                    "UAT Passed", "Ready for UAT", "Ready for Release", "Deployed")} == {"in_review"}
    assert {SEED[name] for name in ("Backlog", "To Do", "Definition", "Design is Needed", "Design is Done")} == {"todo"}
    assert len(SEED) == 19


def test_seed_for_splits_known_and_unknown_names():
    mapped, unmapped = seed_for(["To Do", "Weird B", "COMPLETED", "Weird A"])
    assert mapped == {"To Do": "todo", "COMPLETED": "done"}
    assert unmapped == ["Weird A", "Weird B"]


def test_the_email_is_a_config_name_not_a_credential():
    assert CONFIG_VARS == ("ATLASSIAN_EMAIL",)
    assert "ATLASSIAN_EMAIL" not in CREDENTIAL_VARS
    assert credential_status({"ATLASSIAN_EMAIL": "me@corp.example"}, CONFIG_VARS) == {"ATLASSIAN_EMAIL": True}
