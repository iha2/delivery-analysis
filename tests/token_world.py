"""Made-up people, Jira tickets, pull requests and Claude usage for token-attribution tests.

Everyone here is fictional and lives on *.example domains. Days are UTC dates (YYYY-MM-DD).
Jira and Bitbucket share one account id per person, as on the real site.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Union

from delivery_analysis.model.records import Record
from delivery_analysis.store.upsert import upsert_record

NOW = "2026-03-21T00:00:00Z"
SOURCE = "claude_code_analytics"
REPO = "{33333333-3333-3333-3333-333333333333}"
STATUS_MAP = {
    "todo": ("Backlog", "To Do", "Definition", "Design is Needed", "Design is Done"),
    "in_progress": ("In Progress", "Dev Done"),
    "in_review": ("Code Review", "Tech Review", "In Review", "Ready for QA", "In QA", "UAT", "UAT Passed",
                  "Ready for UAT", "Ready for Release", "Deployed"),
    "done": ("COMPLETED",),
    "dropped": ("DISREGARD",),
}
CATEGORY = {status: category for category, names in STATUS_MAP.items() for status in names}
NO_IMPACT_TYPES = {"Epic", "Initiative", "Sub-task", "Sub-bug"}


@dataclass(frozen=True)
class Person:
    person_id: str
    account: str
    email: str


class Ticket:
    def __init__(self, world: "World", source_id: str, issue_key: str, assignee: Optional[Person],
                 kind: str, points: Optional[float], project: str) -> None:
        self.world = world
        self.id = source_id
        self.issue_key = issue_key
        self.assignee = assignee
        self.type = kind
        self.points = points
        self.project = project
        self.status = "To Do"
        self.started_at: Optional[str] = None
        self.resolved_at: Optional[str] = None
        self._steps = itertools.count(1)
        self._save()

    @property
    def key(self):
        return ("jira", self.id)

    def move(self, status: str, day: str, by: Optional[Person] = None, at: str = "10:00:00") -> "Ticket":
        actor = by or self.assignee
        when = f"{day}T{at}Z"
        self.world.put(
            "work_item_transition", source="jira", source_id=f"{self.id}:{next(self._steps)}:0",
            work_item_id=self.id, from_status=self.status, to_status=status,
            actor_account=actor.account if actor else None, occurred_at=when,
        )
        if status == "In Progress" and self.started_at is None:
            self.started_at = when
        self.resolved_at = when if CATEGORY.get(status) == "done" else None
        self.status = status
        self._save()
        return self

    def in_progress(self, day: str, by: Optional[Person] = None) -> "Ticket":
        return self.move("In Progress", day, by)

    def completed(self, day: str, by: Optional[Person] = None) -> "Ticket":
        return self.move("COMPLETED", day, by)

    def dropped(self, day: str, by: Optional[Person] = None) -> "Ticket":
        return self.move("DISREGARD", day, by)

    def _save(self) -> None:
        self.world.put(
            "work_item", source="jira", source_id=self.id, project=self.project, key=self.issue_key,
            type=self.type, summary="Made-up ticket",
            assignee_account=self.assignee.account if self.assignee else None,
            status=self.status, status_category=CATEGORY.get(self.status), created_at="2026-01-05T09:00:00Z",
            started_at=self.started_at, resolved_at=self.resolved_at, story_points=self.points,
        )


class World:
    def __init__(self, conn, project: str = "MD") -> None:
        self.conn = conn
        self.project = project
        self._ids = itertools.count(10001)
        self._prs = itertools.count(1)
        self._shas = itertools.count(1)
        self._events = itertools.count(1)
        conn.execute(
            "INSERT INTO project_selection (source, project_key, project_id, name, story_points_field, "
            "excluded_types, added_at) VALUES ('jira', ?, '900', 'Made-up project', 'customfield_10004', "
            "'Epic,Initiative', ?)",
            (project, NOW),
        )
        for status, category in CATEGORY.items():
            conn.execute(
                "INSERT INTO status_mapping (source, project_key, status_name, category) VALUES ('jira', ?, ?, ?)",
                (project, status, category),
            )

    def put(self, table: str, **values) -> None:
        upsert_record(self.conn, Record(table, values), NOW)

    def _identity(self, source: str, account: str, person_id: Optional[str], manual: int = 0) -> None:
        self.conn.execute(
            "INSERT INTO identity (source, account_id, person_id, manual) VALUES (?, ?, ?, ?)",
            (source, account, person_id, manual),
        )

    def person(self, name: str, *, email: Optional[str] = None, excluded: bool = False) -> Person:
        first = name.split()[0].lower()
        person = Person(f"p-{first}", f"acc-{first}", email or f"{first}@corp.example")
        self.conn.execute(
            "INSERT INTO person (person_id, display_name, excluded, manual) VALUES (?, ?, ?, 0)",
            (person.person_id, name, 1 if excluded else 0),
        )
        self._identity("bitbucket", person.account, person.person_id)
        self._identity("email", person.email, person.person_id)
        self._identity("jira", person.account, None)  # the Jira connector never sets person_id
        return person

    def map_api_key(self, person: Person, key_name: str) -> None:
        self._identity("claude_api_key", key_name, person.person_id, manual=1)

    def map_email(self, person: Person, email: str) -> None:
        self._identity("email", email.lower(), person.person_id, manual=1)

    def ticket(self, issue_key: str, *, assignee: Optional[Person] = None, points: Optional[float] = None,
               kind: str = "Story", parent: Optional[Ticket] = None) -> Ticket:
        ticket = Ticket(self, str(next(self._ids)), issue_key, assignee, kind, points, self.project)
        self.put("property", record_kind="work_item", record_id=ticket.id, name="counts_for_impact",
                 value="0" if kind in NO_IMPACT_TYPES else "1")
        if parent is not None:
            self.put("link", source="jira", source_id=f"parent:{ticket.id}:{parent.id}", from_kind="work_item",
                     from_id=ticket.id, to_kind="work_item", to_id=parent.id, kind="parent", found_by="jira")
        return ticket

    def pull_request(self, author: Person, *, created: str, merged: Optional[str] = None,
                     links: Sequence[Ticket] = ()) -> str:
        number = next(self._prs)
        sid = f"{REPO}#{number}"
        merged_at = f"{merged}T15:00:00Z" if merged else None
        self.put("change_request", source="bitbucket", source_id=sid, repository_id=REPO, number=str(number),
                 author_account=author.account, title="Made-up change", branch=f"feature/change-{number}",
                 state="MERGED" if merged else "OPEN", created_at=f"{created}T09:00:00Z", merged_at=merged_at,
                 closed_at=merged_at, files_changed=3, commit_count=2)
        for ticket in links:
            self.put("link", source="linker", source_id=f"pr:{sid}:{ticket.id}", from_kind="change_request",
                     from_id=sid, to_kind="work_item", to_id=ticket.id, kind="implements", found_by="pr_title")
        return sid

    def commit(self, author: Person, day: str, *, pr: Optional[str] = None, merge: bool = False,
               email_only: bool = False, links: Iterable[Ticket] = ()) -> str:
        n = next(self._shas)
        sid = f"{REPO}:sha{n}"
        self.put("vcs_commit", source="bitbucket", source_id=sid, repository_id=REPO, sha=f"sha{n}",
                 author_account="" if email_only else author.account, author_email=author.email,
                 author_name="Made Up", committed_at=f"{day}T11:00:00Z", change_request_id=pr)
        if merge:
            self.put("property", record_kind="vcs_commit", record_id=sid, name="is_merge", value="1")
        for ticket in links:
            self.put("link", source="linker", source_id=f"commit:{sid}:{ticket.id}", from_kind="vcs_commit",
                     from_id=sid, to_kind="work_item", to_id=ticket.id, kind="implements", found_by="commit_message")
        return sid

    def event(self, pr: str, actor: Person, kind: str, day: str) -> None:
        self.put("change_event", source="bitbucket", source_id=f"{pr}:e{next(self._events)}", change_request_id=pr,
                 type=kind, actor_account=actor.account, occurred_at=f"{day}T13:00:00Z")

    def usage(self, who: Union[Person, str], day: str, cents: float, *, model: str = "model-a",
              accepted_edits: Optional[int] = None, input_tokens: int = 1000) -> None:
        if isinstance(who, Person):
            actor_type, actor = "email", who.email
        elif "@" in who:
            actor_type, actor = "email", who.lower()
        else:
            actor_type, actor = "claude_api_key", who
        self.conn.execute(
            "INSERT INTO claude_usage_day (source, day, actor_type, actor, model, cost_usd, input_tokens, "
            "output_tokens, cache_read_tokens, cache_creation_tokens, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?) "
            "ON CONFLICT(source, day, actor_type, actor, model) DO UPDATE SET "
            "cost_usd = cost_usd + excluded.cost_usd, input_tokens = input_tokens + excluded.input_tokens",
            (SOURCE, day, actor_type, actor, model, cents / 100.0, input_tokens, NOW),
        )
        if accepted_edits is not None:
            self.conn.execute(
                "INSERT INTO claude_activity_day (source, day, actor_type, actor, sessions, edits_accepted, "
                "tool_actions, customer_types, fetched_at) VALUES (?, ?, ?, ?, 1, ?, '{}', 'api', ?) "
                "ON CONFLICT(source, day, actor_type, actor) DO UPDATE SET "
                "edits_accepted = edits_accepted + excluded.edits_accepted",
                (SOURCE, day, actor_type, actor, accepted_edits, NOW),
            )

    def team(self, team_id: str, name: str, members: Sequence[Person]) -> None:
        self.conn.execute("INSERT INTO team (team_id, name, window_days, created_at) VALUES (?, ?, 90, ?)",
                          (team_id, name, NOW))
        for person in members:
            self.conn.execute(
                "INSERT INTO team_member (team_id, person_id, status, first_seen, last_commit, pinned, manual) "
                "VALUES (?, ?, 'active', '2026-01-01', '2026-03-01', 0, 0)",
                (team_id, person.person_id),
            )
