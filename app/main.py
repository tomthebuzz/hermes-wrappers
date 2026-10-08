"""
Team Portal — FastAPI app.

Every route (except /healthz, /login, /login/verify) MUST go through
`require_user()` first. That dependency is the actual security boundary:
it resolves the session cookie -> telegram_user_id -> RBAC.UserScope, and
every subsequent handler uses that scope to decide what tenants/tasks are
visible. There is no "admin bypass" path in this file on purpose.

UNVERIFIED AGAINST A LIVE INSTALL — see repo README. Run the validation
checklist before trusting this beyond a local smoke test.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from . import config_loader, kanban_read, kanban_write
from .auth.magic_link import MagicLinkAuth
from .artifacts.sla import find_deadline, find_due_date, is_overdue, make_deadline_marker, seconds_remaining
from .rbac import RBAC, UserScope

# --- config (env-driven, container-friendly, no hardcoded host paths) ---
KANBAN_DB_PATH = Path(os.environ.get("KANBAN_DB_PATH", "/data/kanban.db"))
KANBAN_ATTACHMENTS_ROOT = Path(os.environ.get("KANBAN_ATTACHMENTS_ROOT", "/data/attachments"))
USERS_YAML_PATH = Path(os.environ.get("USERS_YAML_PATH", "/config/users.yaml"))
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "http://localhost:8080")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-change-me")

app = FastAPI(title="Team Portal")
rbac = RBAC(USERS_YAML_PATH)
magic_link = MagicLinkAuth(
    hermes_bin=HERMES_BIN, portal_base_url=PORTAL_BASE_URL,
    bridge_url=os.environ.get("HERMES_BRIDGE_URL"),
    bridge_api_key=os.environ.get("HERMES_BRIDGE_API_KEY"),
)
signer = URLSafeTimedSerializer(SESSION_SECRET, salt="team-portal-session")

SESSION_COOKIE = "portal_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12h


def require_user(request: Request) -> UserScope:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        telegram_user_id = signer.loads(raw, max_age=SESSION_MAX_AGE)
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    scope = rbac.get(int(telegram_user_id))
    if scope is None:
        # Fail closed: a valid session for an unknown/removed user gets nothing.
        raise HTTPException(status_code=403, detail="No access configured for this user")
    return scope


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


# --- auth ---

class LoginRequest(BaseModel):
    login: str


@app.post("/login")
def login(body: LoginRequest):
    scope = rbac.resolve_login(body.login)
    if scope is None:
        # Deliberately vague error — don't let this endpoint be used to
        # enumerate which Telegram handles/IDs are provisioned.
        raise HTTPException(status_code=400, detail="Could not send login link")
    result = magic_link.issue(scope.telegram_user_id, scope.delivery_target)
    if not result.delivered:
        raise HTTPException(status_code=502, detail=f"Could not deliver Telegram login link: {result.error}")
    return {"status": "sent", "note": "Check Telegram for a login link."}


@app.get("/login/verify")
def login_verify(token: str):
    telegram_user_id = magic_link.verify(token)
    if telegram_user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    session_value = signer.dumps(telegram_user_id)
    response = RedirectResponse(url="/")
    response.set_cookie(
        SESSION_COOKIE, session_value,
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=PORTAL_BASE_URL.startswith("https://"),
    )
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/api/profile")
def profile(user: UserScope = Depends(require_user)):
    return {
        "name": user.name,
        "role": user.role,
        "telegram_username": user.telegram_username,
        "telegram_user_id": user.telegram_user_id,
        "telegram_chat_id": user.telegram_chat_id or str(user.telegram_user_id),
        "tenants": list(user.tenants),
        "can_rollup": user.can_rollup,
        "can_approve_artifacts": list(user.can_approve_artifacts),
    }


class ProfileUpdateRequest(BaseModel):
    telegram_username: str


@app.patch("/api/profile")
def update_profile(body: ProfileUpdateRequest, user: UserScope = Depends(require_user)):
    username = body.telegram_username.strip().removeprefix("@").lower()
    if not username or len(username) > 32 or not username.replace("_", "").isalnum():
        raise HTTPException(status_code=422, detail="Enter a valid Telegram username without @")
    try:
        data = yaml.safe_load(USERS_YAML_PATH.read_text()) or {}
        entries = data.get("users", [])
        target = next((e for e in entries if int(e.get("telegram_user_id", -1)) == user.telegram_user_id), None)
        if target is None:
            raise HTTPException(status_code=409, detail="User entry is no longer configured")
        for entry in entries:
            existing = str(entry.get("telegram_username", "")).strip().removeprefix("@").lower()
            if existing == username and int(entry.get("telegram_user_id", -1)) != user.telegram_user_id:
                raise HTTPException(status_code=409, detail="That Telegram username is already assigned")
        target["telegram_username"] = username
        # users.yaml is mounted as a single writable Docker file. Replace its
        # contents in-place (os.replace would replace the container mountpoint,
        # not the host file); serialize first so YAML errors cannot truncate it.
        USERS_YAML_PATH.write_text(yaml.safe_dump(data, sort_keys=False))
        rbac.reload()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not save profile; check users.yaml mount permissions: {e}")
    return {"ok": True, "telegram_username": username}


@app.get("/", response_class=HTMLResponse)
def index():
    # Auth is enforced client-side by the SPA hitting /api/board and
    # redirecting to the login screen on 401 — this route just serves the
    # static shell. No session data is exposed here.
    return FileResponse(Path(__file__).parent / "static" / "index.html")


# --- kanban (read) ---

@app.get("/api/board")
def board(user: UserScope = Depends(require_user)):
    all_tenants = kanban_read.distinct_tenants(KANBAN_DB_PATH)
    tenants = user.readable_tenants(all_tenants)
    tasks = kanban_read.list_tasks(KANBAN_DB_PATH, tenants=tenants)
    for t in tasks:
        t["comments"] = kanban_read.list_comments(KANBAN_DB_PATH, t["id"])
        due = find_due_date(t)
        t["due_date"] = due
        t["overdue"] = is_overdue(due) if due else False
    return {"tenants": tenants, "tasks": tasks}


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    task["comments"] = kanban_read.list_comments(KANBAN_DB_PATH, task_id)
    task["attachments"] = kanban_read.list_attachments(KANBAN_DB_PATH, task_id)
    task["can_review"] = user.can_approve_tenant(task.get("tenant", ""))
    task["sla_deadline"] = find_deadline(task)
    task["due_date"] = find_due_date(task)
    return task


@app.post("/api/tasks/{task_id}/attachments")
async def upload_task_attachment(task_id: str, file: UploadFile = File(...), user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Attachment exceeds the 25 MB limit")
    if not data:
        raise HTTPException(status_code=400, detail="Empty files cannot be attached")
    result = kanban_write.upload_attachment(
        HERMES_BIN, task_id, file.filename or "upload", data, file.content_type
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True, "detail": result.stdout[:1000]}


@app.get("/api/attachments/{attachment_id}")
def download_task_attachment(
    attachment_id: int, download: bool = Query(False), user: UserScope = Depends(require_user)
):
    attachment = kanban_read.get_attachment(KANBAN_DB_PATH, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    task = kanban_read.get_task(KANBAN_DB_PATH, attachment["task_id"])
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=404, detail="Attachment not found")
    name = Path(attachment["stored_path"]).name
    candidate = (KANBAN_ATTACHMENTS_ROOT / attachment["task_id"] / name).resolve()
    try:
        candidate.relative_to(KANBAN_ATTACHMENTS_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail="Attachment unavailable")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Attachment file is not mounted in the portal")
    content_type = attachment.get("content_type") or "application/octet-stream"
    previewable = content_type == "application/pdf" or content_type.startswith(("image/", "text/"))
    disposition = "attachment" if download or not previewable else "inline"
    return FileResponse(candidate, filename=attachment["filename"],
                        media_type=content_type, content_disposition_type=disposition)


class CommentRequest(BaseModel):
    text: str


@app.post("/api/tasks/{task_id}/comments")
def add_comment(task_id: str, body: CommentRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    result = kanban_write.comment_task(HERMES_BIN, task_id, body.text, author=user.name)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}


# --- kanban (write) ---

class CreateTaskRequest(BaseModel):
    title: str
    tenant: str
    body: str = ""
    assignee: str | None = None
    status: str = "running"
    priority: int = 0


@app.post("/api/tasks")
def create_task(body: CreateTaskRequest, user: UserScope = Depends(require_user)):
    if not user.can_read_tenant(body.tenant):
        raise HTTPException(status_code=403, detail="Not in your scope")
    allowed_statuses = {"triage", "todo", "ready", "running", "review", "blocked", "done", "archived"}
    if body.status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Unsupported initial status")
    if body.status in {"done", "archived"} and not user.can_approve_tenant(body.tenant):
        raise HTTPException(status_code=403, detail="Review permission is required for this initial status")
    result = kanban_write.create_task(HERMES_BIN, body.title, body.tenant, body.body,
                                      body.assignee, body.status, body.priority)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}


class EditTaskRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    priority: int | None = None
    assignee: str | None = None


@app.patch("/api/tasks/{task_id}")
def edit_task(task_id: str, body: EditTaskRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    if body.title is None and body.body is None and body.priority is None and body.assignee is None:
        raise HTTPException(status_code=422, detail="At least one editable field is required")
    if body.title is not None or body.body is not None or body.priority is not None:
        result = kanban_write.edit_task(HERMES_BIN, task_id, body.title, body.body, body.priority)
        if not result.ok:
            raise HTTPException(status_code=502, detail=result.stderr[:500])
    if body.assignee is not None:
        result = kanban_write.assign_task(HERMES_BIN, task_id, body.assignee)
        if not result.ok:
            raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}


class TransitionTaskRequest(BaseModel):
    status: str
    reason: str = "Moved from Team Portal"


@app.post("/api/tasks/{task_id}/transition")
def transition_task(task_id: str, body: TransitionTaskRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    allowed_statuses = {"todo", "ready", "running", "review", "blocked", "done", "archived"}
    if body.status not in allowed_statuses:
        raise HTTPException(status_code=422, detail=f"Unsupported board transition: {body.status}")
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    if body.status == "done" and not user.can_approve_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Only an artifact reviewer can complete this task")
    result = kanban_write.transition_task(
        HERMES_BIN, task_id, body.status, body.reason, task.get("status")
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True, "detail": result.stdout[:1000]}


@app.post("/api/tasks/{task_id}/claim")
def claim_task(task_id: str, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    if task.get("status") != "ready":
        raise HTTPException(status_code=409, detail=f"Only Ready tasks can be claimed; this task is {task.get('status')}. Move it to Ready first.")
    result = kanban_write.claim_task(HERMES_BIN, task_id)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}


# --- artifacts (Phase 2) ---

@app.get("/api/artifacts")
def artifact_review_queue(user: UserScope = Depends(require_user)):
    """Review queue: tasks in 'review' status across whatever tenants this
    user can read, enriched with the SLA deadline/overdue flag so the UI
    can show a countdown without a second round-trip per card."""
    all_tenants = kanban_read.distinct_tenants(KANBAN_DB_PATH)
    tenants = user.readable_tenants(all_tenants)
    tasks = kanban_read.list_tasks(KANBAN_DB_PATH, tenants=tenants, status="review")
    for t in tasks:
        t["comments"] = kanban_read.list_comments(KANBAN_DB_PATH, t["id"])
        deadline = find_deadline(t)
        t["sla_deadline"] = deadline
        t["sla_seconds_remaining"] = seconds_remaining(deadline) if deadline else None
        t["can_review"] = user.can_approve_tenant(t.get("tenant", ""))
    return {"tasks": tasks}


class PublishArtifactRequest(BaseModel):
    task_id: str
    sla_hours: float | None = None   # None -> use config_loader.default_sla_hours()
    summary: str = ""


@app.post("/api/artifacts/publish")
def publish_artifact(body: PublishArtifactRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, body.task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    hours = body.sla_hours if body.sla_hours is not None else config_loader.default_sla_hours()
    marker = make_deadline_marker(hours)
    kanban_write.comment_task(HERMES_BIN, body.task_id, marker)
    result = kanban_write.publish_artifact_for_review(HERMES_BIN, body.task_id, body.summary)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True, "deadline_marker": marker, "sla_hours": hours}


class ReviewDecisionRequest(BaseModel):
    task_id: str
    approve: bool
    note: str = ""


@app.post("/api/artifacts/review")
def review_artifact(body: ReviewDecisionRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, body.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    tenant = task.get("tenant", "")
    if not user.can_approve_tenant(tenant):
        raise HTTPException(status_code=403, detail="Not authorized to review this tenant's artifacts")
    if body.approve:
        result = kanban_write.approve_artifact(HERMES_BIN, body.task_id, body.note)
    else:
        result = kanban_write.reject_artifact(HERMES_BIN, body.task_id, body.note or "Changes requested.")
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}
