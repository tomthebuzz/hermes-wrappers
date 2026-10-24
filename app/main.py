"""
Team Portal — FastAPI app.

Every route (except /healthz, /login, /login/verify) MUST go through
`require_user()` first. That dependency is the actual security boundary:
it resolves the session cookie -> user key -> RBAC.UserScope, and
every subsequent handler uses that scope to decide what tenants/tasks are
visible. There is no "admin bypass" path in this file on purpose.

UNVERIFIED AGAINST A LIVE INSTALL — see repo README. Run the validation
checklist before trusting this beyond a local smoke test.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import secrets
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from . import config_loader, kanban_read, kanban_write, people
from .auth.magic_link import MagicLinkAuth, MatrixDM
from .auth.matrix_password import PasswordChanger
from .artifacts.sla import (SLA_DEADLINE_RE, deadline_after, find_deadline, find_due_date, is_overdue,
                            make_deadline_marker, parse_ts, seconds_remaining)
from .rbac import RBAC, UserScope

# --- config (env-driven, container-friendly, no hardcoded host paths) ---
KANBAN_DB_PATH = Path(os.environ.get("KANBAN_DB_PATH", "/data/kanban.db"))
KANBAN_ATTACHMENTS_ROOT = Path(os.environ.get("KANBAN_ATTACHMENTS_ROOT", "/data/attachments"))
USERS_YAML_PATH = Path(os.environ.get("USERS_YAML_PATH", "/config/users.yaml"))
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "http://localhost:8080")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if len(SESSION_SECRET) < 16 or SESSION_SECRET == "dev-insecure-change-me":
    # Fail closed: with a known secret anyone can forge a session for any user.
    raise RuntimeError("SESSION_SECRET must be set to a random value (at least 16 characters)")

app = FastAPI(title="Team Portal")
logger = logging.getLogger("team_portal")
if not logger.handlers:   # uvicorn configures only its own loggers; People changes are an audit trail
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class _RedactTokens(logging.Filter):
    """uvicorn's access log would record /login/verify?token=… — a usable
    sign-in until the link is opened."""
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(re.sub(r"token=[^&\s]+", "token=<redacted>", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactTokens())
rbac = RBAC(USERS_YAML_PATH)
PORTAL_AUTH_BACKEND = os.environ.get("PORTAL_AUTH_BACKEND", "magic_link_telegram")
matrix_dm = None
if PORTAL_AUTH_BACKEND == "magic_link_matrix":
    matrix_dm = MatrixDM(os.environ["MATRIX_HOMESERVER"], os.environ["MATRIX_PORTAL_TOKEN"])
password_changer = PasswordChanger(os.environ["MATRIX_HOMESERVER"]) if os.environ.get("MATRIX_HOMESERVER") else None
magic_link = MagicLinkAuth(
    hermes_bin=HERMES_BIN, portal_base_url=PORTAL_BASE_URL,
    bridge_url=os.environ.get("HERMES_BRIDGE_URL"),
    bridge_api_key=os.environ.get("HERMES_BRIDGE_API_KEY"),
    matrix=matrix_dm,
)
signer = URLSafeTimedSerializer(SESSION_SECRET, salt="team-portal-session")

SESSION_COOKIE = "portal_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12h


def require_user(request: Request) -> UserScope:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        user_key = signer.loads(raw, max_age=SESSION_MAX_AGE)
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    scope = rbac.get(user_key)
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


LOGIN_NONCE_COOKIE = "login_nonce"


@app.post("/login")
def login(body: LoginRequest, request: Request):
    """Same answer whether or not the account exists, how it signs in, or
    whether delivery worked: this endpoint must not tell anyone who is
    provisioned. Failures are logged for the operator instead."""
    nonce = request.cookies.get(LOGIN_NONCE_COOKIE) or secrets.token_urlsafe(16)
    scope = rbac.resolve_login(body.login)
    if scope is not None:
        result = magic_link.issue(scope, nonce=nonce)
        if not result.delivered:
            logger.warning("login link for a provisioned user not delivered: %s", result.error[:200])
    response = JSONResponse({"status": "sent", "note": "If this account exists, a login link is on its way (Matrix or Telegram)."})
    response.set_cookie(LOGIN_NONCE_COOKIE, nonce, max_age=900, httponly=True, samesite="lax",
                        secure=PORTAL_BASE_URL.startswith("https://"))
    return response


def _start_session(user_key: str) -> RedirectResponse:
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE, signer.dumps(user_key),
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=PORTAL_BASE_URL.startswith("https://"),
    )
    response.delete_cookie(LOGIN_NONCE_COOKIE)
    return response


@app.get("/login/verify")
def login_verify(token: str, request: Request):
    pending = magic_link.peek(token)
    if pending is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    if pending.nonce and secrets.compare_digest(pending.nonce, request.cookies.get(LOGIN_NONCE_COOKIE, "")):
        return _start_session(magic_link.verify(token))
    # Opened in a browser that did not ask for this link (another device, or a
    # link someone sent you): ask first and show whose account it is, so a
    # forwarded link cannot silently sign you in as someone else.
    scope = rbac.get(pending.user_key)
    name = html.escape(scope.name if scope else "unknown")
    return HTMLResponse(f"""<!doctype html><meta charset="utf-8"><title>Team Portal sign-in</title>
<body style="font:15px system-ui;margin:3rem auto;max-width:28rem">
<h2>Sign in to the Team Portal</h2><p>This link signs you in as <b>{name}</b>.
Only continue if that is you and you asked for this link.</p>
<form method="post" action="/login/verify"><input type="hidden" name="token" value="{html.escape(token)}">
<button type="submit">Continue as {name}</button></form></body>""", headers={"Cache-Control": "no-store"})


@app.post("/login/verify")
def login_verify_confirm(token: str = Form(...)):
    user_key = magic_link.verify(token)
    if user_key is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    return _start_session(user_key)


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
        "telegram_chat_id": user.telegram_chat_id or (str(user.telegram_user_id) if user.telegram_user_id else None),
        "matrix_id": user.matrix_id,
        "tenants": list(user.tenants),
        "can_rollup": user.can_rollup,
        "can_approve_artifacts": list(user.can_approve_artifacts),
        "can_manage_people": user.can_manage_people,
    }


class ProfileUpdateRequest(BaseModel):
    telegram_username: str


@app.patch("/api/profile")
def update_profile(body: ProfileUpdateRequest, user: UserScope = Depends(require_user)):
    if user.telegram_user_id is None:
        raise HTTPException(status_code=409, detail="This account signs in with Matrix; it has no Telegram username")
    username = body.telegram_username.strip().removeprefix("@").lower()
    if not username or len(username) > 32 or not username.replace("_", "").isalnum():
        raise HTTPException(status_code=422, detail="Enter a valid Telegram username without @")
    try:
        data = yaml.safe_load(USERS_YAML_PATH.read_text()) or {}
        entries = data.get("users", [])
        target = next((e for e in entries if str(e.get("telegram_user_id")) == str(user.telegram_user_id)), None)
        if target is None:
            raise HTTPException(status_code=409, detail="User entry is no longer configured")
        for entry in entries:
            existing = str(entry.get("telegram_username", "")).strip().removeprefix("@").lower()
            if existing == username and str(entry.get("telegram_user_id")) != str(user.telegram_user_id):
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


# --- people (Matrix account, tenant rooms, bots, Portal access) ---
#
# Rules, so the page cannot be used to gain or hand out more than one has:
#   * only users with can_manage_people (owners by default) see or use it;
#   * only Matrix accounts on the manager's own server, never owners, never
#     oneself (owners are changed in team.yaml on the host);
#   * tenants given must be ones the manager can read, approval only where
#     the manager may approve; nobody gets can_rollup from here;
#   * a person the manager cannot fully see (tenants outside the manager's
#     reach) cannot be changed or removed by that manager.

LOCALPART_RE = re.compile(r"^[a-z0-9][a-z0-9._=-]{0,63}$")
NAME_RE = re.compile(r'^[^\x00-\x1f\x7f"\\]{1,60}$')
people_log = logging.getLogger("team_portal.people")


def require_people_manager(user: UserScope = Depends(require_user)) -> UserScope:
    if not user.can_manage_people or not user.matrix_id:
        raise HTTPException(status_code=403, detail="Managing people is not part of your role")
    return user


def _server(user: UserScope) -> str:
    return str(user.matrix_id).split(":", 1)[1]


def _grantable(user: UserScope) -> list[str]:
    known = set(kanban_read.distinct_tenants(KANBAN_DB_PATH)) | {t for u in rbac.all() for t in u.tenants}
    return sorted(known if user.can_rollup else set(user.tenants))


def _check_grant(user: UserScope, tenants: list[str], approve: list[str]) -> None:
    grantable = set(_grantable(user))
    if not tenants:
        raise HTTPException(status_code=422, detail="Pick at least one tenant")
    if set(tenants) - grantable:
        raise HTTPException(status_code=403, detail="You can only give tenants you can read")
    if set(approve) - set(tenants):
        raise HTTPException(status_code=422, detail="Approval only for tenants the person can read")
    if set(approve) - set(user.can_approve_artifacts):
        raise HTTPException(status_code=403, detail="You can only give approval where you may approve")


def _target(user: UserScope, localpart: str) -> UserScope:
    if not LOCALPART_RE.fullmatch(localpart):
        raise HTTPException(status_code=422, detail="Invalid user name")
    mxid = f"@{localpart}:{_server(user)}"
    target = next((u for u in rbac.all() if u.matrix_id == mxid), None)
    if target is None:
        raise HTTPException(status_code=404, detail="No such person")
    if target.role == "owner" or target.matrix_id == user.matrix_id:
        raise HTTPException(status_code=403, detail="Owners and your own account are changed by the operator")
    if not user.can_rollup and (set(target.tenants) - set(user.tenants) or target.can_rollup):
        raise HTTPException(status_code=403, detail="This person has access outside your tenants")
    return target


class AddPersonRequest(BaseModel):
    localpart: str
    name: str
    tenants: list[str]
    approve: list[str] = []


class UpdatePersonRequest(BaseModel):
    tenants: list[str]
    approve: list[str] = []


@app.get("/api/people")
def list_people(user: UserScope = Depends(require_people_manager)):
    server = _server(user)
    rows = []
    for u in sorted(rbac.all(), key=lambda u: u.name.lower()):
        if not u.matrix_id or not u.matrix_id.endswith(f":{server}"):
            continue
        editable = u.role != "owner" and u.matrix_id != user.matrix_id and (
            user.can_rollup or not (set(u.tenants) - set(user.tenants) or u.can_rollup))
        rows.append({"name": u.name, "matrix_id": u.matrix_id, "localpart": u.matrix_id[1:].split(":")[0],
                     "role": u.role, "tenants": list(u.tenants), "approve": list(u.can_approve_artifacts),
                     "editable": editable})
    return {"people": rows, "tenants": _grantable(user), "approvable": list(user.can_approve_artifacts),
            "server": server}


@app.post("/api/people")
def add_person(body: AddPersonRequest, user: UserScope = Depends(require_people_manager)):
    localpart = body.localpart.strip().lower()
    if not LOCALPART_RE.fullmatch(localpart) or localpart in ("admin", "portal"):
        raise HTTPException(status_code=422, detail="User name: lowercase letters, digits, . _ = - (no spaces)")
    if not NAME_RE.fullmatch(body.name.strip()):
        raise HTTPException(status_code=422, detail="Name: one line, at most 60 characters, no quotes")
    if any(u.matrix_id == f"@{localpart}:{_server(user)}" for u in rbac.all()):
        raise HTTPException(status_code=409, detail="That user name is taken")
    _check_grant(user, body.tenants, body.approve)
    people_log.info("people: %s adds @%s", user.matrix_id, localpart)
    r = people.add(localpart, body.name.strip(), body.tenants, body.approve)
    if not r.ok:
        raise HTTPException(status_code=502, detail=r.error)
    rbac.reload()
    return {"ok": True, "matrix_id": r.data.get("matrix_id"), "initial_password": r.data.get("initial_password")}


@app.put("/api/people/{localpart}")
def update_person(localpart: str, body: UpdatePersonRequest, user: UserScope = Depends(require_people_manager)):
    _target(user, localpart)
    _check_grant(user, body.tenants, body.approve)
    people_log.info("people: %s sets @%s to %s", user.matrix_id, localpart, ",".join(body.tenants))
    r = people.update(localpart, body.tenants, body.approve)
    if not r.ok:
        raise HTTPException(status_code=502, detail=r.error)
    rbac.reload()
    return {"ok": True}


@app.delete("/api/people/{localpart}")
def remove_person(localpart: str, user: UserScope = Depends(require_people_manager)):
    _target(user, localpart)
    people_log.info("people: %s removes @%s", user.matrix_id, localpart)
    r = people.remove(localpart)
    if not r.ok:
        raise HTTPException(status_code=502, detail=r.error)
    rbac.reload()
    return {"ok": True}


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/profile/password")
def change_password(body: PasswordChangeRequest, user: UserScope = Depends(require_user)):
    """The signed-in person's own Matrix password (see auth/matrix_password.py)."""
    if not user.matrix_id:
        raise HTTPException(status_code=409, detail="This account has no Matrix login")
    if password_changer is None:
        raise HTTPException(status_code=503, detail="Password changes are not configured (MATRIX_HOMESERVER)")
    outcome = password_changer.change(user.matrix_id, body.current_password, body.new_password)
    if not outcome.ok:
        raise HTTPException(status_code=outcome.status, detail=outcome.error)
    logger.info("password changed by %s", user.matrix_id)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    # Auth is enforced client-side by the SPA hitting /api/board and
    # redirecting to the login screen on 401 — this route just serves the
    # static shell. No session data is exposed here.
    # no-store: the whole UI is this one file, so a cached copy keeps running
    # old JS after a deploy (an old native prompt() froze a review click).
    return FileResponse(Path(__file__).parent / "static" / "index.html",
                        headers={"Cache-Control": "no-store"})


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
    task["sla_deadline"] = review_deadline(task) if task.get("status") == "review" else find_deadline(task)
    task["autonomy_level"] = config_loader.autonomy_level(task_skills(task))
    task["due_date"] = find_due_date(task)
    return task


def task_skills(task: dict) -> list:
    try:
        skills = json.loads(task.get("skills") or "[]")
    except ValueError:
        return []
    return [s for s in skills if isinstance(s, str)] if isinstance(skills, list) else []


def auto_approves(task: dict) -> bool:
    """Same rule as hermes-team's SLA sweep: autonomy level >= 3 AND the
    tenant's own on-miss rule is approve (a skill cannot override a tenant
    that rejects)."""
    level = config_loader.autonomy_level(task_skills(task))
    return level is not None and level >= 3 and config_loader.on_miss_direction(task.get("tenant", "")) == "approve"


def review_deadline(task: dict) -> str | None:
    """The SLA-DEADLINE marker the Portal's publish writes, else the default
    SLA counted from the latest review hand-off (workers hand off directly).
    A skill-tagged card at autonomy level >= 3 auto-approves when its veto
    window closes, so that is its deadline (same rule as the SLA sweep)."""
    if auto_approves(task):
        requested_at = kanban_read.latest_event_at(KANBAN_DB_PATH, task["id"], "review_requested")
        return deadline_after(requested_at, config_loader.veto_window_hours()) if requested_at else None
    requested_at = kanban_read.latest_event_at(KANBAN_DB_PATH, task["id"], "review_requested")
    marker = find_deadline(task)
    if marker and parse_ts(marker) is not None:
        if requested_at is None:
            return marker
        floor = deadline_after(requested_at, config_loader.min_sla_hours())
        return marker if parse_ts(marker) >= parse_ts(floor) else floor
    return deadline_after(requested_at, config_loader.default_sla_hours()) if requested_at else None


@app.get("/api/assignees")
def list_assignees(user: UserScope = Depends(require_user)):
    """Department profiles a card can be assigned to; empty when unavailable."""
    result = kanban_write.list_assignees()
    return {"assignees": result}


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
        HERMES_BIN, task_id, file.filename or "upload", data, file.content_type, author=user.name
    )
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True, "detail": result.stdout[:1000]}


INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}


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
    # Inline only for types a browser cannot run as a page from the Portal's
    # origin (an uploaded .html or .svg would otherwise be stored XSS); text
    # previews are served as text/plain. Everything is sandboxed.
    if content_type.startswith("text/"):
        content_type = "text/plain; charset=utf-8"
    previewable = content_type in INLINE_TYPES or content_type.startswith("text/plain")
    disposition = "attachment" if download or not previewable else "inline"
    return FileResponse(candidate, filename=attachment["filename"],
                        media_type=content_type if previewable else "application/octet-stream",
                        content_disposition_type=disposition,
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "sandbox; default-src 'none'"})


class CommentRequest(BaseModel):
    text: str


def reject_reserved_markers(*texts: str | None) -> None:
    """SLA-DEADLINE markers are written only by publish-for-review."""
    if any(t and SLA_DEADLINE_RE.search(t) for t in texts):
        raise HTTPException(status_code=422, detail="SLA-DEADLINE markers are set by 'Publish for review', not by hand")


def check_assignee(assignee: str | None, allow_none: bool = False) -> None:
    """Only installed department profiles (bridge /kanban/assignees): never the
    operator's default profile or an arbitrary string."""
    if assignee in (None, ""):
        return
    if allow_none and assignee == "none":
        return
    if assignee not in kanban_write.list_assignees():
        raise HTTPException(status_code=422, detail=f"Unknown assignee {assignee!r}")


@app.post("/api/tasks/{task_id}/comments")
def add_comment(task_id: str, body: CommentRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail="Not in your scope")
    reject_reserved_markers(body.text)
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
    reject_reserved_markers(body.title, body.body)
    check_assignee(body.assignee)
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
    reject_reserved_markers(body.title, body.body)
    check_assignee(body.assignee, allow_none=True)
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
    if (task.get("status") == "review" or body.status == "archived") and not user.can_approve_tenant(task.get("tenant", "")):
        # Moving a card out of Review rejects it; archiving removes it from view.
        raise HTTPException(status_code=403, detail="Only an artifact reviewer can move a card out of Review or archive it")
    result = kanban_write.transition_task(
        HERMES_BIN, task_id, body.status, body.reason, task.get("status"), author=user.name
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
        deadline = review_deadline(t)
        t["sla_deadline"] = deadline
        t["sla_seconds_remaining"] = seconds_remaining(deadline) if deadline else None
        t["can_review"] = user.can_approve_tenant(t.get("tenant", ""))
        t["autonomy_level"] = config_loader.autonomy_level(task_skills(t))
        t["auto_approves"] = auto_approves(t)
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
    if not config_loader.min_sla_hours() <= hours <= 24 * 30:
        raise HTTPException(status_code=422, detail=f"sla_hours must be between {config_loader.min_sla_hours():g} and 720")
    marker = make_deadline_marker(hours)
    kanban_write.comment_task(HERMES_BIN, body.task_id, marker, author=user.name)
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
        result = kanban_write.approve_artifact(HERMES_BIN, body.task_id, body.note, author=user.name)
    else:
        result = kanban_write.reject_artifact(HERMES_BIN, body.task_id, body.note or "Changes requested.",
                                              author=user.name)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return {"ok": True}
