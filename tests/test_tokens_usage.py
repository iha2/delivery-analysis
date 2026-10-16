import pytest

from token_world import World
from delivery_analysis.tokens.accounts import AccountMap
from delivery_analysis.tokens.usage import derive_usage, generate_share, write_usage


def test_generate_share_saturates():
    assert generate_share(0, 10.0) == 0.0
    assert generate_share(10, 10.0) == 0.5
    assert generate_share(None, 10.0) == 0.0


def test_actors_resolve_split_by_purpose_and_unmapped_cost_is_kept(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    w.person("Bo Bot", excluded=True)
    cy = w.person("Cy Example")
    w.map_api_key(ada, "ada-laptop")
    w.usage(ada, "2026-03-03", 1000, accepted_edits=10)
    w.usage("ada-laptop", "2026-03-03", 500)
    w.usage("bo@corp.example", "2026-03-03", 700)
    w.usage("ghost@corp.example", "2026-03-03", 300)
    w.usage(cy, "2026-03-04", 200)
    result = derive_usage(conn, AccountMap(conn))
    rows = [(r.person_id, r.day, r.purpose, r.cost_usd, r.total_tokens, r.purpose_method) for r in result.rows]
    assert rows == [
        ("p-ada", "2026-03-03", "ask", 7.5, 1000, "v1_actions"),
        ("p-ada", "2026-03-03", "generate", 7.5, 1000, "v1_actions"),
        ("p-cy", "2026-03-04", "unclassified", 2.0, 1000, "none"),
    ]
    assert result.unmapped == {("email", "ghost@corp.example"): 3.0}
    assert sum(r.cost_usd for r in result.rows) == pytest.approx(17.0)


def test_write_usage_stores_the_rows(conn):
    w = World(conn)
    ada = w.person("Ada Example")
    w.usage(ada, "2026-03-03", 1000)
    write_usage(conn, derive_usage(conn, AccountMap(conn)).rows)
    row = conn.execute("SELECT person_id, purpose, cost_usd, source, purpose_confidence FROM token_usage").fetchone()
    assert tuple(row) == ("p-ada", "unclassified", 10.0, "claude_code_analytics", "low")
