from __future__ import annotations

from typing import Dict, List

from delivery_analysis.metrics import bitbucket as bb
from delivery_analysis.metrics import impact as im
from delivery_analysis.metrics import jira as jr
from delivery_analysis.metrics import tokens as tk
from delivery_analysis.metrics.registry import PER_PERSON, TEAM_BREAKDOWN, TEAM_SERIES, Metric

BB = ("bitbucket",)
CU = ("claude_usage",)
JC = ("jira", "claude_usage")

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
    Metric("issues_done", "Issues done", "count", PER_PERSON, ("jira",), compute=jr.issues_done,
           description="Issues that reached COMPLETED, credited to the authors of their linked pull requests (the assignee when none is linked); excludes Epics, Initiatives and sub-tasks."),
    Metric("issues_done_weekly", "Issues done by week", "count", TEAM_SERIES, ("jira",),
           compute=jr.issues_done_weekly, description="Issues completed per week."),
    Metric("cycle_time", "Cycle time", "hours", PER_PERSON, ("jira",), better="lower", aggregate="median",
           compute=jr.cycle_time, description="First In Progress to COMPLETED."),
    Metric("story_points_done", "Story points done", "points", PER_PERSON, ("jira",),
           compute=jr.story_points_done,
           description="Story points of completed issues, split by each author's share of the linked pull requests (the assignee when none is linked)."),
    Metric("story_points_weekly", "Story points by week", "points", TEAM_SERIES, ("jira",),
           compute=im.story_points_weekly,
           description="Story points of completed issues per week, credited by pull request evidence; "
                       "rows also carry the completed issues and the issues without points."),
    Metric("points_by_type", "Points by issue type", "points", TEAM_BREAKDOWN, ("jira",),
           compute=im.points_by_type, description="Story points of completed issues by issue type."),
    Metric("cycle_time_weekly", "Cycle time by week", "hours", TEAM_SERIES, ("jira",), better="lower",
           compute=im.cycle_time_weekly,
           description="Median and 85th percentile hours from first In Progress to COMPLETED, and the median "
                       "to the first merged linked pull request, by week, counting each issue once."),
    Metric("cycle_time_summary", "Cycle time (team, by issue)", "hours", TEAM_BREAKDOWN, ("jira",),
           better="lower", compute=im.cycle_time_summary,
           description="Median and 85th percentile hours from first In Progress to COMPLETED and to the first "
                       "merged linked pull request, counting each completed issue once."),
    Metric("prs_linked_weekly", "PRs linked to an issue by week", "count", TEAM_SERIES, ("bitbucket", "links"),
           compute=im.prs_linked_weekly,
           description="Merged pull requests per week, split by whether an issue key links them."),
    Metric("cost_spent", "Claude cost", "usd", PER_PERSON, CU, better="neutral", sample_noun="days with cost",
           compute=tk.cost_spent, description="Claude Code cost in USD (the API's estimate), by UTC day."),
    Metric("story_points_per_dollar", "Impact per token (cost proxy)", "points_per_usd", PER_PERSON, JC,
           aggregate="ratio", min_sample=3, min_denominator=20.0, sample_noun="completed tickets",
           compute=tk.story_points_per_dollar,
           description="Credited story points of tickets completed in the window per dollar of Claude cost "
                       "attributed to them."),
    Metric("story_points_per_dollar_all_in", "Impact per token, all-in", "points_per_usd", PER_PERSON, JC,
           aggregate="ratio", min_sample=3, min_denominator=20.0, sample_noun="completed tickets",
           compute=tk.story_points_per_dollar_all_in,
           description="Credited story points per dollar of all Claude cost in the window, attributed or not."),
    Metric("story_points_per_dollar_weekly", "Impact per token by week", "points_per_usd", TEAM_SERIES, JC,
           compute=tk.story_points_per_dollar_weekly,
           description="Story points per attributed dollar, by completion week."),
    Metric("unattributed_cost_share", "Unattributed cost share", "ratio", PER_PERSON, CU, better="lower",
           aggregate="ratio", sample_noun="days with cost", compute=tk.unattributed_cost_share,
           description="Share of cost not attributed to any ticket."),
    Metric("ask_generate_ratio", "Ask to generate ratio (coarse)", "multiple", PER_PERSON, CU, better="neutral",
           aggregate="ratio", sample_noun="days with cost", compute=tk.ask_generate_ratio,
           description="Asking cost relative to generating cost; a coarse v1 proxy shown as context only."),
    Metric("cost_by_purpose_weekly", "Claude cost by purpose by week", "usd", TEAM_SERIES, CU, better="neutral",
           compute=tk.cost_by_purpose_weekly, description="Ask, generate and unclassified cost per UTC week."),
    Metric("prs_with_issue_link", "PRs with an issue link", "ratio", PER_PERSON, ("bitbucket", "links"),
           aggregate="mean", compute=im.prs_with_issue_link,
           description="Share of merged pull requests linked to a Jira issue by key in the title or branch."),
    Metric("documentation_activity", "Documentation activity", "count", TEAM_SERIES, ("confluence",),
           description="Confluence page edits per week."),
]

BY_NAME: Dict[str, Metric] = {metric.name: metric for metric in METRICS}
