from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

BOT_TOKENS = frozenset({"bot", "bots", "jenkins", "noreply", "service", "automation", "ci"})


@dataclass(frozen=True)
class EmailActivity:
    """What the commits say about one lower-case author email."""

    email: str
    names: Mapping[str, int]  # name spelling -> number of commits
    account_ids: Tuple[Tuple[str, str], ...]  # (source, account id) seen with this email
    commits: int
    last_commit: str  # UTC ISO timestamp


@dataclass(frozen=True)
class MergedPerson:
    display_name: str
    emails: Tuple[str, ...]  # sorted
    account_ids: Tuple[Tuple[str, str], ...]  # sorted
    commits: int
    last_commit: str
    is_bot: bool

    @property
    def key(self) -> str:
        """Stable handle for this person within one run: the first sorted email."""
        return self.emails[0]


@dataclass(frozen=True)
class PossibleDuplicate:
    email_a: str
    email_b: str
    reason: str


def _tokens(text: str) -> List[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split()


def _local_part(email: str) -> str:
    return email.split("@", 1)[0]


def _norm(name: str) -> str:
    return "".join(_tokens(name))


def _initial_surname(name: str) -> str:
    tokens = _tokens(name)
    return tokens[0][0] + tokens[-1] if len(tokens) >= 2 else ""


def names_compatible(a: Mapping[str, int], b: Mapping[str, int], local: str = "") -> bool:
    """Two sets of author names can belong to one person when, for some pair of names, the
    normalized names are equal, or one equals the email local part, or one is the first
    initial plus surname of the other."""
    local_norm = re.sub(r"[^a-z0-9]", "", local.lower())
    for name_a in a:
        norm_a = _norm(name_a)
        if not norm_a:
            continue
        initial_a = _initial_surname(name_a)
        for name_b in b:
            norm_b = _norm(name_b)
            if not norm_b:
                continue
            if norm_a == norm_b:
                return True
            if local_norm and local_norm in (norm_a, norm_b):
                return True
            if initial_a and initial_a == norm_b:
                return True
            initial_b = _initial_surname(name_b)
            if initial_b and initial_b == norm_a:
                return True
    return False


def _is_bot(activity: EmailActivity) -> bool:
    local = _local_part(activity.email)
    tokens = set(re.split(r"[^a-z0-9]+", local))
    for name in activity.names:
        tokens.update(_tokens(name))
    return bool(tokens & BOT_TOKENS) or "noreply" in re.sub(r"[^a-z0-9]", "", local)


def _display_name(names: Counter, fallback: str) -> str:
    cleaned = [(count, name.strip()) for name, count in names.items() if name.strip()]
    if not cleaned:
        return fallback
    spaced = [(count, name) for count, name in cleaned if " " in name]
    pool = spaced or cleaned
    return sorted(pool, key=lambda item: (-item[0], -len(item[1]), item[1]))[0][1]


def merge_identities(
    activities: Sequence[EmailActivity],
    pinned: Optional[Mapping[str, str]] = None,
) -> Tuple[List[MergedPerson], List[PossibleDuplicate]]:
    """Group author emails into people. Weak matches go to the duplicate list, never guessed.

    `pinned` maps an email to the person a human assigned it to; two emails pinned to different
    people are never merged, so a manual split is replayed on every run."""
    owners = pinned or {}
    items = sorted(activities, key=lambda activity: activity.email)
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def blocked(i: int, j: int) -> bool:
        owner_i, owner_j = owners.get(items[i].email), owners.get(items[j].email)
        return owner_i is not None and owner_j is not None and owner_i != owner_j

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[max(root_i, root_j)] = min(root_i, root_j)

    # A shared account id is the same person.
    by_account: Dict[Tuple[str, str], int] = {}
    for index, item in enumerate(items):
        for account in item.account_ids:
            if account in by_account:
                if not blocked(index, by_account[account]):
                    union(index, by_account[account])
            else:
                by_account[account] = index

    # The same part before the @ is the same person only when the names are compatible.
    by_local: Dict[str, List[int]] = {}
    for index, item in enumerate(items):
        by_local.setdefault(_local_part(item.email), []).append(index)
    undecided: List[Tuple[int, int, str]] = []
    for local, indexes in by_local.items():
        for position, i in enumerate(indexes):
            for j in indexes[position + 1:]:
                if blocked(i, j):
                    continue
                if names_compatible(items[i].names, items[j].names, local):
                    union(i, j)
                else:
                    undecided.append((i, j, local))

    groups: Dict[int, List[int]] = {}
    for index in range(len(items)):
        groups.setdefault(find(index), []).append(index)

    people: List[MergedPerson] = []
    key_of_root: Dict[int, str] = {}
    for root, members in groups.items():
        acts = [items[i] for i in members]
        emails = tuple(sorted(activity.email for activity in acts))
        names: Counter = Counter()
        for activity in acts:
            names.update(activity.names)
        accounts = tuple(sorted({account for activity in acts for account in activity.account_ids}))
        people.append(
            MergedPerson(
                display_name=_display_name(names, _local_part(emails[0])),
                emails=emails,
                account_ids=accounts,
                commits=sum(activity.commits for activity in acts),
                last_commit=max(activity.last_commit for activity in acts),
                is_bot=any(_is_bot(activity) for activity in acts),
            )
        )
        key_of_root[root] = emails[0]
    people.sort(key=lambda person: (person.display_name.lower(), person.emails))

    duplicates: List[PossibleDuplicate] = []
    seen: Set[Tuple[str, str]] = set()
    for i, j, local in undecided:
        root_i, root_j = find(i), find(j)
        if root_i == root_j:
            continue
        pair = tuple(sorted((key_of_root[root_i], key_of_root[root_j])))
        if pair in seen:
            continue
        seen.add(pair)
        duplicates.append(
            PossibleDuplicate(pair[0], pair[1], f"same name before the @ ({local}) but different names")
        )
    duplicates.sort(key=lambda dup: (dup.email_a, dup.email_b))
    return people, duplicates
