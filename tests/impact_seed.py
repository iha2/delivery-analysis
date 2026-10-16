"""Made-up Jira rows, pull requests and links on top of the metrics seed.

Team "Core" (t1): Ann and Bob are active members, Cy is inactive, Dee is an excluded bot, acc-zed and
acc-qa are Jira users nobody has mapped (acc-qa is a QA owner who never commits). September 2026 in
New York time. Completed issues (id, assignee, what, credited to):

  1 Ann    Story  done 09-10  started 09-08  5 pts   linked PR 2 (Ann)           -> Ann 1.0 by pull request
  2 Ann    Bug    done 09-20  never started  no pts  no linked PR                -> Ann 1.0 by assignee
  3 QA     Story  done 09-21T02Z (Sunday 09-20 local)  started 09-19T02Z  3 pts
                                             linked PRs 3 (Ann) and 7 (Bob)        -> Ann 0.5, Bob 0.5 by pull request
  4 Ann    Epic   done 09-12  13 pts, counts_for_impact 0                          (never counted)
  5 Ann    status DISREGARD (category dropped)  8 pts                              (never counted)
  6 zed    Task   done 09-15  started 09-14  8 pts   no linked PR                -> zed 1.0 by assignee (unmapped)
  7 Cy     Story  done 09-16  started 09-15  2 pts   no linked PR                -> Cy 1.0 (inactive: outside the team)
  8 Ann    Story  done 08-10  2 pts                                                (previous window)
  9 nobody Bug    done 09-18  started 09-17  1 pt    no linked PR                -> nobody (unassigned)

Pull requests 2, 3 and 7 (merged in the window, repository REPO) are linked; PR 1 is not.
"""
from metrics_seed import REPO, pr, prop, put, seed


def issue(conn, sid, assignee, *, category="done", resolved=None, started=None, points=None, kind="Story",
          counts="1"):
    put(
        conn, "work_item", source="jira", source_id=sid, project="MD", key=f"MD-{sid}", type=kind,
        assignee_account=assignee, status="COMPLETED" if category == "done" else "Other",
        status_category=category, started_at=started, resolved_at=resolved, story_points=points,
    )
    prop(conn, "work_item", sid, "counts_for_impact", counts)


def link_pr(conn, number, issue_id, repo=REPO, found_by="pr_title"):
    put(
        conn, "link", source="linker", source_id=f"{repo}#{number}->{issue_id}:{found_by}", from_kind="change_request",
        from_id=f"{repo}#{number}", to_kind="work_item", to_id=issue_id, kind="implements", found_by=found_by,
    )


def seed_impact(conn):
    seed(conn)
    pr(conn, 7, "acc-bob", "MERGED", "2026-09-19T14:00:00Z", "2026-09-20T14:00:00Z")
    issue(conn, "1", "acc-ann", resolved="2026-09-10T14:00:00Z", started="2026-09-08T14:00:00Z", points=5)
    issue(conn, "2", "acc-ann", resolved="2026-09-20T14:00:00Z", kind="Bug")
    issue(conn, "3", "acc-qa", resolved="2026-09-21T02:00:00Z", started="2026-09-19T02:00:00Z", points=3)
    issue(conn, "4", "acc-ann", resolved="2026-09-12T14:00:00Z", started="2026-09-01T14:00:00Z", points=13,
          kind="Epic", counts="0")
    issue(conn, "5", "acc-ann", category="dropped", resolved="2026-09-12T14:00:00Z", points=8)
    issue(conn, "6", "acc-zed", resolved="2026-09-15T14:00:00Z", started="2026-09-14T14:00:00Z", points=8, kind="Task")
    issue(conn, "7", "acc-cy", resolved="2026-09-16T14:00:00Z", started="2026-09-15T14:00:00Z", points=2)
    issue(conn, "8", "acc-ann", resolved="2026-08-10T14:00:00Z", started="2026-08-09T14:00:00Z", points=2)
    issue(conn, "9", None, resolved="2026-09-18T14:00:00Z", started="2026-09-17T14:00:00Z", points=1, kind="Bug")
    link_pr(conn, 2, "1")
    link_pr(conn, 3, "3")
    link_pr(conn, 3, "3", found_by="pr_branch")  # the same pull request linked twice still counts once
    link_pr(conn, 7, "3")
    # An issue-to-issue link from the Jira connector must never make a pull request look linked.
    put(conn, "link", source="jira", source_id="issuelink:1", from_kind="work_item", from_id="2",
        to_kind="work_item", to_id="1", kind="Blocks", found_by="jira")
