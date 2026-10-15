from datetime import datetime, timezone

from delivery_analysis.core import activity as act

UTC = timezone.utc
START = datetime(2026, 5, 1, 4, tzinfo=UTC)
END = datetime(2026, 6, 1, 4, tzinfo=UTC)


def dt(month, day, hour=12):
    return datetime(2026, month, day, hour, tzinfo=UTC)


def test_open_at_month_end_is_half_open():
    assert act.is_open_at_month_end(dt(5, 2), None, None, end_exclusive_utc=END)
    assert not act.is_open_at_month_end(END, None, None, end_exclusive_utc=END)
    assert not act.is_open_at_month_end(None, None, None, end_exclusive_utc=END)
    assert not act.is_open_at_month_end(dt(5, 2), dt(5, 3), dt(5, 3), end_exclusive_utc=END)
    assert not act.is_open_at_month_end(dt(5, 2), None, dt(5, 3), end_exclusive_utc=END)
    assert act.is_open_at_month_end(dt(5, 2), END, None, end_exclusive_utc=END)


def test_closed_unmerged_needs_open_in_window_and_close_before_end():
    kwargs = dict(start_inclusive_utc=START, end_exclusive_utc=END)
    assert act.is_closed_unmerged_in_window(dt(5, 5), None, dt(5, 6), **kwargs)
    assert act.is_closed_unmerged_in_window(START, None, dt(5, 6), **kwargs)
    assert not act.is_closed_unmerged_in_window(END, None, None, **kwargs)
    assert not act.is_closed_unmerged_in_window(dt(4, 20), None, dt(5, 6), **kwargs)
    assert not act.is_closed_unmerged_in_window(dt(5, 5), dt(5, 6), dt(5, 6), **kwargs)
    assert not act.is_closed_unmerged_in_window(dt(5, 5), None, END, **kwargs)
    assert not act.is_closed_unmerged_in_window(dt(5, 5), None, None, **kwargs)


STATES = {
    1: {"author": "ann", "pr_created": dt(5, 2), "merged": dt(5, 3), "closed_at": dt(5, 3)},
    2: {"author": "ann", "pr_created": dt(4, 20), "merged": dt(5, 10), "closed_at": dt(5, 10)},
    3: {"author": "bob", "pr_created": dt(5, 5), "merged": None, "closed_at": dt(5, 6)},
    4: {"author": "bob", "pr_created": dt(5, 7), "merged": None, "closed_at": None},
    5: {"author": "", "pr_created": dt(5, 8), "merged": None, "closed_at": None},
    6: {"author": "cy", "pr_created": END, "merged": None, "closed_at": None},
}


def test_counts_authored_in_window():
    result = act.counts_authored_in_window(STATES, start_utc=START, end_exclusive_utc=END)
    assert result == {"ann": 1, "bob": 2, "(unknown)": 1}


def test_counts_merged_in_window_includes_prs_opened_earlier():
    result = act.counts_merged_in_window(STATES, start_utc=START, end_exclusive_utc=END)
    assert result == {"ann": 2}


def test_counts_closed_unmerged_in_window():
    result = act.counts_closed_unmerged_in_window(
        STATES, start_inclusive_utc=START, end_exclusive_utc=END
    )
    assert result == {"bob": 1}


def test_counts_open_at_month_end():
    result = act.counts_open_at_month_end(STATES, end_exclusive_utc=END)
    assert result == {"bob": 1, "(unknown)": 1}
