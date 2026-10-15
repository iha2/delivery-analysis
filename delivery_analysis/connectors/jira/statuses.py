from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

# Default mapping by status NAME. Jira's own status categories are not used: on this site
# "Tech Review" is category "new" and "DISREGARD" is category "done".
SEED: Dict[str, str] = {
    "Backlog": "todo",
    "To Do": "todo",
    "Definition": "todo",
    "Design is Needed": "todo",
    "Design is Done": "todo",
    "In Progress": "in_progress",
    "Dev Done": "in_progress",
    "Code Review": "in_review",
    "Tech Review": "in_review",
    "In Review": "in_review",
    "Ready for QA": "in_review",
    "In QA": "in_review",
    "UAT": "in_review",
    "UAT Passed": "in_review",
    "Ready for UAT": "in_review",
    "Ready for Release": "in_review",
    "Deployed": "in_review",
    "COMPLETED": "done",
    "DISREGARD": "dropped",
}


def seed_for(names: Iterable[str]) -> Tuple[Dict[str, str], List[str]]:
    """Split status names into (seeded mapping, sorted names that still need `projects map`)."""
    unique = sorted(set(names))
    mapped = {name: SEED[name] for name in unique if name in SEED}
    unmapped = [name for name in unique if name not in SEED]
    return mapped, unmapped
