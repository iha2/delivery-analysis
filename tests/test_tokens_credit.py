from delivery_analysis.tokens.credit import Credit, compute_credit

T1, T2, T3 = ("jira", "1"), ("jira", "2"), ("jira", "3")


def test_evidence_shares_then_assignee_then_none():
    credits, uncredited = compute_credit(
        {(T1, "p-ada"): 3.0, (T1, "p-bo"): 1.0, (T2, "p-bo"): 0.0},
        {T1: "p-cy", T2: "p-ada", T3: None},
    )
    assert credits == [
        Credit(T1, "p-ada", 0.75, 3.0, "evidence_share"),
        Credit(T1, "p-bo", 0.25, 1.0, "evidence_share"),
        Credit(T2, "p-ada", 1.0, 0.0, "assignee"),
    ]
    assert uncredited == 1


def test_a_ticket_with_evidence_but_no_assignee_entry_is_still_credited():
    credits, uncredited = compute_credit({(T1, "p-ada"): 2.0}, {})
    assert credits == [Credit(T1, "p-ada", 1.0, 2.0, "evidence_share")] and uncredited == 0
