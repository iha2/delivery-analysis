from __future__ import annotations

import re
from datetime import datetime, timezone, tzinfo

_PROJECT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def jql_date(since_utc: str, tz: tzinfo) -> str:
    """A UTC `YYYY-MM-DDTHH:MM:SSZ` instant as Jira's `yyyy/MM/dd HH:mm` in the profile time zone.

    Converting from UTC always gives a local time that exists, so a DST gap cannot occur; the
    repeated hour at fall-back is absorbed by the runner's 7-day overlap. Seconds are dropped.
    """
    moment = datetime.strptime(since_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime("%Y/%m/%d %H:%M")


def project_jql(project_key: str, since_utc: str, tz: tzinfo) -> str:
    if not _PROJECT_KEY.match(project_key or ""):
        raise ValueError(f"{project_key!r} is not a valid project key.")
    return (
        f'project = "{project_key}" AND updated >= "{jql_date(since_utc, tz)}" '
        "ORDER BY updated ASC, key ASC"
    )
