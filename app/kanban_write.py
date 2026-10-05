"""
All Kanban *writes* go through the `hermes kanban` CLI, never raw SQL —
this is the one rule that keeps the portal from corrupting kanban_db's
invariants (status transitions, task_events logging, dispatcher
notifications, review state machine). Slower than a direct UPDATE, correct
by construction instead of by hoping we reimplemented the state machine
right.

UNVERIFIED: flag names taken from the Hermes Kanban CLI reference docs as
of 2026-10-05. Run each wrapped command by hand once against a real
install before trusting this in the portal's write paths.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class CLIResult:
    ok: bool
    stdout: str
    stderr: str


def _run(hermes_bin: str, *args: str) -> CLIResult:
    cmd = [hermes_bin, "kanban", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    return CLIResult(ok=result.returncode == 0, stdout=result.stdout, stderr=result.stderr)


def create_task(hermes_bin: str, title: str, tenant: str, body: str = "",
                 assignee: Optional[str] = None) -> CLIResult:
    args = ["create", title, "--tenant", tenant, "--body", body, "--json"]
    if assignee:
        args += ["--assignee", assignee]
    return _run(hermes_bin, *args)


def claim_task(hermes_bin: str, task_id: str) -> CLIResult:
    return _run(hermes_bin, "claim", task_id)


def assign_task(hermes_bin: str, task_id: str, assignee: str) -> CLIResult:
    return _run(hermes_bin, "assign", task_id, assignee)


def comment_task(hermes_bin: str, task_id: str, text: str, author: Optional[str] = None) -> CLIResult:
    args = ["comment", task_id, text]
    if author:
        args += ["--author", author]
    return _run(hermes_bin, *args)


def approve_artifact(hermes_bin: str, task_id: str, note: str = "") -> CLIResult:
    """Approve == complete the review-lane card."""
    args = ["complete", task_id]
    if note:
        args += ["--result", note]
    return _run(hermes_bin, *args)


def reject_artifact(hermes_bin: str, task_id: str, reason: str) -> CLIResult:
    """Reject == request-changes, sending it back to the publisher."""
    return _run(hermes_bin, "request-changes", task_id, reason)


def publish_artifact_for_review(hermes_bin: str, task_id: str, summary: str = "") -> CLIResult:
    args = ["request-review", task_id]
    if summary:
        args += ["--summary", summary]
    return _run(hermes_bin, *args)
