from impact_seed import issue, seed_impact
from metrics_seed import SEPT, TODAY, TZ, prop, put
from delivery_analysis.metrics import credit as cr
from delivery_analysis.metrics import delivered as dv
from delivery_analysis.metrics import impact_build as ib
from delivery_analysis.metrics import jira as mj
from delivery_analysis.metrics import tokens as tk
from delivery_analysis.metrics.people import Scope
from delivery_analysis.metrics.window import make_window

WINDOW = make_window(SEPT, TZ, TODAY)


def item(conn, sid, status, *, category="in_progress", resolved=None, source="jira", points=3):
    put(
        conn, "work_item", source=source, source_id=sid, project="MD", key=f"MD-{sid}", type="Story",
        assignee_account="acc-ann", status=status, status_category=category, resolved_at=resolved,
        story_points=points,
    )
    prop(conn, "work_item", sid, "counts_for_impact", "1")


def move(conn, sid, n, to, at):
    put(
        conn, "work_item_transition", source="jira", source_id=f"{sid}:{n}:0", work_item_id=sid,
        from_status=None, to_status=to, occurred_at=at,
    )


def delivered_at(conn, sid, source="jira"):
    return conn.execute(
        "SELECT delivered_at FROM work_item WHERE source = ? AND source_id = ?", (source, sid)
    ).fetchone()[0]


def test_the_default_statuses_and_the_env_override():
    assert dv.delivered_statuses({}) == dv.DELIVERED_STATUSES
    assert dv.delivered_statuses(None) == dv.DELIVERED_STATUSES
    assert "Dev Done" in dv.DELIVERED_STATUSES and "DISREGARD" not in dv.DELIVERED_STATUSES
    assert dv.delivered_statuses({"DELIVERED_STATUSES": " Done , Shipped,, "}) == ("Done", "Shipped")
    assert dv.delivered_statuses({"DELIVERED_STATUSES": " , "}) == dv.DELIVERED_STATUSES


def test_the_earliest_transition_into_a_delivered_status_wins(conn):
    item(conn, "1", "COMPLETED", category="done", resolved="2026-09-30T10:00:00Z")
    move(conn, "1", 1, "In Progress", "2026-09-01T10:00:00Z")
    move(conn, "1", 2, "Dev Done", "2026-09-10T10:00:00Z")
    move(conn, "1", 3, "UAT", "2026-09-20T10:00:00Z")
    move(conn, "1", 4, "COMPLETED", "2026-09-30T10:00:00Z")
    assert dv.derive_delivered(conn) == 1
    assert delivered_at(conn, "1") == "2026-09-10T10:00:00Z"


def test_a_ticket_that_went_back_to_work_is_not_delivered(conn):
    item(conn, "1", "In Progress")
    move(conn, "1", 1, "Dev Done", "2026-09-10T10:00:00Z")
    move(conn, "1", 2, "In Progress", "2026-09-11T10:00:00Z")
    assert dv.derive_delivered(conn) == 0
    assert delivered_at(conn, "1") is None


def test_a_re_delivered_ticket_keeps_its_earliest_date(conn):
    item(conn, "1", "Dev Done")
    move(conn, "1", 1, "Dev Done", "2026-09-10T10:00:00Z")
    move(conn, "1", 2, "In Progress", "2026-09-11T10:00:00Z")
    move(conn, "1", 3, "Dev Done", "2026-09-25T10:00:00Z")
    dv.derive_delivered(conn)
    assert delivered_at(conn, "1") == "2026-09-10T10:00:00Z"


def test_a_delivered_ticket_without_transitions_uses_its_resolved_date(conn):
    item(conn, "1", "COMPLETED", category="done", resolved="2026-09-12T10:00:00Z")
    dv.derive_delivered(conn)
    assert delivered_at(conn, "1") == "2026-09-12T10:00:00Z"


def test_a_dropped_ticket_is_never_delivered(conn):
    item(conn, "1", "DISREGARD", category="dropped", resolved="2026-09-12T10:00:00Z")
    move(conn, "1", 1, "Dev Done", "2026-09-10T10:00:00Z")
    move(conn, "1", 2, "DISREGARD", "2026-09-12T10:00:00Z")
    dv.derive_delivered(conn)
    assert delivered_at(conn, "1") is None


def test_other_sources_are_untouched_and_a_stale_date_is_cleared(conn):
    item(conn, "1", "Dev Done", source="other")
    conn.execute("UPDATE work_item SET delivered_at = 'keep' WHERE source = 'other'")
    item(conn, "2", "In Progress")
    conn.execute("UPDATE work_item SET delivered_at = 'stale' WHERE source_id = '2'")
    dv.derive_delivered(conn)
    assert delivered_at(conn, "1", "other") == "keep" and delivered_at(conn, "2") is None


def test_deriving_twice_gives_the_same_answer_and_the_statuses_can_be_overridden(conn):
    item(conn, "1", "Shipped")
    move(conn, "1", 1, "Shipped", "2026-09-10T10:00:00Z")
    assert dv.derive_delivered(conn) == 0
    assert dv.derive_delivered(conn, ("Shipped",)) == 1
    assert dv.derive_delivered(conn, ("Shipped",)) == 1
    assert delivered_at(conn, "1") == "2026-09-10T10:00:00Z"


def _dev_done_in_window(conn):
    """A ticket that is still open in Jira terms but reached Dev Done on 09-10; one done in August."""
    item(conn, "1", "Dev Done", resolved=None)
    move(conn, "1", 1, "Dev Done", "2026-09-10T10:00:00Z")
    item(conn, "2", "COMPLETED", category="done", resolved="2026-10-01T10:00:00Z")  # resolved after the window
    move(conn, "2", 1, "Dev Done", "2026-09-12T10:00:00Z")
    move(conn, "2", 2, "COMPLETED", "2026-10-01T10:00:00Z")
    dv.derive_delivered(conn)


def test_credit_counts_a_ticket_in_the_window_of_its_first_dev_done(conn):
    seed_impact(conn)
    _dev_done_in_window(conn)
    issues = {row["source_id"]: row["resolved_at"] for row in cr.completed_issues(conn, WINDOW)}
    assert issues["1"] == "2026-09-10T10:00:00Z" and issues["2"] == "2026-09-12T10:00:00Z"


def test_jira_metrics_count_the_delivered_date(conn):
    seed_impact(conn)
    _dev_done_in_window(conn)
    rows, _ = mj._done(conn, Scope(), WINDOW)
    by_id = {row["source_id"]: row["resolved_at"] for row in rows}
    assert by_id["1"] == "2026-09-10T10:00:00Z" and by_id["2"] == "2026-09-12T10:00:00Z"


def test_the_unresolved_count_skips_a_done_ticket_with_a_delivered_date(conn):
    item(conn, "1", "COMPLETED", category="done", resolved=None)
    move(conn, "1", 1, "Dev Done", "2026-09-10T10:00:00Z")
    assert mj._unresolved(conn, Scope()) == 1
    dv.derive_delivered(conn)
    assert mj._unresolved(conn, Scope()) == 0


def test_the_impact_cohort_uses_the_delivered_date(conn):
    _dev_done_in_window(conn)
    cohort = {row["source_id"]: row["resolved_at"] for row in conn.execute(ib._COHORT_SQL)}
    assert cohort == {"1": "2026-09-10T10:00:00Z", "2": "2026-09-12T10:00:00Z"}


def test_the_token_cohort_uses_the_delivered_date(conn):
    _dev_done_in_window(conn)
    tickets = tk.load_cohort(conn, WINDOW).tickets
    assert tickets[("jira", "1")]["resolved_at"] == "2026-09-10T10:00:00Z"
    assert tickets[("jira", "2")]["resolved_at"] == "2026-09-12T10:00:00Z"


def test_a_database_that_never_derived_behaves_as_before(conn):
    issue(conn, "1", "acc-ann", resolved="2026-09-10T10:00:00Z", points=3)
    issue(conn, "2", "acc-ann", category="in_progress", resolved="2026-09-11T10:00:00Z", points=3)
    assert [row["source_id"] for row in cr.completed_issues(conn, WINDOW)] == ["1"]
    assert [row["source_id"] for row in conn.execute(ib._COHORT_SQL)] == ["1"]
    assert [row["source_id"] for row in mj._done(conn, Scope(), WINDOW)[0]] == ["1"]
    assert list(tk.load_cohort(conn, WINDOW).tickets) == [("jira", "1")]


def test_a_custom_delivered_set_still_counts_done_category_items(conn):
    item(conn, "1", "COMPLETED", category="done", resolved="2026-09-12T10:00:00Z")
    item(conn, "2", "Closed", category="done", resolved="2026-09-13T10:00:00Z")  # user-mapped to done
    item(conn, "3", "Dev Done")
    move(conn, "3", 1, "Dev Done", "2026-09-10T10:00:00Z")
    item(conn, "4", "In Progress")
    move(conn, "4", 1, "Dev Done", "2026-09-10T10:00:00Z")
    move(conn, "4", 2, "In Progress", "2026-09-11T10:00:00Z")
    item(conn, "5", "DISREGARD", category="dropped", resolved="2026-09-12T10:00:00Z")
    assert dv.derive_delivered(conn, ("Dev Done",)) == 3
    assert delivered_at(conn, "1") == "2026-09-12T10:00:00Z"
    assert delivered_at(conn, "2") == "2026-09-13T10:00:00Z"
    assert delivered_at(conn, "3") == "2026-09-10T10:00:00Z"
    assert delivered_at(conn, "4") is None and delivered_at(conn, "5") is None
    # the fallback must not resurrect anything derive left NULL
    assert not {"4", "5"} & {r["source_id"] for r in conn.execute(ib._COHORT_SQL)}


def test_a_done_item_uses_its_earliest_delivered_transition_even_with_a_custom_set(conn):
    item(conn, "1", "COMPLETED", category="done", resolved="2026-09-30T10:00:00Z")
    move(conn, "1", 1, "Dev Done", "2026-09-10T10:00:00Z")
    dv.derive_delivered(conn, ("Dev Done",))
    assert delivered_at(conn, "1") == "2026-09-10T10:00:00Z"
