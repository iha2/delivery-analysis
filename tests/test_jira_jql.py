from zoneinfo import ZoneInfo

import pytest

from delivery_analysis.connectors.jira import jql

LA = ZoneInfo("America/Los_Angeles")


def test_a_utc_instant_becomes_a_local_minute_floored_date():
    assert jql.jql_date("2026-10-15T20:07:45Z", LA) == "2026/10/15 13:07"
    assert jql.jql_date("2026-11-02T20:07:45Z", LA) == "2026/11/02 12:07"


def test_the_repeated_fall_back_hour_still_gives_a_real_local_time():
    # 2026-11-01: PDT ends at 09:00Z. Both instants exist; the 7-day overlap absorbs the repeat.
    assert jql.jql_date("2026-11-01T08:30:00Z", LA) == "2026/11/01 01:30"
    assert jql.jql_date("2026-11-01T09:30:00Z", LA) == "2026/11/01 01:30"


def test_the_spring_forward_gap_is_never_produced():
    assert jql.jql_date("2026-03-08T09:59:00Z", LA) == "2026/03/08 01:59"
    assert jql.jql_date("2026-03-08T10:00:00Z", LA) == "2026/03/08 03:00"


def test_project_jql_is_bounded_and_ordered():
    assert jql.project_jql("MD", "2026-10-08T14:05:30Z", LA) == (
        'project = "MD" AND updated >= "2026/10/08 07:05" ORDER BY updated ASC, key ASC'
    )


@pytest.mark.parametrize("key", ['M"D', "MD OR 1=1", "", "1MD", "M-D"])
def test_a_project_key_that_could_alter_the_query_is_refused(key):
    with pytest.raises(ValueError, match="project key"):
        jql.project_jql(key, "2026-10-08T14:05:30Z", LA)
