import pytest

from metrics_seed import SEPT, TODAY, TZ, seed
from delivery_analysis.metrics.people import team_scope
from delivery_analysis.metrics.person import person_detail
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)


def test_person_detail_lists_work_reviews_pending_and_weekly_commits(conn):
    seed(conn)
    ann = person_detail(conn, "p-ann", WINDOW, team_scope(conn, "t1"))
    assert ann["person"] == {"person_id": "p-ann", "name": "Ann Example", "excluded": False,
                             "accounts": ["acc-ann"], "emails": ["ann@corp.example"]}
    assert [pr["number"] for pr in ann["pull_requests"]] == ["3", "2", "1"]
    assert ann["pull_requests"][0]["repository"] == "core-repo"
    assert [(r["number"], r["created_at"]) for r in ann["reviews_pending"]] == [("4", "2026-09-25T14:00:00Z")]
    assert ann["commits_weekly"][0] == {"week": "2026-08-31", "value": 2}
    bob = person_detail(conn, "p-bob", WINDOW, team_scope(conn, "t1"))
    assert sorted(r["type"] for r in bob["reviews_given"]) == ["approved", "comment"]


def test_person_detail_without_a_team_includes_other_repositories(conn):
    seed(conn)
    numbers = [pr["number"] for pr in person_detail(conn, "p-ann", WINDOW)["pull_requests"]]
    assert "6" in numbers


def test_an_unknown_person_is_a_lookup_error(conn):
    with pytest.raises(LookupError):
        person_detail(conn, "nobody", WINDOW)
