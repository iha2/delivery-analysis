from token_world import SOURCE, World


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def test_the_world_writes_canonical_rows_and_usage(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    t1 = w.ticket("MD-1", assignee=ada, points=3).in_progress("2026-03-02").completed("2026-03-06")
    pr = w.pull_request(ada, created="2026-03-03", merged="2026-03-05", links=[t1])
    w.commit(ada, "2026-03-03", pr=pr)
    w.usage(ada, "2026-03-03", 1250, accepted_edits=4)
    w.usage(ada, "2026-03-03", 250)
    item = one(conn, "SELECT status, status_category, started_at, resolved_at, story_points FROM work_item WHERE key = 'MD-1'")
    assert tuple(item) == ("COMPLETED", "done", "2026-03-02T10:00:00Z", "2026-03-06T10:00:00Z", 3.0)
    assert one(conn, "SELECT COUNT(*) FROM work_item_transition")[0] == 2
    assert one(conn, "SELECT actor_account FROM work_item_transition LIMIT 1")[0] == "acc-ada"
    assert one(conn, "SELECT to_id FROM link WHERE kind = 'implements'")[0] == t1.id
    assert one(conn, "SELECT value FROM property WHERE name = 'counts_for_impact' AND record_id = ?", t1.id)[0] == "1"
    usage = one(conn, "SELECT cost_usd, input_tokens FROM claude_usage_day WHERE source = ?", SOURCE)
    assert tuple(usage) == (15.0, 2000)
    assert one(conn, "SELECT edits_accepted FROM claude_activity_day")[0] == 4
    assert one(conn, "SELECT person_id FROM identity WHERE source = 'jira'")[0] is None


def test_subtasks_and_epics_do_not_count_for_impact_and_link_to_their_parent(conn):
    w = World(conn)
    story = w.ticket("MD-1", points=5)
    sub = w.ticket("MD-2", kind="Sub-task", parent=story)
    epic = w.ticket("MD-3", kind="Epic")
    values = dict(conn.execute("SELECT record_id, value FROM property WHERE name = 'counts_for_impact'").fetchall())
    assert values == {story.id: "1", sub.id: "0", epic.id: "0"}
    assert tuple(one(conn, "SELECT from_id, to_id FROM link WHERE kind = 'parent'")) == (sub.id, story.id)
