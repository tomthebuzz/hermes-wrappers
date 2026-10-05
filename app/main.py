"""
FutureTree Team Portal — FastAPI app.

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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from . import kanban_read, kanban_write
from .auth.magic_link import MagicLinkAuth
from .artifacts.sla import make_deadline_marker
from .rbac import RBAC, UserScope

# --- config (env-driven, container-friendly, no hardcoded host paths) ---
KANBAN_DB_PATH = Path(os.environ.get("KANBAN_DB_PATH", "/data/kanban.db"))
USERS_YAML_PATH = Path(os.environ.get("USERS_YAML_PATH", "/config/users.yaml"))
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "http://localhost:8080")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-insecure-change-me")

app = FastAPI(title="FutureTree Team Portal")
rbac = RBAC(USERS_YAML_PATH)
magic_link = MagicLinkAuth(hermes_bin=HERMES_BIN, portal_base_url=PORTAL_BASE_URL)
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


# --- auth ---

class LoginRequest(BaseModel):
    telegram_user_id: int


@app.post("/login")
def login(body: LoginRequest):
    if rbac.get(body.telegram_user_id) is None:
        # Deliberately vague error — don't let this endpoint be used to
        # enumerate which Telegram IDs are provisioned.
        raise HTTPException(status_code=400, detail="Could not send login link")
    magic_link.issue(body.telegram_user_id)
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


@app.get("/", response_class=HTMLResponse)
def index(user: UserScope = Depends(require_user)):
    return f"<h1>FutureTree Team Portal</h1><p>Signed in as {user.name} ({user.role})</p>"


# --- kanban (read) ---

@app.get("/api/board")
def board(user: UserScope = Depends(require_user)):
    all_tenants = kanban_read.distinct_tenants(KANBAN_DB_PATH)
    tenants = user.readable_tenants(all_tenants)
    tasks = kanban_read.list_tasks(KANBAN_DB_PATH, tenants=tenants)
    return {"tenants": tenants, "tasks": tasks}


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    task["comments"] = kanban_read.list_comments(KANBAN_DB_PATH, task_id)
    return task


# --- kanban (write) ---

class CreateTaskRequest(BaseModel):
    title: str
    tenant: str
    body: str = ""
    assignee: str | None = None


@app.post("/api/tasks")
def create_task(body: CreateTaskRequest, user: UserScope = Depends(require_user)):
    if not user.can_read_tenant(body.tenant):
        raise HTTPException(status_code=403, detail="Not in your scope")
    result = kanban_write.create_task(HERMES_BIN, body.title, body.tenant, body.body, body.assignee)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}


@app.post("/api/tasks/{task_id}/claim")
def claim_task(task_id: str, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    result = kanban_write.claim_task(HERMES_BIN, task_id)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}


# --- artifacts (Phase 2 surface, scaffolded now) ---

class PublishArtifactRequest(BaseModel):
    task_id: str
    sla_hours: float = 48.0
    summary: str = ""


@app.post("/api/artifacts/publish")
def publish_artifact(body: PublishArtifactRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, body.task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    marker = make_deadline_marker(body.sla_hours)
    kanban_write.comment_task(HERMES_BIN, body.task_id, marker)
    result = kanban_write.publish_artifact_for_review(HERMES_BIN, body.task_id, body.summary)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True, "deadline_marker": marker}


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
