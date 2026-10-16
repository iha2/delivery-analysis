from __future__ import annotations

from typing import List, Sequence

from delivery_analysis.tokens.config import DEFAULT_CONFIG, AttributionConfig
from delivery_analysis.tokens.types import Allocation, Candidate


def _level(method: str, candidate: Candidate) -> str:
    if not candidate.known:
        return "low"  # related only as the current assignee
    if method == "window_single":
        return "high" if candidate.evidence > 0 else "medium"
    if method == "window_evidence":
        return "medium"
    return "low"


def allocate(
    cost_usd: float,
    candidates: Sequence[Candidate],
    has_untracked_commits: bool,
    config: AttributionConfig = DEFAULT_CONFIG,
) -> List[Allocation]:
    """Split one person-day's cost: weight = prior + evidence, which is an equal split without evidence."""
    if cost_usd == 0:
        return []
    if cost_usd < 0:
        # A refund or correction: keep the signed amount in one unattributed row so totals reconcile.
        return [Allocation(None, round(cost_usd, 6), None, None, "unattributed", None, "adjustment")]
    total_cost = round(cost_usd, 6)
    if not candidates:
        reason = "untracked_work" if has_untracked_commits else "no_active_ticket"
        return [Allocation(None, total_cost, None, None, "unattributed", None, reason)]
    ordered = sorted(candidates, key=lambda c: c.ticket)
    weights = [config.prior + max(0.0, c.evidence) for c in ordered]
    if len(ordered) == 1:
        method = "window_single"
    elif any(c.evidence > 0 for c in ordered):
        method = "window_evidence"
    else:
        method = "window_equal"
    total_weight = sum(weights)
    shares = [round(total_cost * w / total_weight, 6) for w in weights]
    # The rounding remainder goes to the largest share so the rows add up to the day's cost.
    biggest = max(range(len(shares)), key=lambda i: (shares[i], -i))
    shares[biggest] = round(shares[biggest] + total_cost - sum(shares), 6)
    return [
        Allocation(c.ticket, share, round(w, 6), c.evidence, method, _level(method, c))
        for c, w, share in zip(ordered, weights, shares)
    ]
