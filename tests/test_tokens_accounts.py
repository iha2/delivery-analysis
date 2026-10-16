from datetime import date

from delivery_analysis.tokens.accounts import AccountMap
from delivery_analysis.tokens.config import ALGO_VERSION, DEFAULT_CONFIG
from delivery_analysis.tokens.types import day_of


def _person(conn, person_id, name, excluded=0):
    conn.execute(
        "INSERT INTO person (person_id, display_name, excluded, manual) VALUES (?, ?, ?, 0)",
        (person_id, name, excluded),
    )


def _identity(conn, source, account, person_id):
    conn.execute(
        "INSERT INTO identity (source, account_id, person_id, manual) VALUES (?, ?, ?, 0)",
        (source, account, person_id),
    )


def test_people_resolve_by_source_with_the_shared_jira_id_fallback(conn):
    _person(conn, "p-ada", "Ada Example")
    _person(conn, "p-bot", "Build Bot", excluded=1)
    _identity(conn, "bitbucket", "acc-ada", "p-ada")
    _identity(conn, "email", "ada@corp.example", "p-ada")
    _identity(conn, "jira", "acc-ada", None)  # the Jira connector never sets person_id
    _identity(conn, "claude_api_key", "ada-laptop", "p-ada")
    _identity(conn, "email", "bot@corp.example", "p-bot")
    accounts = AccountMap(conn)
    assert accounts.person("jira", "acc-ada") == "p-ada"
    assert accounts.person("claude_api_key", "ada-laptop") == "p-ada"
    assert accounts.person("email", "ghost@corp.example") is None
    assert accounts.person("bitbucket", "") is None
    assert accounts.commit_author("", " Ada@Corp.Example ") == "p-ada"
    assert accounts.commit_author("acc-ada", None) == "p-ada"
    assert accounts.person("email", "bot@corp.example") is None
    assert accounts.is_excluded("email", "bot@corp.example") is True
    assert accounts.is_excluded("email", "ghost@corp.example") is False


def test_day_of_and_config_defaults():
    assert day_of("2026-03-03T23:59:59Z") == date(2026, 3, 3)
    assert day_of("2026-03-03") == date(2026, 3, 3)
    assert day_of(None) is None
    assert ALGO_VERSION == "a-plus-1"
    values = DEFAULT_CONFIG.as_json()
    assert values["prior"] == 0.25 and values["idle_days"] == 7 and values["cost_floor_usd"] == 20.0
    assert values["pr_event_types"] == ["comment", "approved", "update"]
