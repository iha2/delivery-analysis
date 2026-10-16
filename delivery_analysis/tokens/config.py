from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Tuple

ALGO_VERSION = "a-plus-1"


@dataclass(frozen=True)
class AttributionConfig:
    """Every attribution and ranking threshold. Judgement values; calibrate on real data."""

    prior: float = 0.25
    idle_days: int = 7
    commit_weight: float = 1.0
    pr_created_weight: float = 1.0
    pr_event_weight: float = 1.0
    transition_weight: float = 1.0
    pr_event_types: Tuple[str, ...] = ("comment", "approved", "update")
    generate_half_saturation: float = 10.0
    min_tickets: int = 3
    high_min_tickets: int = 5
    cost_floor_usd: float = 20.0
    ticket_ratio_floor_usd: float = 1.0
    high_share: float = 0.8
    medium_share: float = 0.5
    high_max_unattributed: float = 0.2
    medium_max_unattributed: float = 0.4
    unranked_max_unattributed: float = 0.5

    def as_json(self) -> Dict[str, Any]:
        values = asdict(self)
        values["pr_event_types"] = list(self.pr_event_types)
        return values


DEFAULT_CONFIG = AttributionConfig()
