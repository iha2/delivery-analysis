from __future__ import annotations

from typing import Dict, List

from delivery_analysis.metrics import bitbucket as bb
from delivery_analysis.metrics.registry import PER_PERSON, TEAM_BREAKDOWN, TEAM_SERIES, Metric

BB = ("bitbucket",)

METRICS: List[Metric] = [
    Metric("prs_merged", "PRs merged", "count", PER_PERSON, BB, compute=bb.prs_merged,
           description="Merged pull requests authored, by merge date."),
    Metric("time_to_merge", "Time to merge", "hours", PER_PERSON, BB, better="lower", aggregate="median",
           compute=bb.time_to_merge, description="Median hours from opening a pull request to merging it."),
    Metric("reviews_given", "Reviews given", "count", PER_PERSON, BB, compute=bb.reviews_given,
           description="Distinct pull requests approved or commented on, excluding one's own."),
    Metric("reviews_assigned", "Reviews assigned", "count", PER_PERSON, BB, better="neutral",
           compute=bb.reviews_assigned, description="Pull requests that list the person as a reviewer."),
    Metric("review_response_rate", "Review response rate", "ratio", PER_PERSON, BB, aggregate="mean",
           compute=bb.review_response_rate,
           description="Share of assigned reviews the person approved or commented on."),
    Metric("review_load", "Pending reviews", "count", PER_PERSON, BB, better="neutral", min_sample=0,
           windowed=False, compute=bb.review_load,
           description="Open pull requests waiting on the person's review, right now."),
    Metric("commits", "Commits", "count", PER_PERSON, BB, compute=bb.commits,
           description="Non-merge commits authored."),
    Metric("work_in_progress", "Open PRs", "count", PER_PERSON, BB, better="neutral", min_sample=0,
           windowed=False, compute=bb.work_in_progress, description="Open pull requests authored, right now."),
    Metric("prs_merged_weekly", "PRs merged by week", "count", TEAM_SERIES, BB, compute=bb.prs_merged_weekly,
           description="Merged pull requests per week."),
    Metric("lead_time_breakdown", "PR lead time breakdown", "hours", TEAM_BREAKDOWN, BB, better="lower",
           compute=bb.lead_time_breakdown,
           description="Median hours waiting for review, in review, and from approval to merge."),
    # Registered now, computed by later specs (Jira, token usage, linking, Confluence).
    Metric("issues_done", "Issues done", "count", PER_PERSON, ("jira",),
           description="Issues that reached COMPLETED."),
    Metric("issues_done_weekly", "Issues done by week", "count", TEAM_SERIES, ("jira",),
           description="Issues completed per week."),
    Metric("cycle_time", "Cycle time", "hours", PER_PERSON, ("jira",), better="lower", aggregate="median",
           description="First In Progress to COMPLETED."),
    Metric("story_points_done", "Story points done", "points", PER_PERSON, ("jira",),
           description="Story points of completed issues."),
    Metric("cost_spent", "Claude cost", "usd", PER_PERSON, ("claude_usage",), better="neutral",
           description="Claude cost in USD."),
    Metric("story_points_per_dollar", "Impact per token (cost proxy)", "points_per_usd", PER_PERSON,
           ("jira", "claude_usage"), description="Story points done per dollar of attributed Claude cost."),
    Metric("unattributed_cost_share", "Unattributed cost share", "ratio", PER_PERSON, ("claude_usage",),
           better="lower", aggregate="mean", description="Share of cost not attributed to any ticket."),
    Metric("ask_generate_ratio", "Ask to generate ratio", "ratio", PER_PERSON, ("claude_usage",),
           better="neutral", aggregate="mean", description="Asking cost relative to generating cost."),
    Metric("prs_with_issue_link", "PRs with an issue link", "ratio", PER_PERSON, ("bitbucket", "links"),
           aggregate="mean", description="Share of pull requests linked to a Jira issue."),
    Metric("documentation_activity", "Documentation activity", "count", TEAM_SERIES, ("confluence",),
           description="Confluence page edits per week."),
]

BY_NAME: Dict[str, Metric] = {metric.name: metric for metric in METRICS}
