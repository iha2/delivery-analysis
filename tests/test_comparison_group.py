import pytest

from metrics_seed import seed
from delivery_analysis.store import comparison


@pytest.fixture
def seeded(conn):
    seed(conn)
    return conn


def test_a_team_with_no_choice_has_no_group(seeded):
    assert comparison.get_group(seeded, "t1") is None


def test_set_group_keeps_only_the_chosen_people_and_reset_clears_it(seeded):
    comparison.set_group(seeded, "t1", ["p-bob"])
    assert comparison.get_group(seeded, "t1") == ["p-bob"]
    comparison.set_group(seeded, "t1", ["p-ann", "p-bob"])
    assert comparison.get_group(seeded, "t1") == ["p-ann", "p-bob"]
    comparison.reset_group(seeded, "t1")
    assert comparison.get_group(seeded, "t1") is None


@pytest.mark.parametrize("people", [[], ["p-cy"], ["p-dee"], ["nobody"], ["p-ann", "nobody"]])
def test_only_active_team_members_can_be_chosen(seeded, people):
    with pytest.raises(ValueError):
        comparison.set_group(seeded, "t1", people)
    assert comparison.get_group(seeded, "t1") is None


def test_an_unknown_team_is_a_lookup_error(seeded):
    with pytest.raises(LookupError):
        comparison.set_group(seeded, "nope", ["p-ann"])
    with pytest.raises(LookupError):
        comparison.get_group(seeded, "nope")


def test_people_who_leave_the_team_drop_out_of_the_group(seeded):
    comparison.set_group(seeded, "t1", ["p-ann", "p-bob"])
    seeded.execute("UPDATE team_member SET status = 'inactive' WHERE person_id = 'p-bob'")
    assert comparison.get_group(seeded, "t1") == ["p-ann"]
    seeded.execute("UPDATE team_member SET status = 'excluded' WHERE person_id = 'p-ann'")
    assert comparison.get_group(seeded, "t1") is None  # nobody left: fall back to the whole team


def test_options_lists_active_members_with_their_selection(seeded):
    assert comparison.options(seeded, "t1") == {
        "team_id": "t1", "custom": False,
        "people": [{"person_id": "p-ann", "name": "Ann Example", "selected": True},
                   {"person_id": "p-bob", "name": "Bob Builder", "selected": True}],
    }
    comparison.set_group(seeded, "t1", ["p-bob"])
    out = comparison.options(seeded, "t1")
    assert out["custom"] is True
    assert [(p["person_id"], p["selected"]) for p in out["people"]] == [("p-ann", False), ("p-bob", True)]
