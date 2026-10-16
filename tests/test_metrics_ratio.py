from metrics_seed import SEPT, TODAY, TZ, seed
from delivery_analysis.metrics import registry as r
from delivery_analysis.metrics.people import People, team_scope, unmapped_accounts
from delivery_analysis.metrics.window import make_window

SEPT_WINDOW = make_window(SEPT, TZ, TODAY)
AUG_START = "2026-08-02T04:00:00Z"


def pairs(data, confidence=None, unranked=None):
    def compute(conn, scope, window):
        obs = r.Observations(notes=["a note"])
        for key, items in data.get(window.start, {}).items():
            for item in items:
                obs.add_pair(key, *item)
        obs.confidence.update(confidence or {})
        obs.unranked.update(unranked or {})
        return obs
    return compute


def metric(compute, **kwargs):
    options = dict(aggregate="ratio", min_sample=3, min_denominator=20.0, sample_noun="completed tickets")
    options.update(kwargs)
    return r.Metric("m", "M", "points_per_usd", r.PER_PERSON, ("bitbucket",), compute=compute, **options)


def test_ratio_of_sums_minimums_trend_and_confidence(conn):
    seed(conn)
    data = {
        SEPT_WINDOW.start: {"person:p-ann": [(3, 10), (2, 10), (5, 10)], "person:p-bob": [(8, 50)],
                            "person:nobody": [(1, 1)]},
        AUG_START: {"person:p-ann": [(1, 10), (1, 10), (1, 10)]},
    }
    result = r.run_metric(conn, metric(pairs(data, confidence={"person:p-ann": "medium"})),
                          team_scope(conn, "t1"), SEPT_WINDOW)
    ann, bob = result["rows"]
    assert (ann["name"], ann["value"], ann["numerator"], ann["denominator"], ann["sample"], ann["ranked"],
            ann["rank"], ann["confidence"], ann["previous"]) == ("Ann Example", 0.3333, 10.0, 30.0, 3, True, 1,
                                                                  "medium", 0.1)
    assert ann["trend"] == round((10 / 30 - 0.1) / 0.1, 4)
    assert (bob["name"], bob["value"], bob["ranked"], bob["unranked_reason"], bob["previous"]) == (
        "Bob Builder", 0.16, False, "fewer than 3 completed tickets", None)
    assert result["team"] == {"value": 0.225, "sample": 4, "numerator": 18.0, "denominator": 80.0,
                              "previous": 0.1, "trend": 1.25}


def test_the_cost_floor_and_thin_history(conn):
    seed(conn)
    data = {SEPT_WINDOW.start: {"person:p-ann": [(3, 5), (2, 5), (5, 5)]}, AUG_START: {"person:p-ann": [(1, 10)]}}
    result = r.run_metric(conn, metric(pairs(data)), team_scope(conn, "t1"), SEPT_WINDOW)
    ann = result["rows"][0]
    assert ann["ranked"] is False and ann["unranked_reason"] == "under $20 of attributed Claude cost"
    assert ann["previous"] is None and any("insufficient history" in note for note in result["notes"])


def test_zero_denominator_is_none_with_a_reason(conn):
    seed(conn)
    data = {SEPT_WINDOW.start: {"person:p-ann": [(1, 0), (1, 0), (1, 0)]}}
    ann = r.run_metric(conn, metric(pairs(data), min_denominator=0.0), team_scope(conn, "t1"), SEPT_WINDOW)["rows"][0]
    assert ann["value"] is None and ann["ranked"] is False and ann["unranked_reason"] == "no cost to divide by"


def test_a_reason_from_the_metric_wins(conn):
    seed(conn)
    data = {SEPT_WINDOW.start: {"person:p-ann": [(3, 10), (2, 10), (5, 10)]}}
    reason = "over 50% of Claude cost unattributed"
    ann = r.run_metric(conn, metric(pairs(data, unranked={"person:p-ann": reason})), team_scope(conn, "t1"),
                       SEPT_WINDOW)["rows"][0]
    assert ann["ranked"] is False and ann["unranked_reason"] == reason


def test_non_ratio_rows_carry_empty_confidence(conn):
    seed(conn)

    def compute(conn, scope, window):
        obs = r.Observations()
        obs.add("bitbucket:acc-ann", 1)
        return obs

    rows = r.run_metric(conn, r.Metric("c", "C", "count", r.PER_PERSON, ("bitbucket",), compute=compute),
                        team_scope(conn, "t1"), SEPT_WINDOW)["rows"]
    assert all(row["confidence"] is None and row["unranked_reason"] is None for row in rows)


def test_person_keys_and_unmapped_claude_actors(conn):
    seed(conn)
    people = People(conn)
    assert people.resolve("person:p-ann") == "p-ann" and people.resolve("person:nobody") is None
    assert people.resolve("email:none@corp.example|person:p-bob") == "p-bob"
    conn.execute(
        "INSERT INTO claude_usage_day (source, day, actor_type, actor, model, cost_usd, fetched_at) "
        "VALUES ('claude_code_analytics', '2026-09-03', 'email', 'ghost@corp.example', 'm', 1.0, 'now')"
    )
    found = {(row["source"], row["account"]) for row in unmapped_accounts(conn)}
    assert ("email", "ghost@corp.example") in found
