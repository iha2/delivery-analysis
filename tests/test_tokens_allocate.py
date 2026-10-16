import pytest

from delivery_analysis.tokens.allocate import allocate
from delivery_analysis.tokens.types import Candidate

T1, T2, T3 = ("jira", "1"), ("jira", "2"), ("jira", "3")


def shape(rows):
    return [(r.ticket, r.cost_usd, r.method, r.confidence, r.reason) for r in rows]


def test_no_candidate_is_one_unattributed_row_with_a_reason():
    assert shape(allocate(6.0, [], False)) == [(None, 6.0, "unattributed", None, "no_active_ticket")]
    assert shape(allocate(3.0, [], True)) == [(None, 3.0, "unattributed", None, "untracked_work")]


def test_zero_cost_gives_no_rows():
    assert allocate(0.0, [Candidate(T1, 1.0, True)], False) == []


def test_single_candidate_levels():
    assert shape(allocate(10.0, [Candidate(T1, 2.0, True)], False)) == [(T1, 10.0, "window_single", "high", None)]
    assert shape(allocate(10.0, [Candidate(T1, 0.0, True)], False)) == [(T1, 10.0, "window_single", "medium", None)]
    assert shape(allocate(10.0, [Candidate(T1, 0.0, False)], False)) == [(T1, 10.0, "window_single", "low", None)]


def test_evidence_weighted_split_uses_the_prior():
    rows = allocate(10.0, [Candidate(T2, 0.0, True), Candidate(T1, 2.0, True)], False)
    assert shape(rows) == [(T1, 9.0, "window_evidence", "medium", None), (T2, 1.0, "window_evidence", "medium", None)]
    assert [r.weight for r in rows] == [2.25, 0.25]
    assert [r.evidence for r in rows] == [2.0, 0.0]


def test_equal_split_when_no_candidate_has_evidence_and_the_sum_is_exact():
    rows = allocate(10.0, [Candidate(T3, 0.0, True), Candidate(T1, 0.0, True), Candidate(T2, 0.0, True)], False)
    assert [r.ticket for r in rows] == [T1, T2, T3]
    assert {r.method for r in rows} == {"window_equal"} and {r.confidence for r in rows} == {"low"}
    assert sum(r.cost_usd for r in rows) == pytest.approx(10.0, abs=1e-6)
    assert [r.cost_usd for r in rows] == [3.333334, 3.333333, 3.333333]


def test_an_assignee_only_candidate_is_low_even_in_an_evidence_split():
    rows = allocate(10.0, [Candidate(T1, 1.0, True), Candidate(T2, 0.0, False)], False)
    assert [(r.ticket, r.confidence) for r in rows] == [(T1, "medium"), (T2, "low")]


def test_negative_cost_is_one_signed_adjustment_row():
    assert shape(allocate(-2.5, [Candidate(T1, 1.0, True)], False)) == [
        (None, -2.5, "unattributed", None, "adjustment")]
