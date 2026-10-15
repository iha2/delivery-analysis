"""A small made-up Bitbucket dataset for metric and API tests.

Team "Core" (t1) covers REPO. Ann and Bob are active, Cy is inactive, Dee is an excluded bot,
and acc-zed is a reviewer nobody has mapped to a person. The test window is September 2026 in
New York time.
"""
import itertools
from datetime import date
from zoneinfo import ZoneInfo

from delivery_analysis.model.records import Record
from delivery_analysis.store.upsert import upsert_record

NOW = "2026-10-15T12:00:00Z"
REPO = "{11111111-1111-1111-1111-111111111111}"
OTHER = "{22222222-2222-2222-2222-222222222222}"
TZ = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 15)
SEPT = "month:2026-09"

_events = itertools.count(1)


def put(conn, table, **values):
    upsert_record(conn, Record(table, values), NOW)


def prop(conn, kind, record_id, name, value):
    put(conn, "property", record_kind=kind, record_id=record_id, name=name, value=value)


def person(conn, person_id, name, accounts=(), emails=(), excluded=0):
    conn.execute(
        "INSERT INTO person (person_id, display_name, excluded, manual) VALUES (?, ?, ?, 0)",
        (person_id, name, excluded),
    )
    for account in accounts:
        conn.execute(
            "INSERT INTO identity (source, account_id, person_id, manual) VALUES ('bitbucket', ?, ?, 0)",
            (account, person_id),
        )
    for email in emails:
        conn.execute(
            "INSERT INTO identity (source, account_id, person_id, manual) VALUES ('email', ?, ?, 0)",
            (email, person_id),
        )


def team(conn, team_id, name, repos, members):
    conn.execute(
        "INSERT INTO team (team_id, name, window_days, created_at) VALUES (?, ?, 90, ?)", (team_id, name, NOW)
    )
    for repo in repos:
        conn.execute(
            "INSERT INTO team_repo (team_id, repository_source, repository_id) VALUES (?, 'bitbucket', ?)",
            (team_id, repo),
        )
    for person_id, status in members.items():
        conn.execute(
            "INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit, pinned, manual) "
            "VALUES (?, ?, ?, '2026-07-01', '2026-10-01', 0, 0)",
            (team_id, person_id, status),
        )


def pr(conn, number, author, state, created, merged=None, repo=REPO, detailed=True, reviewers=None, title="Change"):
    sid = f"{repo}#{number}"
    put(
        conn, "change_request", source="bitbucket", source_id=sid, repository_id=repo, number=str(number),
        author_account=author, state=state, created_at=created, merged_at=merged, closed_at=merged, title=title,
    )
    prop(conn, "change_request", sid, "updated_on", merged or created)
    if detailed:
        prop(conn, "change_request", sid, "detail_updated_on", merged or created)
        if merged:
            prop(conn, "change_request", sid, "times_from", "activity")
    else:
        prop(conn, "change_request", sid, "times_from", "updated_on")
    for account, value in (reviewers or {}).items():
        prop(conn, "change_request", sid, f"reviewer:{account}", value)
    return sid


def event(conn, pr_sid, kind, actor, when):
    put(
        conn, "change_event", source="bitbucket", source_id=f"{pr_sid}:e{next(_events)}",
        change_request_id=pr_sid, type=kind, actor_account=actor, occurred_at=when,
    )


def commit(conn, sha, account, email, when, repo=REPO, merge=False):
    sid = f"{repo}:{sha}"
    put(
        conn, "vcs_commit", source="bitbucket", source_id=sid, repository_id=repo, sha=sha,
        author_account=account, author_email=email, committed_at=when,
    )
    if merge:
        prop(conn, "vcs_commit", sid, "is_merge", "1")


def seed(conn):
    person(conn, "p-ann", "Ann Example", accounts=["acc-ann"], emails=["ann@corp.example"])
    person(conn, "p-bob", "Bob Builder", accounts=["acc-bob"], emails=["bob@corp.example"])
    person(conn, "p-cy", "Cy Inactive", accounts=["acc-cy"])
    person(conn, "p-dee", "Dee Bot", accounts=["acc-dee"], excluded=1)
    team(conn, "t1", "Core", [REPO], {"p-ann": "active", "p-bob": "active", "p-cy": "inactive", "p-dee": "excluded"})
    put(conn, "repository", source="bitbucket", source_id=REPO, workspace="ws", name="core-repo", default_branch="main")
    put(conn, "repository", source="bitbucket", source_id=OTHER, workspace="ws", name="other-repo", default_branch="main")
    p1 = pr(conn, 1, "acc-ann", "MERGED", "2026-09-01T14:00:00Z", "2026-09-02T14:00:00Z",
            reviewers={"acc-bob": "approved", "acc-zed": "pending"})
    event(conn, p1, "comment", "acc-ann", "2026-09-01T15:00:00Z")  # own comment: not a review
    event(conn, p1, "comment", "acc-bob", "2026-09-01T16:00:00Z")  # first review, 2 h after opening
    event(conn, p1, "approved", "acc-bob", "2026-09-01T20:00:00Z")  # approval, 4 h after first review
    p2 = pr(conn, 2, "acc-ann", "MERGED", "2026-09-10T14:00:00Z", "2026-09-12T14:00:00Z",
            reviewers={"acc-bob": "pending"})
    event(conn, p2, "comment", "acc-zed", "2026-09-11T10:00:00Z")
    pr(conn, 3, "acc-ann", "MERGED", "2026-09-20T14:00:00Z", "2026-09-21T02:00:00Z", detailed=False)
    pr(conn, 4, "acc-bob", "OPEN", "2026-09-25T14:00:00Z", reviewers={"acc-ann": "pending"})
    pr(conn, 5, "acc-bob", "MERGED", "2026-08-10T14:00:00Z", "2026-08-11T14:00:00Z")
    pr(conn, 6, "acc-ann", "MERGED", "2026-09-05T14:00:00Z", "2026-09-06T14:00:00Z", repo=OTHER)
    commit(conn, "c1", "acc-ann", "ann@corp.example", "2026-09-02T12:00:00Z")
    commit(conn, "c2", None, "ann@corp.example", "2026-09-03T12:00:00Z")
    commit(conn, "c3", "acc-bob", "bob@corp.example", "2026-09-04T12:00:00Z", merge=True)
    commit(conn, "c4", "acc-dee", "bot@corp.example", "2026-09-04T12:00:00Z")
    commit(conn, "c5", "acc-cy", None, "2026-09-05T12:00:00Z")
