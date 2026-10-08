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
import tempfile
from dataclasses import dataclass
from pathlib import Path
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
        try:
            detail = resp.json().get("detail", resp.text)
            if isinstance(detail, dict):
                detail = detail.get("detail", detail)
        except (ValueError, AttributeError):
            detail = resp.text
        return CLIResult(ok=False, stdout="", stderr=str(detail))
    try:
        payload = resp.json()
        detail = payload.get("detail", resp.text) if isinstance(payload, dict) else resp.text
    except (ValueError, AttributeError):
        detail = resp.text
    return CLIResult(ok=True, stdout=str(detail), stderr="")


def _run(hermes_bin: str, *args: str) -> CLIResult:
    cmd = [hermes_bin, "kanban", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
    return CLIResult(ok=result.returncode == 0, stdout=result.stdout, stderr=result.stderr)


def create_task(hermes_bin: str, title: str, tenant: str, body: str = "",
                 assignee: Optional[str] = None, status: str = "running",
                 priority: int = 0) -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("POST", "/kanban/tasks",
                             {"title": title, "tenant": tenant, "body": body,
                              "assignee": assignee, "status": status, "priority": priority})
    initial = "blocked" if status in {"todo", "ready"} else "running"
    args = ["create", title, "--tenant", tenant, "--body", body,
            "--initial-status", initial, "--priority", str(priority), "--json"]
    if status == "triage":
        args = ["create", title, "--tenant", tenant, "--body", body,
                "--triage", "--priority", str(priority), "--json"]
    if assignee:
        args += ["--assignee", assignee]
    return _run(hermes_bin, *args)


def upload_attachment(hermes_bin: str, task_id: str, filename: str,
                      data: bytes, content_type: str | None = None) -> CLIResult:
    safe_name = Path(filename).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        return CLIResult(False, "", "invalid filename")
    if BRIDGE_URL:
        headers = {"X-API-Key": BRIDGE_API_KEY} if BRIDGE_API_KEY else {}
        try:
            response = httpx.post(
                f"{BRIDGE_URL}/kanban/tasks/{task_id}/attachments",
                files={"file": (safe_name, data, content_type or "application/octet-stream")},
                headers=headers,
                timeout=60,
            )
        except httpx.HTTPError as e:
            return CLIResult(False, "", f"bridge upload failed: {e}")
        if response.status_code >= 300:
            return CLIResult(False, "", response.text)
        return CLIResult(True, response.text, "")
    with tempfile.TemporaryDirectory(prefix="portal-attachment-") as tmp:
        path = Path(tmp) / safe_name
        path.write_bytes(data)
        return _run(hermes_bin, "attach", task_id, str(path))


def edit_task(hermes_bin: str, task_id: str, title: str | None = None,
              body: str | None = None, priority: int | None = None) -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("PATCH", f"/kanban/tasks/{task_id}",
                            {"title": title, "body": body, "priority": priority})
    args = ["edit", task_id]
    if title is not None: args += ["--title", title]
    if body is not None: args += ["--body", body]
    if priority is not None: args += ["--priority", str(priority)]
    return _run(hermes_bin, *args)


def transition_task(hermes_bin: str, task_id: str, status: str,
                    reason: str = "Moved from Team Portal",
                    current_status: str | None = None) -> CLIResult:
    if BRIDGE_URL:
        return _bridge_call("POST", f"/kanban/tasks/{task_id}/transition",
                            {"status": status, "reason": reason, "current_status": current_status})
    if current_status == status:
        return CLIResult(True, f"Task {task_id} is already {status}", "")
    if status == "running" and current_status == "review":
        reopened = _run(hermes_bin, "reopen-review", task_id, "--reason", reason)
        return _run(hermes_bin, "claim", task_id) if reopened.ok else reopened
    if status == "running" and current_status in {"todo", "blocked"}:
        promoted = _run(hermes_bin, "promote", task_id)
        return _run(hermes_bin, "claim", task_id) if promoted.ok else promoted
    if status == "running" and current_status == "ready":
        return _run(hermes_bin, "claim", task_id)
    if status == "ready" and current_status == "running":
        return _run(hermes_bin, "reclaim", task_id, "--reason", reason)
    if status == "ready" and current_status == "review":
        return _run(hermes_bin, "reopen-review", task_id, "--reason", reason)
    if status == "ready" and current_status in {"todo", "blocked"}:
        return _run(hermes_bin, "promote", task_id, reason)
    if status == "todo" and current_status == "review":
        return _run(hermes_bin, "reopen-review", task_id, "--reason", reason)
    if status == "todo" and current_status == "blocked":
        return _run(hermes_bin, "unblock", task_id, "--reason", reason)
    if status == "todo" and current_status == "running":
        return _run(hermes_bin, "reclaim", task_id, "--reason", reason)
    if status == "blocked" and current_status in {"running", "ready"}:
        return _run(hermes_bin, "block", task_id, reason)
    if status == "review" and current_status in {"running", "ready"}:
        return _run(hermes_bin, "request-review", task_id, "--summary", reason)
    if status == "done" and current_status in {"running", "ready", "review"}:
        return _run(hermes_bin, "complete", task_id, "--result", "Completed from Team Portal")
    if status == "archived":
        return _run(hermes_bin, "archive", task_id)
    return CLIResult(False, "", f"Cannot move {task_id} from {current_status or 'unknown'} to {status} using a supported Hermes transition.")


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
