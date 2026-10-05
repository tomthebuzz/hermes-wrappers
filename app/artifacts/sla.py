"""
Shared SLA-deadline convention between the Team Portal (publish step) and
the hermes-team-bots cron sweep (auto-resolve step). Keeping this logic in
one small module and documenting the convention here so the two repos don't
silently drift on the marker format.

Convention: a structured line in the task body or a comment:
    SLA-DEADLINE: 2026-10-07T12:00:00Z

Default duration is 48h, overridable per-artifact at publish time (per
spec). Default direction on miss (approve/reject) is a per-tenant setting —
see DEFAULT_DIRECTION in hermes-team-bots/cron/artifact-sla-sweep.py. This
module intentionally does NOT duplicate that dict; Phase 2 should move both
into a shared config source (e.g. a small config.yaml both repos read) once
the two repos are deployed together, rather than hand-syncing two Python
dicts forever.
"""
from __future__ import annotations

import datetime as dt

DEFAULT_SLA_HOURS = 48


def make_deadline_marker(hours: float = DEFAULT_SLA_HOURS) -> str:
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    return f"SLA-DEADLINE: {deadline.isoformat().replace('+00:00', 'Z')}"
