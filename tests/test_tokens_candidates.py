from datetime import date

from delivery_analysis.tokens.candidates import active_intervals, candidates_for_day
from delivery_analysis.tokens.types import Candidate

T1, T2, T3, T4, T5 = (("jira", str(n)) for n in range(1, 6))
TODAY = date(2026, 3, 20)


def d(day):
    return date(2026, 3, day)


def at(day):
    return f"2026-03-{day:02d}T10:00:00Z"


def test_a_bounce_back_to_in_progress_opens_a_second_span():
    spans = active_intervals(
        [(at(2), "in_progress"), (at(4), "in_review"), (at(6), "in_progress"), (at(8), "done")], []
    )
    assert spans == [(d(2), d(4)), (d(6), d(8))]


def test_a_merge_cuts_the_span_and_dev_done_does_not_reopen_it():
    spans = active_intervals(
        [(at(2), "in_progress"), (at(6), "in_progress"), (at(9), "done")], ["2026-03-04T15:00:00Z"]
    )
    assert spans == [(d(2), d(4))]


def test_open_spans_unmapped_statuses_and_early_merges():
    assert active_intervals([(at(2), "in_progress")], []) == [(d(2), None)]
    assert active_intervals([(at(2), "in_progress"), (at(3), None)], []) == [(d(2), d(3))]
    assert active_intervals([(at(2), "in_progress")], ["2026-03-01T15:00:00Z"]) == [(d(2), None)]


def test_candidates_by_evidence_by_window_and_not_after_a_span_ends():
    found = candidates_for_day(
        d(10), TODAY, assigned={T1, T2},
        evidence={T1: {d(9): 1.0}, T3: {d(10): 2.0}},
        intervals={T1: [(d(2), None)], T2: [(d(1), d(5))]},
        eligible={T1, T2, T3},
    )
    assert found == [Candidate(T1, 0.0, True), Candidate(T3, 2.0, True)]


def test_the_idle_cutoff_and_its_reset_by_the_span_start():
    kwargs = dict(assigned={T1}, evidence={T1: {d(1): 1.0}}, intervals={T1: [(d(2), None)]}, eligible={T1})
    assert candidates_for_day(d(9), TODAY, **kwargs) == [Candidate(T1, 0.0, True)]  # 7 days after the span start
    assert candidates_for_day(d(12), TODAY, **kwargs) == []  # 10 days idle


def test_ineligible_tickets_and_assignee_only_candidates():
    found = candidates_for_day(
        d(10), TODAY, assigned={T5}, evidence={T4: {d(10): 1.0}},
        intervals={T5: [(d(8), None)]}, eligible={T5},
    )
    assert found == [Candidate(T5, 0.0, False)]
