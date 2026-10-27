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

import markdown
import yaml
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from . import config_loader, i18n, kanban_read, kanban_write, people, team_read, team_write
from .auth.magic_link import MagicLinkAuth, MatrixDM
from .i18n import t
from .auth.matrix_password import PasswordChanger
from .artifacts.sla import (SLA_DEADLINE_RE, deadline_after, find_deadline, find_due_date, is_overdue,
                            make_deadline_marker, parse_ts, seconds_remaining)
from .rbac import RBAC, UserScope

# --- config (env-driven, container-friendly, no hardcoded host paths) ---
KANBAN_DB_PATH = Path(os.environ.get("KANBAN_DB_PATH", "/data/kanban.db"))
KANBAN_ATTACHMENTS_ROOT = Path(os.environ.get("KANBAN_ATTACHMENTS_ROOT", "/data/attachments"))
TEAM_DB_PATH = Path(os.environ.get("TEAM_DB_PATH", "/team/ontology.db"))   # the team store, read-only (dashboard)
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
        raise HTTPException(status_code=401, detail=t("err.not_logged_in"))
    try:
        user_key = signer.loads(raw, max_age=SESSION_MAX_AGE)
    except BadSignature:
        raise HTTPException(status_code=401, detail=t("err.session_expired"))
    scope = rbac.get(user_key)
    if scope is None:
        # Fail closed: a valid session for an unknown/removed user gets nothing.
        raise HTTPException(status_code=403, detail=t("err.no_access"))
    return scope


def _session_language(raw_cookie: str | None) -> str | None:
    """The signed-in person's users.yaml language, if the session cookie is valid."""
    if not raw_cookie:
        return None
    try:
        scope = rbac.get(signer.loads(raw_cookie, max_age=SESSION_MAX_AGE))
    except BadSignature:
        return None
    return scope.language if scope else None


class LanguageMiddleware:
    """Chooses the request's language before anything else runs (see i18n.py).
    Pure ASGI and set on the request's own task: route handlers and
    dependencies run in thread-pool copies of this context, so a value set
    inside one of them would not reach the others."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            from starlette.requests import Request as _Request
            req = _Request(scope)
            i18n.use(i18n.pick(query=req.query_params.get("lang"), cookie=req.cookies.get(i18n.COOKIE),
                               user_lang=_session_language(req.cookies.get(SESSION_COOKIE)),
                               accept=req.headers.get("accept-language")))
        await self.app(scope, receive, send)


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.add_middleware(LanguageMiddleware)


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
    response = JSONResponse({"status": "sent", "note": t("login.note")})
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
        raise HTTPException(status_code=400, detail=t("err.token_invalid"))
    if pending.nonce and secrets.compare_digest(pending.nonce, request.cookies.get(LOGIN_NONCE_COOKIE, "")):
        return _start_session(magic_link.verify(token))
    # Opened in a browser that did not ask for this link (another device, or a
    # link someone sent you): ask first and show whose account it is, so a
    # forwarded link cannot silently sign you in as someone else.
    scope = rbac.get(pending.user_key)
    name = html.escape(scope.name if scope else "unknown")
    # No session yet: the pending person's own language, unless the browser chose one.
    if scope and scope.language and not request.query_params.get("lang") and not request.cookies.get(i18n.COOKIE):
        i18n.use(scope.language)
    return HTMLResponse(f"""<!doctype html><html lang="{i18n.current()}"><meta charset="utf-8"><title>{t("verify.title")}</title>
<body style="font:15px system-ui;margin:3rem auto;max-width:28rem">
<h2>{t("verify.heading")}</h2><p>{t("verify.text", name=f"<b>{name}</b>")}</p>
<form method="post" action="/login/verify"><input type="hidden" name="token" value="{html.escape(token)}">
<button type="submit">{t("verify.button", name=name)}</button></form></body></html>""", headers={"Cache-Control": "no-store"})


@app.post("/login/verify")
def login_verify_confirm(token: str = Form(...)):
    user_key = magic_link.verify(token)
    if user_key is None:
        raise HTTPException(status_code=400, detail=t("err.token_invalid"))
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
        "language": user.language,          # from users.yaml (the owner or the person set it); None = not set
        "languages": list(i18n.SUPPORTED),
    }


class ProfileUpdateRequest(BaseModel):
    telegram_username: str


@app.patch("/api/profile")
def update_profile(body: ProfileUpdateRequest, user: UserScope = Depends(require_user)):
    if user.telegram_user_id is None:
        raise HTTPException(status_code=409, detail=t("err.no_telegram_username"))
    username = body.telegram_username.strip().removeprefix("@").lower()
    if not username or len(username) > 32 or not username.replace("_", "").isalnum():
        raise HTTPException(status_code=422, detail=t("err.telegram_username_invalid"))
    try:
        data = yaml.safe_load(USERS_YAML_PATH.read_text()) or {}
        entries = data.get("users", [])
        target = next((e for e in entries if str(e.get("telegram_user_id")) == str(user.telegram_user_id)), None)
        if target is None:
            raise HTTPException(status_code=409, detail=t("err.user_entry_gone"))
        for entry in entries:
            existing = str(entry.get("telegram_username", "")).strip().removeprefix("@").lower()
            if existing == username and str(entry.get("telegram_user_id")) != str(user.telegram_user_id):
                raise HTTPException(status_code=409, detail=t("err.telegram_username_taken"))
        target["telegram_username"] = username
        # users.yaml is mounted as a single writable Docker file. Replace its
        # contents in-place (os.replace would replace the container mountpoint,
        # not the host file); serialize first so YAML errors cannot truncate it.
        USERS_YAML_PATH.write_text(yaml.safe_dump(data, sort_keys=False))
        rbac.reload()
    except OSError as e:
        raise HTTPException(status_code=500, detail=t("err.profile_save", error=str(e)))
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
        raise HTTPException(status_code=403, detail=t("err.people_role"))
    return user


def _server(user: UserScope) -> str:
    return str(user.matrix_id).split(":", 1)[1]


def _grantable(user: UserScope) -> list[str]:
    known = set(kanban_read.distinct_tenants(KANBAN_DB_PATH)) | {t for u in rbac.all() for t in u.tenants}
    return sorted(known if user.can_rollup else set(user.tenants))


def _check_grant(user: UserScope, tenants: list[str], approve: list[str]) -> None:
    grantable = set(_grantable(user))
    if not tenants:
        raise HTTPException(status_code=422, detail=t("err.pick_tenant"))
    if set(tenants) - grantable:
        raise HTTPException(status_code=403, detail=t("err.grant_tenants"))
    if set(approve) - set(tenants):
        raise HTTPException(status_code=422, detail=t("err.approve_subset"))
    if set(approve) - set(user.can_approve_artifacts):
        raise HTTPException(status_code=403, detail=t("err.grant_approval"))


def _target(user: UserScope, localpart: str) -> UserScope:
    if not LOCALPART_RE.fullmatch(localpart):
        raise HTTPException(status_code=422, detail=t("err.username_invalid"))
    mxid = f"@{localpart}:{_server(user)}"
    target = next((u for u in rbac.all() if u.matrix_id == mxid), None)
    if target is None:
        raise HTTPException(status_code=404, detail=t("err.no_such_person"))
    if target.role == "owner" or target.matrix_id == user.matrix_id:
        raise HTTPException(status_code=403, detail=t("err.owner_or_self"))
    if not user.can_rollup and (set(target.tenants) - set(user.tenants) or target.can_rollup):
        raise HTTPException(status_code=403, detail=t("err.outside_tenants"))
    return target


class AddPersonRequest(BaseModel):
    localpart: str
    name: str
    tenants: list[str]
    approve: list[str] = []
    language: str | None = None


class UpdatePersonRequest(BaseModel):
    tenants: list[str]
    approve: list[str] = []
    language: str | None = None


def _language_arg(code: str | None) -> str | None:
    if code is None or code == "":
        return None
    lang = i18n.normalize(code)
    if lang is None:
        raise HTTPException(status_code=422, detail=t("err.language", languages=", ".join(i18n.SUPPORTED)))
    return lang


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
                     "language": u.language, "editable": editable})
    return {"people": rows, "tenants": _grantable(user), "approvable": list(user.can_approve_artifacts),
            "server": server}


@app.post("/api/people")
def add_person(body: AddPersonRequest, user: UserScope = Depends(require_people_manager)):
    localpart = body.localpart.strip().lower()
    if not LOCALPART_RE.fullmatch(localpart) or localpart in ("admin", "portal"):
        raise HTTPException(status_code=422, detail=t("err.localpart_format"))
    if not NAME_RE.fullmatch(body.name.strip()):
        raise HTTPException(status_code=422, detail=t("err.name_format"))
    if any(u.matrix_id == f"@{localpart}:{_server(user)}" for u in rbac.all()):
        raise HTTPException(status_code=409, detail=t("err.username_taken"))
    _check_grant(user, body.tenants, body.approve)
    people_log.info("people: %s adds @%s", user.matrix_id, localpart)
    r = people.add(localpart, body.name.strip(), body.tenants, body.approve, _language_arg(body.language))
    if not r.ok:
        raise HTTPException(status_code=502, detail=r.error)
    rbac.reload()
    return {"ok": True, "matrix_id": r.data.get("matrix_id"), "initial_password": r.data.get("initial_password")}


@app.put("/api/people/{localpart}")
def update_person(localpart: str, body: UpdatePersonRequest, user: UserScope = Depends(require_people_manager)):
    _target(user, localpart)
    _check_grant(user, body.tenants, body.approve)
    people_log.info("people: %s sets @%s to %s", user.matrix_id, localpart, ",".join(body.tenants))
    r = people.update(localpart, body.tenants, body.approve, _language_arg(body.language))
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


class LanguageRequest(BaseModel):
    language: str | None = None   # "en", "de" or null = let the browser decide


@app.post("/api/profile/language")
def set_my_language(body: LanguageRequest, user: UserScope = Depends(require_user)):
    """One's own language. Matrix accounts: through the people hook into
    team.yaml (users.yaml follows; no rooms or bots touched). Telegram-only
    accounts live in users.yaml alone and are written there."""
    lang = _language_arg(body.language)
    if user.matrix_id:
        r = people.set_language(user.matrix_id[1:].split(":")[0], lang)
        if not r.ok:
            raise HTTPException(status_code=502, detail=r.error)
    else:
        try:
            data = yaml.safe_load(USERS_YAML_PATH.read_text()) or {}
            target = next((e for e in data.get("users", []) if str(e.get("telegram_user_id")) == str(user.telegram_user_id)), None)
            if target is None:
                raise HTTPException(status_code=409, detail=t("err.user_entry_gone"))
            if lang:
                target["language"] = lang
            else:
                target.pop("language", None)
            USERS_YAML_PATH.write_text(yaml.safe_dump(data, sort_keys=False))
        except OSError as e:
            raise HTTPException(status_code=500, detail=t("err.profile_save", error=str(e)))
    rbac.reload()
    return {"ok": True, "language": lang}


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/profile/password")
def change_password(body: PasswordChangeRequest, user: UserScope = Depends(require_user)):
    """The signed-in person's own Matrix password (see auth/matrix_password.py)."""
    if not user.matrix_id:
        raise HTTPException(status_code=409, detail=t("err.no_matrix_login"))
    if password_changer is None:
        raise HTTPException(status_code=503, detail=t("err.password_unconfigured"))
    outcome = password_changer.change(user.matrix_id, body.current_password, body.new_password)
    if not outcome.ok:
        raise HTTPException(status_code=outcome.status, detail=outcome.error)
    logger.info("password changed by %s", user.matrix_id)
    return {"ok": True}


# --- help: docs/user-guide.md (English) and user-guide.<lang>.md, the one guide for business users ---

USER_GUIDE = Path(__file__).resolve().parents[1] / "docs" / "user-guide.md"
HELP_PAGE = """<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{help_title} · Team Portal</title>
<style>:root{{--bg:#0f1115;--panel:#171a21;--line:#303643;--text:#e7eaf0;--muted:#aab2c0}}
body{{font:15px/1.55 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text)}}
header{{position:sticky;top:0;background:var(--panel);padding:14px 20px;border-bottom:1px solid var(--line)}}
a{{color:#9ab8ff}}main{{max-width:820px;margin:0 auto;padding:8px 16px 48px}}
h1,h2,h3{{line-height:1.25}}h2{{margin-top:2em;border-bottom:1px solid var(--line);padding-bottom:6px}}
code{{background:#202530;padding:1px 5px;border-radius:4px;word-break:break-word}}
table{{border-collapse:collapse;width:100%;display:block;overflow-x:auto}}
th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
.toc{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:6px 18px}}
.toc ul{{padding-left:18px}}</style></head>
header span{{float:right}}header span a{{margin-left:10px}}</style></head>
<body><header><a href="/">← Team Portal</a><span>{switch}</span></header><main>{body}</main></body></html>"""
LANGUAGE_NAMES = {"en": "English", "de": "Deutsch"}


def guide_path(lang: str) -> Path:
    localized = USER_GUIDE.with_name(f"user-guide.{lang}.md")
    return localized if lang != i18n.DEFAULT and localized.exists() else USER_GUIDE


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request):
    """Public on purpose: people read it before their first sign-in. It
    holds no data, only how to use the Portal and Matrix; {{HOST}} becomes
    the server name the reader reached. The language follows the request
    (?lang=, cookie, browser); the header switches it."""
    host = html.escape(request.url.hostname or "your-server")
    lang = i18n.current()
    body = markdown.markdown(guide_path(lang).read_text().replace("{{HOST}}", host),
                             extensions=["tables", "toc", "fenced_code"])
    switch = " · ".join(f"<b>{name}</b>" if code == lang else f'<a href="/help?lang={code}">{name}</a>'
                        for code, name in LANGUAGE_NAMES.items() if code in i18n.SUPPORTED)
    response = HTMLResponse(HELP_PAGE.format(body=body, lang=lang, switch=switch, help_title=t("nav.help")),
                            headers={"Cache-Control": "no-store"})
    if request.query_params.get("lang"):   # an explicit choice is kept, like the Portal's switcher
        response.set_cookie(i18n.COOKIE, lang, max_age=i18n.COOKIE_MAX_AGE, samesite="lax",
                            secure=PORTAL_BASE_URL.startswith("https://"))
    return response


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
    lanes, by_task = _lanes_of(tenants)
    for t in tasks:
        t["comments"] = kanban_read.list_comments(KANBAN_DB_PATH, t["id"])
        due = find_due_date(t)
        t["due_date"] = due
        t["overdue"] = is_overdue(due) if due else False
        _put_lane(t, lanes, by_task)
    return {"tenants": tenants, "tasks": tasks, "lanes": lanes}


def _lanes_of(tenants: list[str]) -> tuple[dict, dict]:
    """{tenant: [lanes]} and {task id: TaskLane} from the team store; empty
    without a store."""
    if not team_read.available(TEAM_DB_PATH):
        return {}, {}
    return {t: team_read.swimlanes(TEAM_DB_PATH, t) for t in tenants}, team_read.task_lanes(TEAM_DB_PATH)


def _put_lane(task: dict, lanes: dict, by_task: dict) -> None:
    """The card's lane (id, name, color) when it has one that still exists
    in its team; a lane deleted or archived counts as no lane."""
    tl = by_task.get(task["id"])
    lane = next((l for l in lanes.get(task.get("tenant"), []) if tl and l["id"] == tl["lane"]), None)
    task["lane"] = lane["id"] if lane else None
    task["lane_name"] = lane.get("name") if lane else None
    task["lane_color"] = lane.get("color") if lane else None


# --- dashboard (read) ---

RECENT_DAYS = 7


def _brief(t: dict) -> dict:
    due = find_due_date(t)
    return {"id": t["id"], "title": t.get("title"), "status": t.get("status"), "assignee": t.get("assignee"),
            "updated_at": t.get("updated_at"), "due_date": due, "overdue": is_overdue(due) if due else False}


@app.get("/api/dashboard")
def dashboard(tenant: str | None = Query(default=None), user: UserScope = Depends(require_user)):
    """The landing page: one tenant's objectives, KPIs, open work and approved
    reviews; roll-up tiles for people who see every tenant. Reads the team
    store and the board; writes come later through the bridge."""
    board_tenants = kanban_read.distinct_tenants(KANBAN_DB_PATH)
    readable = user.readable_tenants(sorted(set(board_tenants) | set(user.tenants)))
    if not team_read.available(TEAM_DB_PATH):
        return {"available": False, "tenants": readable, "tenant": tenant}
    if tenant is None:
        tenant = readable[0] if readable else None
    if tenant is None or not user.can_read_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    tasks = kanban_read.list_tasks(KANBAN_DB_PATH, tenants=[tenant])
    recent = int(__import__("time").time()) - RECENT_DAYS * 86400
    work = {
        "awaiting_my_approval": [_brief(task) for task in tasks if task.get("status") == "review" and _may_review(user, task, _links(task["id"]))],
        "in_review": [_brief(task) for task in tasks if task.get("status") == "review"],
        "blocked": [_brief(task) for task in tasks if task.get("status") == "blocked"],
        "in_progress": [_brief(task) for task in tasks if task.get("status") == "running"],
        "recently_done": [_brief(task) for task in tasks if task.get("status") in ("done", "archived")
                          and (task.get("completed_at") or 0) >= recent][:8],
    }
    out = {
        "available": True, "tenant": tenant, "tenants": readable,
        "can_approve": user.can_approve_tenant(tenant),
        "objectives": team_read.objectives(TEAM_DB_PATH, tenant),
        "kpis": team_read.kpis(TEAM_DB_PATH, tenant),
        "reviews": team_read.reviews(TEAM_DB_PATH, tenant),
        "work": work,
        "serving": team_read.tasks_serving(TEAM_DB_PATH, tenant),
        "sources": team_read.sources(TEAM_DB_PATH, tenant) if user.can_approve_tenant(tenant) else [],
        "lanes": _lane_rows(tenant, tasks, include_archived=user.can_approve_tenant(tenant)),
        "movable_to": [task for task in readable if task != tenant] if user.can_approve_tenant(tenant) else [],
    }
    if user.can_rollup:
        tiles = []
        for task in readable:
            tt = kanban_read.list_tasks(KANBAN_DB_PATH, tenants=[task])
            tile = team_read.tenant_summary(TEAM_DB_PATH, task)
            tile["tenant"] = task
            tile["board"] = {"open": sum(1 for x in tt if x.get("status") not in ("done", "archived")),
                             "blocked": sum(1 for x in tt if x.get("status") == "blocked"),
                             "review": sum(1 for x in tt if x.get("status") == "review")}
            tiles.append(tile)
        out["rollup"] = tiles
    return out


def _lane_rows(tenant: str, tasks: list[dict], include_archived: bool = False) -> list[dict]:
    """The team's lanes with how many open cards each holds."""
    lanes = team_read.swimlanes(TEAM_DB_PATH, tenant, include_archived=include_archived)
    by_task = team_read.task_lanes(TEAM_DB_PATH)
    open_count: dict[str, int] = {}
    for t in tasks:
        tl = by_task.get(t["id"])
        if tl and t.get("status") not in ("done", "archived"):
            open_count[tl["lane"]] = open_count.get(tl["lane"], 0) + 1
    for lane in lanes:
        lane["open_cards"] = open_count.get(lane["id"], 0)
    return lanes


# --- dashboard (write: through the bridge) ---

OKR_TYPES = {"Objective", "KeyResult", "KPI", "Source", "Swimlane"}


class OkrObjectRequest(BaseModel):
    type: str
    id: str | None = None
    objective_id: str | None = None      # a new KeyResult's objective
    data: dict
    reason: str = "dashboard"


class CheckinRequest(BaseModel):
    target_id: str
    value: float
    note: str = ""


def _store_result(result) -> dict:
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error[:500])
    out = {"ok": True, "object": result.object}
    if result.notice:
        out["notice"] = result.notice
    return out


def _okr_tenant(body: OkrObjectRequest) -> str | None:
    if body.id:
        return team_read.tenant_of(TEAM_DB_PATH, body.id)
    if body.type == "KeyResult":
        return team_read.tenant_of(TEAM_DB_PATH, body.objective_id) if body.objective_id else None
    return body.data.get("tenant")


def require_team_owner(user: UserScope, tenant: str | None) -> None:
    """Definitions are the team owner's: for now the people with approval
    rights for the tenant (team.yaml can_approve_artifacts)."""
    if not tenant or not user.can_approve_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.owners_define"))


@app.post("/api/okr/objects")
def okr_upsert(body: OkrObjectRequest, user: UserScope = Depends(require_user)):
    if body.type not in OKR_TYPES:
        raise HTTPException(status_code=422, detail=t("err.okr_type"))
    if body.type == "KeyResult" and not body.id and not body.objective_id:
        raise HTTPException(status_code=422, detail=t("err.kr_needs_objective"))
    reject_reserved_markers(*[v for v in body.data.values() if isinstance(v, str)])
    tenant = _okr_tenant(body)
    require_team_owner(user, tenant)
    if "tenant" in body.data and body.data["tenant"] != tenant:
        raise HTTPException(status_code=403, detail=t("err.use_move"))
    result = team_write.upsert(body.type, body.data, actor=user.name, reason=body.reason[:200] or "dashboard",
                               object_id=body.id, objective_id=None if body.id else body.objective_id)
    return _store_result(result)


@app.post("/api/okr/objects/{object_id}/delete")
def okr_delete(object_id: str, user: UserScope = Depends(require_user)):
    require_team_owner(user, team_read.tenant_of(TEAM_DB_PATH, object_id))
    return _store_result(team_write.delete(object_id, actor=user.name, reason="deleted from the dashboard"))


class MoveRequest(BaseModel):
    tenant: str


@app.post("/api/okr/objects/{object_id}/move")
def okr_move(object_id: str, body: MoveRequest, user: UserScope = Depends(require_user)):
    """An owner of the current team moves an objective (with its key results
    and the KPIs that name it), a KPI, a source or a lane to another team
    they belong to; the target team's owners see it on their dashboard."""
    source = team_read.tenant_of(TEAM_DB_PATH, object_id)
    require_team_owner(user, source)
    if not user.can_read_tenant(body.tenant):
        raise HTTPException(status_code=403, detail=t("err.not_member_target"))
    if body.tenant == source:
        raise HTTPException(status_code=422, detail=t("err.already_in_team"))
    return _store_result(team_write.move(object_id, body.tenant, actor=user.name, reason=f"moved from {source} to {body.tenant}"))


@app.post("/api/okr/checkin")
def okr_checkin(body: CheckinRequest, user: UserScope = Depends(require_user)):
    """Any member of the team records a value; the store keeps who and when."""
    reject_reserved_markers(body.note)
    tenant = team_read.tenant_of(TEAM_DB_PATH, body.target_id)
    if not tenant or not user.can_read_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    return _store_result(team_write.checkin(body.target_id, body.value, actor=user.name, reason="check-in", note=body.note[:1000]))


# --- stakeholders: who owns, reviews and follows a card (team store) ---

STAKEHOLDER_ROLES = ("owner", "reviewer", "watcher")


def _element_thread_url(thread: dict | None) -> str | None:
    if not thread:
        return None
    return f"/#/room/{thread['room_id']}/{thread['event_id']}"   # appended to the Element origin by the page


def _may_review(user: UserScope, task: dict, links: list[dict]) -> bool:
    """Approval rights for the tenant, narrowed to the card's reviewers when
    any are named."""
    if not user.can_approve_tenant(task.get("tenant", "")):
        return False
    reviewers = [l for l in links if l.get("role") == "reviewer"]
    if not reviewers:
        return True
    return any(l.get("matrix_id") == user.matrix_id or l.get("person") == user.name for l in reviewers)


def _links(task_id: str) -> list[dict]:
    return team_read.task_links(TEAM_DB_PATH, task_id) if team_read.available(TEAM_DB_PATH) else []


class StakeholderRequest(BaseModel):
    matrix_id: str
    role: str
    key_result: str | None = None       # the owner's link serves this key result


def _member(user: UserScope, tenant: str, matrix_id: str) -> UserScope:
    target = rbac.get(matrix_id)
    if target is None or not target.can_read_tenant(tenant):
        raise HTTPException(status_code=422, detail=t("err.not_member"))
    return target


@app.get("/api/members")
def members(tenant: str = Query(...), user: UserScope = Depends(require_user)):
    """People of a team, for the stakeholder picker."""
    if not user.can_read_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    rows = [{"name": u.name, "matrix_id": u.matrix_id, "can_approve": u.can_approve_tenant(tenant)}
            for u in rbac.all() if u.matrix_id and u.can_read_tenant(tenant)]
    rows.sort(key=lambda r: r["name"].lower())
    return {"members": rows}


@app.get("/api/okr/key-results")
def key_result_options(tenant: str = Query(...), user: UserScope = Depends(require_user)):
    if not user.can_read_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    if not team_read.available(TEAM_DB_PATH):
        return {"key_results": []}
    return {"key_results": team_read.key_results_of_tenant(TEAM_DB_PATH, tenant)}


@app.post("/api/tasks/{task_id}/stakeholders")
def add_stakeholder(task_id: str, body: StakeholderRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    if body.role not in STAKEHOLDER_ROLES:
        raise HTTPException(status_code=422, detail=t("err.stakeholder_role"))
    tenant = task.get("tenant", "")
    target = _member(user, tenant, body.matrix_id)
    if body.role == "reviewer" and not target.can_approve_tenant(tenant):
        raise HTTPException(status_code=422, detail=t("err.no_approval_rights", name=target.name, tenant=tenant))
    if body.role in ("owner", "reviewer") and not user.can_approve_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.name_stakeholders"))
    if body.key_result and team_read.tenant_of(TEAM_DB_PATH, body.key_result) != tenant:
        raise HTTPException(status_code=422, detail=t("err.kr_other_team"))
    result = team_write.upsert("TaskLink", {"task_id": task_id, "person": target.name, "matrix_id": target.matrix_id, "role": body.role},
                               actor=user.name, reason=f"stakeholder on {task_id}")
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error[:500])
    if body.key_result:
        linked = team_write.link("serves", result.object["id"], body.key_result, actor=user.name, reason=f"{task_id} serves a key result")
        if not linked.ok:
            raise HTTPException(status_code=502, detail=linked.error[:500])
    return _store_result(result)


@app.post("/api/tasks/{task_id}/stakeholders/{link_id}/delete")
def remove_stakeholder(task_id: str, link_id: str, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    link = next((l for l in _links(task_id) if l["id"] == link_id), None)
    if link is None:
        raise HTTPException(status_code=404, detail=t("err.not_found"))
    own = link.get("matrix_id") == user.matrix_id
    if not own and not user.can_approve_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.remove_others"))
    return _store_result(team_write.delete(link_id, actor=user.name, reason=f"stakeholder removed from {task_id}"))


@app.get("/api/lanes")
def lane_options(tenant: str = Query(...), user: UserScope = Depends(require_user)):
    if not user.can_read_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    if not team_read.available(TEAM_DB_PATH):
        return {"lanes": []}
    return {"lanes": [{"id": l["id"], "name": l.get("name"), "color": l.get("color")} for l in team_read.swimlanes(TEAM_DB_PATH, tenant)]}


class LaneRequest(BaseModel):
    lane: str | None = None       # Swimlane id; null takes the card out of its lane


def _set_lane(task_id: str, tenant: str, lane_id: str | None, user: UserScope) -> dict | None:
    """One TaskLane per card: update it, create it, or delete it for null.
    The lane must be one of the card's team."""
    if lane_id and not any(l["id"] == lane_id for l in team_read.swimlanes(TEAM_DB_PATH, tenant)):
        raise HTTPException(status_code=422, detail=t("err.lane_other_team"))
    current = team_read.task_lanes(TEAM_DB_PATH).get(task_id)
    if lane_id is None:
        if current is None:
            return None
        return _store_result(team_write.delete(current["id"], actor=user.name, reason=f"{task_id} taken out of its lane"))
    return _store_result(team_write.upsert("TaskLane", {"task_id": task_id, "tenant": tenant, "lane": lane_id},
                                           actor=user.name, reason=f"{task_id} put in a lane", object_id=current["id"] if current else None))


@app.post("/api/tasks/{task_id}/lane")
def set_task_lane(task_id: str, body: LaneRequest, user: UserScope = Depends(require_user)):
    """Any member of the card's team puts it in one of the team's lanes."""
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    if not team_read.available(TEAM_DB_PATH):
        raise HTTPException(status_code=503, detail=t("err.records_unset"))
    return _set_lane(task_id, task.get("tenant", ""), body.lane, user) or {"ok": True}


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=t("err.not_found"))
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    task["comments"] = kanban_read.list_comments(KANBAN_DB_PATH, task_id)
    task["attachments"] = kanban_read.list_attachments(KANBAN_DB_PATH, task_id)
    links = _links(task_id)
    task["stakeholders"] = links
    task["can_review"] = _may_review(user, task, links)
    task["can_name_stakeholders"] = user.can_approve_tenant(task.get("tenant", ""))
    task["thread_url"] = _element_thread_url(team_read.task_thread(TEAM_DB_PATH, task_id)) if team_read.available(TEAM_DB_PATH) else None
    lanes, by_task = _lanes_of([task.get("tenant", "")])
    _put_lane(task, lanes, by_task)
    task["lanes"] = [{"id": l["id"], "name": l.get("name"), "color": l.get("color")} for l in lanes.get(task.get("tenant", ""), [])]
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
        raise HTTPException(status_code=404, detail=t("err.task_not_found"))
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail=t("err.attachment_too_big"))
    if not data:
        raise HTTPException(status_code=400, detail=t("err.attachment_empty"))
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
        raise HTTPException(status_code=404, detail=t("err.attachment_not_found"))
    task = kanban_read.get_task(KANBAN_DB_PATH, attachment["task_id"])
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=404, detail=t("err.attachment_not_found"))
    name = Path(attachment["stored_path"]).name
    candidate = (KANBAN_ATTACHMENTS_ROOT / attachment["task_id"] / name).resolve()
    try:
        candidate.relative_to(KANBAN_ATTACHMENTS_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=404, detail=t("err.attachment_unavailable"))
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=t("err.attachment_unmounted"))
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
    if any(task and SLA_DEADLINE_RE.search(task) for task in texts):
        raise HTTPException(status_code=422, detail=t("err.sla_marker"))


def check_assignee(assignee: str | None, allow_none: bool = False) -> None:
    """Only installed department profiles (bridge /kanban/assignees): never the
    operator's default profile or an arbitrary string."""
    if assignee in (None, ""):
        return
    if allow_none and assignee == "none":
        return
    if assignee not in kanban_write.list_assignees():
        raise HTTPException(status_code=422, detail=t("err.unknown_assignee", assignee=repr(assignee)))


def ok_result(result) -> dict:
    """A success payload; `notice` is shown to the person by the page (e.g. the
    bridge removed hidden characters from their text)."""
    out = {"ok": True}
    if getattr(result, "notice", ""):
        out["notice"] = result.notice
    return out


@app.post("/api/tasks/{task_id}/comments")
def add_comment(task_id: str, body: CommentRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    reject_reserved_markers(body.text)
    result = kanban_write.comment_task(HERMES_BIN, task_id, body.text, author=user.name)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return ok_result(result)


# --- kanban (write) ---

class CreateTaskRequest(BaseModel):
    key_result: str | None = None      # the new card serves this key result
    lane: str | None = None            # Swimlane id of the card's team
    title: str
    tenant: str
    body: str = ""
    assignee: str | None = None
    status: str = "running"
    priority: int = 0


@app.post("/api/tasks")
def create_task(body: CreateTaskRequest, user: UserScope = Depends(require_user)):
    if not user.can_read_tenant(body.tenant):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    allowed_statuses = {"triage", "todo", "ready", "running", "review", "blocked", "done", "archived"}
    if body.status not in allowed_statuses:
        raise HTTPException(status_code=422, detail=t("err.initial_status"))
    if body.status in {"done", "archived"} and not user.can_approve_tenant(body.tenant):
        raise HTTPException(status_code=403, detail=t("err.initial_status_review"))
    reject_reserved_markers(body.title, body.body)
    check_assignee(body.assignee)
    if body.key_result and team_read.available(TEAM_DB_PATH) and team_read.tenant_of(TEAM_DB_PATH, body.key_result) != body.tenant:
        raise HTTPException(status_code=422, detail=t("err.kr_other_team"))
    if body.lane and team_read.available(TEAM_DB_PATH) and not any(l["id"] == body.lane for l in team_read.swimlanes(TEAM_DB_PATH, body.tenant)):
        raise HTTPException(status_code=422, detail=t("err.lane_other_team"))
    result = kanban_write.create_task(HERMES_BIN, body.title, body.tenant, body.body,
                                      body.assignee, body.status, body.priority)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    out = ok_result(result)
    task_id = _created_id(result.stdout)
    if task_id and team_read.available(TEAM_DB_PATH):
        if user.matrix_id:
            # the creator owns the card; the owner's link is what serves a key result
            link = team_write.upsert("TaskLink", {"task_id": task_id, "person": user.name, "matrix_id": user.matrix_id, "role": "owner"},
                                     actor=user.name, reason=f"created {task_id}")
            if link.ok and body.key_result:
                team_write.link("serves", link.object["id"], body.key_result, actor=user.name, reason=f"{task_id} serves a key result")
        if body.lane:
            team_write.upsert("TaskLane", {"task_id": task_id, "tenant": body.tenant, "lane": body.lane}, actor=user.name, reason=f"{task_id} created in a lane")
        out["task_id"] = task_id
    return out


def _created_id(stdout: str) -> str | None:
    try:
        data = json.loads(stdout)
        return data.get("id") if isinstance(data, dict) else None
    except ValueError:
        m = re.search(r"\bt_[A-Za-z0-9_-]+", stdout or "")
        return m.group(0) if m else None


class EditTaskRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    priority: int | None = None
    assignee: str | None = None


@app.patch("/api/tasks/{task_id}")
def edit_task(task_id: str, body: EditTaskRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=t("err.not_found"))
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    if body.title is None and body.body is None and body.priority is None and body.assignee is None:
        raise HTTPException(status_code=422, detail=t("err.no_fields"))
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
    return ok_result(result)


class TransitionTaskRequest(BaseModel):
    status: str
    reason: str = "Moved from Team Portal"


@app.post("/api/tasks/{task_id}/transition")
def transition_task(task_id: str, body: TransitionTaskRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=t("err.not_found"))
    allowed_statuses = {"todo", "ready", "running", "review", "blocked", "done", "archived"}
    if body.status not in allowed_statuses:
        raise HTTPException(status_code=422, detail=t("err.transition", status=body.status))
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    if body.status == "done" and not user.can_approve_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.reviewer_complete"))
    if (task.get("status") == "review" or body.status == "archived") and not user.can_approve_tenant(task.get("tenant", "")):
        # Moving a card out of Review rejects it; archiving removes it from view.
        raise HTTPException(status_code=403, detail=t("err.reviewer_move"))
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
        raise HTTPException(status_code=404, detail=t("err.task_not_found"))
    if not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    if task.get("status") != "ready":
        raise HTTPException(status_code=409, detail=t("err.claim_not_ready", status=task.get("status")))
    result = kanban_write.claim_task(HERMES_BIN, task_id)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return ok_result(result)


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
        t["can_review"] = _may_review(user, t, _links(t["id"]))
        t["autonomy_level"] = config_loader.autonomy_level(task_skills(t))
        t["auto_approves"] = auto_approves(t)
    return {"tasks": tasks}


@app.get("/api/artifacts/files")
def artifact_files(user: UserScope = Depends(require_user)):
    """Every file attached to a card the user can see, with the card's team,
    lane, status, owner (initiator) and reviewers, newest first. Filtering
    and sorting happen in the page; this is the whole list."""
    tenants = user.readable_tenants(kanban_read.distinct_tenants(KANBAN_DB_PATH))
    rows = kanban_read.list_all_attachments(KANBAN_DB_PATH, tenants=tenants)
    lanes, by_task = _lanes_of(tenants)
    links = team_read.task_links_many(TEAM_DB_PATH) if team_read.available(TEAM_DB_PATH) else {}
    for r in rows:
        tl = by_task.get(r["task_id"])
        lane = next((l for l in lanes.get(r.get("tenant"), []) if tl and l["id"] == tl["lane"]), None)
        r["lane"] = lane["id"] if lane else None
        r["lane_name"] = lane.get("name") if lane else None
        people = links.get(r["task_id"], [])
        owners = [p["person"] for p in people if p.get("role") == "owner" and p.get("person")]
        r["owner"] = owners[0] if owners else (r.get("uploaded_by") or r.get("created_by") or r.get("assignee"))
        r["reviewers"] = sorted({p["person"] for p in people if p.get("role") == "reviewer" and p.get("person")})
    return {"files": rows, "lanes": lanes}


class PublishArtifactRequest(BaseModel):
    task_id: str
    sla_hours: float | None = None   # None -> use config_loader.default_sla_hours()
    summary: str = ""


@app.post("/api/artifacts/publish")
def publish_artifact(body: PublishArtifactRequest, user: UserScope = Depends(require_user)):
    task = kanban_read.get_task(KANBAN_DB_PATH, body.task_id)
    if task is None or not user.can_read_tenant(task.get("tenant", "")):
        raise HTTPException(status_code=403, detail=t("err.not_in_scope"))
    hours = body.sla_hours if body.sla_hours is not None else config_loader.default_sla_hours()
    if not config_loader.min_sla_hours() <= hours <= 24 * 30:
        raise HTTPException(status_code=422, detail=t("err.sla_hours", min=f"{config_loader.min_sla_hours():g}"))
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
        raise HTTPException(status_code=404, detail=t("err.not_found"))
    tenant = task.get("tenant", "")
    if not user.can_approve_tenant(tenant):
        raise HTTPException(status_code=403, detail=t("err.review_tenant"))
    if not _may_review(user, task, _links(body.task_id)):
        raise HTTPException(status_code=403, detail=t("err.not_named_reviewer"))
    if body.approve:
        result = kanban_write.approve_artifact(HERMES_BIN, body.task_id, body.note, author=user.name)
    else:
        result = kanban_write.reject_artifact(HERMES_BIN, body.task_id, body.note or "Changes requested.",
                                              author=user.name)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.stderr[:500])
    return ok_result(result)
