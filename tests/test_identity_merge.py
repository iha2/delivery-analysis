from delivery_analysis.identity.merge import EmailActivity, merge_identities


def act(email, names, commits=1, last="2026-09-01T00:00:00Z", accounts=()):
    return EmailActivity(
        email=email, names=dict(names), account_ids=tuple(accounts), commits=commits, last_commit=last
    )


def test_one_person_with_two_domains_is_merged():
    people, dupes = merge_identities(
        [
            act("pat.lee@alpha.example", {"Pat Lee": 3}, 3, "2026-09-02T00:00:00Z"),
            act("pat.lee@beta.example", {"Pat Lee": 2}, 2, "2026-09-05T00:00:00Z"),
        ]
    )
    assert len(people) == 1 and dupes == []
    person = people[0]
    assert person.emails == ("pat.lee@alpha.example", "pat.lee@beta.example")
    assert (person.commits, person.last_commit) == (5, "2026-09-05T00:00:00Z")
    assert person.key == "pat.lee@alpha.example"


def test_machine_name_email_joins_the_full_name():
    people, _ = merge_identities(
        [act("akhan@host-641", {"akhan": 4}), act("akhan@corp.example", {"Abdul Rauf Khan": 7})]
    )
    assert [(p.display_name, p.emails) for p in people] == [
        ("Abdul Rauf Khan", ("akhan@corp.example", "akhan@host-641"))
    ]


def test_two_different_people_sharing_a_first_name_are_not_merged():
    people, dupes = merge_identities(
        [act("john@a.example", {"John Smith": 3}), act("john@b.example", {"John Doe": 3})]
    )
    assert len(people) == 2
    assert [(d.email_a, d.email_b) for d in dupes] == [("john@a.example", "john@b.example")]
    assert "john" in dupes[0].reason


def test_display_name_prefers_the_most_common_spelling_with_a_space():
    people, _ = merge_identities([act("a@x.example", {"Alex Poe": 381, "Alexander Poe": 323, "apoe": 900})])
    assert people[0].display_name == "Alex Poe"
    people, _ = merge_identities([act("j@x.example", {"JRoe": 196, "Jane Roe": 194})])
    assert people[0].display_name == "Jane Roe"


def test_display_name_falls_back_to_the_email_when_no_name_was_recorded():
    people, _ = merge_identities([act("sam@x.example", {})])
    assert people[0].display_name == "sam"


def test_bots_and_service_accounts_are_flagged():
    people, _ = merge_identities(
        [
            act("build-bot@corp.example", {"Build Bot": 9}),
            act("noreply@corp.example", {"GitHub": 2}),
            act("jenkins@corp.example", {"Jenkins": 5}),
            act("dana@corp.example", {"Dana Example": 4}),
        ]
    )
    flags = {p.emails[0]: p.is_bot for p in people}
    assert flags == {
        "build-bot@corp.example": True,
        "noreply@corp.example": True,
        "jenkins@corp.example": True,
        "dana@corp.example": False,
    }


def test_a_shared_account_id_joins_different_emails():
    account = ("bitbucket", "{abc-123}")
    people, _ = merge_identities(
        [
            act("x.one@a.example", {"Xavier One": 2}, accounts=[account]),
            act("y.two@b.example", {"X. One": 1}, accounts=[account]),
        ]
    )
    assert len(people) == 1
    assert people[0].account_ids == (account,)


def test_result_does_not_depend_on_input_order():
    items = [
        act("pat.lee@alpha.example", {"Pat Lee": 3}),
        act("pat.lee@beta.example", {"Pat Lee": 2}),
        act("john@a.example", {"John Smith": 3}),
        act("john@b.example", {"John Doe": 3}),
        act("zed@x.example", {"Zed Q": 1}),
    ]
    assert merge_identities(items) == merge_identities(list(reversed(items)))
