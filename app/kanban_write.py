"""
All Kanban *writes* go through here. Two modes, chosen automatically by
whether HERMES_BRIDGE_URL is set:

  - Bridge mode (HERMES_BRIDGE_URL set): calls the hermes-bridge service
    over HTTP. This is what Docker/K8s deployments use — the container
    can't exec the host's `hermes` CLI directly, the bridge can.
  - Direct mode (unset): shells out to the local `hermes` CLI directly,
    same as before. Useful for native/dev runs where this process IS on
    the same host as the real Hermes install.

Either way, the never-write-raw-SQL rule holds: every path here ends up
going through kanban_db's real invariants (status transitions, events,
notifications), never a bypassed INSERT/UPDATE.

UNVERIFIED: both the direct CLI flag shapes AND the bridge's own HTTP
contract are best-effort / sandbox-tested-against-a-stub. See repo README.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional

import httpx

BRIDGE_URL = os.environ.get("HERMES_BRIDGE_URL")          # e.g. http://host.docker.internal:8765
BRIDGE_API_KEY = os.environ.get("HERMES_BRIDGE_API_KEY")
BRIDGE_TIMEOUT = float(os.environ.get("HERMES_BRIDGE_TIMEOUT", "30"))


@dataclass
class CLIResult:
    ok: bool
    stdout: str
    stderr: str


def _bridge_call(method: str, path: str, json_body: Optional[dict] = None) -> CLIResult:
    headers = {"X-API-Key": BRIDGE_API_KEY} if BRIDGE_API_KEY else {}
    try:
        resp = httpx.request(method, f"{BRIDGE_URL}{path}", json=json_body, headers=headers, timeout=BRIDGE_TIMEOUT)
    except httpx.HTTPError as e:
        return CLIResult(ok=False, stdout="", stderr=f"bridge request failed: {e}")
    if resp.status_code >= 300:
        return CLIResult(ok=False, stdout="", stderr=resp.text)
    return CLIResult(ok=True, stdout=resp.text, stderr="")


def _run(hermes_bin: str, *args: str) -> CLIResult:
    cmd = [hermes_bin, "kanban", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    return CLIResult(ok=result.returncode == 0, stdout=result.stdout, stderr=result.stderr)


def create_task(hermes_bin: str, title: str, tenant: str, body: str = "",
                 assignee: Optional[str] = None) -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("POST", "/kanban/tasks",
                             {"title": title, "tenant": tenant, "body": body, "assignee": assignee})
    args = ["create", title, "--tenant", tenant, "--body", body, "--json"]
    if assignee:
        args += ["--assignee", assignee]
    return _run(hermes_bin, *args)


def claim_task(hermes_bin: str, task_id: str) -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("POST", f"/kanban/tasks/{task_id}/claim")
    return _run(hermes_bin, "claim", task_id)


def assign_task(hermes_bin: str, task_id: str, assignee: str) -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("POST", f"/kanban/tasks/{task_id}/assign", {"assignee": assignee})
    return _run(hermes_bin, "assign", task_id, assignee)


def comment_task(hermes_bin: str, task_id: str, text: str, author: Optional[str] = None) -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("POST", f"/kanban/tasks/{task_id}/comments", {"text": text, "author": author})
    args = ["comment", task_id, text]
    if author:
        args += ["--author", author]
    return _run(hermes_bin, *args)


def approve_artifact(hermes_bin: str, task_id: str, note: str = "") -> CLIResult:
    """Approve == complete the review-lane card."""
    if BRIDGE_URL:
        return _bridge_call("POST", f"/kanban/tasks/{task_id}/approve", {"note": note})
    args = ["complete", task_id]
    if note:
        args += ["--result", note]
    return _run(hermes_bin, *args)


def reject_artifact(hermes_bin: str, task_id: str, reason: str) -> CLIResult:
    """Reject == request-changes, sending it back to the publisher."""
    if BRIDGE_URL:
        return _bridge_call("POST", f"/kanban/tasks/{task_id}/reject", {"reason": reason})
    return _run(hermes_bin, "request-changes", task_id, reason)


def publish_artifact_for_review(hermes_bin: str, task_id: str, summary: str = "") -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("POST", f"/kanban/tasks/{task_id}/publish-for-review", {"summary": summary})
    args = ["request-review", task_id]
    if summary:
        args += ["--summary", summary]
    return _run(hermes_bin, *args)
