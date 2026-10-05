"""
Helpers for parsing the SLA-DEADLINE marker left on a task — shared
convention with hermes-team-bots/cron/artifact-sla-sweep.py. See that
file's docstring for the full convention.
"""
from __future__ import annotations

import datetime as dt
import re

SLA_DEADLINE_RE = re.compile(r"SLA-DEADLINE:\s*(\S+)")
DUE_DATE_RE = re.compile(r"DUE-DATE:\s*(\S+)")


def make_deadline_marker(hours: float) -> str:
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    return f"SLA-DEADLINE: {deadline.isoformat().replace('+00:00', 'Z')}"


def make_due_date_marker(due: dt.datetime) -> str:
    return f"DUE-DATE: {due.isoformat().replace('+00:00', 'Z')}"


def find_deadline(task: dict) -> str | None:
    return _find_marker(task, SLA_DEADLINE_RE)


def find_due_date(task: dict) -> str | None:
    return _find_marker(task, DUE_DATE_RE)


def _find_marker(task: dict, pattern: re.Pattern) -> str | None:
    body = task.get("body") or ""
    m = pattern.search(body)
    if m:
        return m.group(1)
    for c in task.get("comments", []) or []:
        m = pattern.search(c.get("text", ""))
        if m:
            return m.group(1)
    return None


def is_overdue(date_str: str, now: dt.datetime | None = None) -> bool:
    """Pure soft check — used for the task 'turns red' visual flag. Never
    triggers an automatic status change (that's only for artifacts, via
    the cron sweep in the sibling hermes-team-bots repo)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        deadline = dt.datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    return now >= deadline


def seconds_remaining(deadline_str: str, now: dt.datetime | None = None) -> float | None:
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        deadline = dt.datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (deadline - now).total_seconds()
