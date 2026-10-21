from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from delivery_analysis.core.time_utils import to_utc_iso

# Rich-text and bulky fields are never requested and never stored as properties.
EXCLUDED_FIELDS = frozenset({"description", "comment", "worklog", "attachment"})
SEARCH_FIELDS = ["*all", "-description", "-comment", "-worklog", "-attachment"]
# Fields already stored as work_item columns, links, or the cursor: no property row for them.
SKIP_PROPERTY = frozenset(
    {"summary", "issuelinks", "parent", "created", "updated", "project", "status", "assignee",
     "reporter", "issuetype"}
)
# The only keys kept from an object inside a list (so goals and URLs never enter properties).
_ITEM_KEYS = ("id", "name", "value", "key", "state", "boardId", "startDate", "endDate", "releaseDate", "released")
_NAME_KEYS = ("name", "value", "key", "displayName")
_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _snake(key: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()


class FieldCatalogue:
    """Names Jira fields for the property table. Built once per run from GET /field."""

    def __init__(self, fields: Iterable[Mapping[str, Any]]) -> None:
        self._by_id: Dict[str, Mapping[str, Any]] = {str(f["id"]): f for f in fields}

    def is_custom(self, field_id: str) -> bool:
        return field_id.startswith("customfield_")

    def has(self, field_id: str) -> bool:
        return field_id in self._by_id

    def property_name(self, field_id: str) -> str:
        """System fields keep their key in snake case; custom fields are `<slug>_<id>`, so two
        fields with the same display name never collide."""
        if not self.is_custom(field_id):
            return _snake(field_id)
        meta = self._by_id.get(field_id)
        slug = _slug(str(meta.get("name") or "")) if meta else ""
        if not slug:
            return field_id
        return f"{slug}_{field_id.split('_', 1)[1]}"

    def ids_by_name(self, name: str) -> List[str]:
        """Custom field ids whose display name equals `name` (case-insensitive), sorted."""
        wanted = name.strip().lower()
        return sorted(
            field_id
            for field_id, meta in self._by_id.items()
            if self.is_custom(field_id) and str(meta.get("name") or "").strip().lower() == wanted
        )

    def points_candidates(self) -> List[str]:
        found = []
        for field_id, meta in self._by_id.items():
            schema = meta.get("schema") or {}
            if (
                self.is_custom(field_id)
                and schema.get("type") == "number"
                and "story point" in str(meta.get("name") or "").lower()
            ):
                found.append(field_id)
        return sorted(found)


def _is_doc(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") == "doc"


def _plain(value: Any) -> bool:
    return value is not None and value != "" and not isinstance(value, (dict, list))


def _scalar(value: Any) -> Any:
    if isinstance(value, str) and _DATE_TIME.match(value):
        try:
            return to_utc_iso(value) or value
        except ValueError:
            return value
    return value


def _text(value: Any) -> str:
    value = _scalar(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _list_item(item: Any) -> Any:
    if isinstance(item, dict):
        if "accountId" in item:
            return item["accountId"]
        if _is_doc(item):
            return None
        picked = {key: _scalar(item[key]) for key in _ITEM_KEYS if key in item and _plain(item[key])}
        return picked or None
    if _plain(item):
        return _scalar(item)
    return None


def flatten_value(value: Any) -> Optional[str]:
    """Text for one property value, or None when the field is empty, rich text, or has nothing plain."""
    if value is None or value == "" or value == [] or value == {} or _is_doc(value):
        return None
    if isinstance(value, list):
        items = [item for item in (_list_item(entry) for entry in value) if item is not None]
        return json.dumps(items, sort_keys=True) if items else None
    if isinstance(value, dict):
        if "accountId" in value:
            return str(value["accountId"])
        for key in _NAME_KEYS:
            if _plain(value.get(key)):
                return _text(value[key])
        picked = {key: _scalar(value[key]) for key in _ITEM_KEYS if key in value and _plain(value[key])}
        return json.dumps(picked, sort_keys=True) if picked else None
    return _text(value)


def points_value(raw: Any) -> Optional[float]:
    """A story points number, or None for empty or non-numeric values (never 0 for empty)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def detect_points_field(counts: Mapping[str, int]) -> Tuple[Optional[str], str]:
    """Pick the story points field with the most values; refuse when there is none or a near tie."""
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    if not ranked or ranked[0][1] == 0:
        return None, "No story points field has a value in the sampled issues. Pass --points-field."
    if len(ranked) > 1 and ranked[1][1] >= 0.8 * ranked[0][1]:
        return None, (
            f"{ranked[0][0]} and {ranked[1][0]} are both filled about equally. Pass --points-field."
        )
    return ranked[0][0], ""
