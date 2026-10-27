"""
Magic-link auth: the link is DMed via Telegram (default, through the bridge)
or, with PORTAL_AUTH_BACKEND=magic_link_matrix, via Matrix by the Portal's
own bot account (MATRIX_HOMESERVER + MATRIX_PORTAL_TOKEN).

Telegram notes: No domain/widget dependency — works today
on the tailnet, and is the bridge until the real Telegram Login Widget
exists.

Delivery target comes from users.yaml via RBAC.UserScope.delivery_target.
Prefer numeric `telegram_chat_id`/`telegram_user_id` for DMs: Telegram bots
generally cannot initiate arbitrary DMs by @username until the user has
started the bot. @username is supported as the user-facing login handle;
delivery stays numeric unless explicitly configured otherwise.
"""
from __future__ import annotations

import secrets
import subprocess
import time
import urllib.parse
from dataclasses import dataclass

import httpx

from ..i18n import t
from ..rbac import UserScope

TOKEN_TTL_SECONDS = 600  # 10 minutes


MAX_LINKS_PER_WINDOW = 3     # per user per TOKEN_TTL_SECONDS
MAX_PENDING = 1000


@dataclass
class PendingToken:
    user_key: str
    expires_at: float
    nonce: str = ""      # the requesting browser's login_nonce cookie


class MatrixDM:
    """Sends a DM from the Portal's bot account, reusing the DM room recorded
    in the bot's m.direct account data. The recipient sees an invite the
    first time and has to accept it before the message shows."""

    def __init__(self, homeserver: str, token: str):
        self._base = homeserver.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    def _call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        resp = httpx.request(method, self._base + path, json=body, headers=self._headers, timeout=15)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}

    def _usable_dm(self, room: str, user_id: str) -> bool:
        """Still a two-person room the user is in (or invited to)."""
        q = urllib.parse.quote
        code, member = self._call("GET", f"/_matrix/client/v3/rooms/{q(room)}/state/m.room.member/{q(user_id)}")
        if code != 200 or member.get("membership") not in ("join", "invite"):
            return False
        code, joined = self._call("GET", f"/_matrix/client/v3/rooms/{q(room)}/joined_members")
        return code == 200 and len(joined.get("joined", {})) <= 2

    def send(self, user_id: str, text: str) -> None:
        code, me = self._call("GET", "/_matrix/client/v3/account/whoami")
        if code != 200:
            raise RuntimeError(f"portal bot token rejected ({code})")
        direct_path = f"/_matrix/client/v3/user/{urllib.parse.quote(me['user_id'])}/account_data/m.direct"
        code, direct = self._call("GET", direct_path)
        if code == 404:
            direct = {}
        elif code != 200:
            # Writing back a guessed {} would wipe the bot's other DM mappings.
            raise RuntimeError(f"could not read the bot's DM list ({code})")
        room = next((r for r in direct.get(user_id, []) if self._usable_dm(r, user_id)), None)
        if room is None:
            code, created = self._call("POST", "/_matrix/client/v3/createRoom", {
                "is_direct": True, "invite": [user_id], "preset": "trusted_private_chat",
                "name": "Team Portal login"})
            if code != 200:
                raise RuntimeError(f"could not open a DM with {user_id} ({code}: {created.get('error', '')})")
            room = created["room_id"]
            direct[user_id] = [room] + [r for r in direct.get(user_id, []) if r != room]
            self._call("PUT", direct_path, direct)
        txn = secrets.token_hex(8)
        code, resp = self._call("PUT", f"/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/send/m.room.message/{txn}",
                                {"msgtype": "m.text", "body": text})
        if code != 200:
            raise RuntimeError(f"could not send the login DM ({code}: {resp.get('error', '')})")


@dataclass
class IssueResult:
    token: str
    delivered: bool
    error: str = ""


class MagicLinkAuth:
    def __init__(self, hermes_bin: str, portal_base_url: str,
                 bridge_url: str | None = None, bridge_api_key: str | None = None,
                 matrix: MatrixDM | None = None):
        self._hermes_bin = hermes_bin
        self._portal_base_url = portal_base_url.rstrip("/")
        self._bridge_url = bridge_url
        self._bridge_api_key = bridge_api_key
        self._matrix = matrix
        self._pending: dict[str, PendingToken] = {}

    def issue(self, user: UserScope, nonce: str = "") -> IssueResult:
        now = time.time()
        self._pending = {t: p for t, p in self._pending.items() if p.expires_at > now}
        recent = sum(1 for p in self._pending.values() if p.user_key == user.key)
        if recent >= MAX_LINKS_PER_WINDOW or len(self._pending) >= MAX_PENDING:
            return IssueResult(token="", delivered=False, error="rate limited")
        token = secrets.token_urlsafe(32)
        self._pending[token] = PendingToken(
            user_key=user.key,
            expires_at=now + TOKEN_TTL_SECONDS,
            nonce=nonce,
        )
        link = f"{self._portal_base_url}/login/verify?token={token}"
        # In the person's own language (users.yaml), not the requester's browser:
        # the DM reaches their phone, and a login asked for by someone else
        # must not change what they see.
        message = t("login.dm", lang=getattr(user, "language", None), minutes=TOKEN_TTL_SECONDS // 60, link=link)
        if self._matrix and user.matrix_id:
            try:
                self._matrix.send(user.matrix_id, message)
            except (httpx.HTTPError, RuntimeError, KeyError) as e:
                return IssueResult(token=token, delivered=False, error=f"Matrix delivery failed: {e}")
            return IssueResult(token=token, delivered=True)
        if user.telegram_user_id is None:
            return IssueResult(token=token, delivered=False, error="no Telegram ID and Matrix login is not enabled")
        delivery_target = user.delivery_target
        if self._bridge_url:
            headers = {"X-API-Key": self._bridge_api_key} if self._bridge_api_key else {}
            try:
                resp = httpx.post(
                    f"{self._bridge_url}/messaging/telegram/send",
                    json={"chat_id": str(delivery_target), "text": message},
                    headers=headers,
                    timeout=15,
                )
            except httpx.HTTPError as e:
                return IssueResult(token=token, delivered=False, error=f"bridge request failed: {e}")
            if resp.status_code >= 300:
                return IssueResult(token=token, delivered=False, error=f"bridge returned {resp.status_code}: {resp.text[:300]}")
            return IssueResult(token=token, delivered=True)

        # Direct-mode fallback for native/dev runs.
        try:
            result = subprocess.run(
                [self._hermes_bin, "send", "--to", f"telegram:{delivery_target}", message],
                capture_output=True, text=True, check=False, timeout=15,
            )
        except Exception as e:
            return IssueResult(token=token, delivered=False, error=f"direct send failed: {e}")
        if result.returncode != 0:
            return IssueResult(token=token, delivered=False, error=result.stderr[:300] or "direct send failed")
        return IssueResult(token=token, delivered=True)

    def peek(self, token: str) -> PendingToken | None:
        """The pending login for a token without using it up."""
        pending = self._pending.get(token)
        return pending if pending and time.time() <= pending.expires_at else None

    def verify(self, token: str) -> str | None:
        pending = self._pending.pop(token, None)
        if pending is None:
            return None
        if time.time() > pending.expires_at:
            return None
        return pending.user_key
