"""
Magic-link-via-Telegram-DM auth. No domain/widget dependency — works today
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
from dataclasses import dataclass

import httpx

TOKEN_TTL_SECONDS = 600  # 10 minutes


@dataclass
class PendingToken:
    telegram_user_id: int
    expires_at: float


@dataclass
class IssueResult:
    token: str
    delivered: bool
    error: str = ""


class MagicLinkAuth:
    def __init__(self, hermes_bin: str, portal_base_url: str,
                 bridge_url: str | None = None, bridge_api_key: str | None = None):
        self._hermes_bin = hermes_bin
        self._portal_base_url = portal_base_url.rstrip("/")
        self._bridge_url = bridge_url
        self._bridge_api_key = bridge_api_key
        self._pending: dict[str, PendingToken] = {}

    def issue(self, telegram_user_id: int, delivery_target: str) -> IssueResult:
        token = secrets.token_urlsafe(32)
        self._pending[token] = PendingToken(
            telegram_user_id=telegram_user_id,
            expires_at=time.time() + TOKEN_TTL_SECONDS,
        )
        link = f"{self._portal_base_url}/login/verify?token={token}"
        message = (
            "Team Portal login link (expires in "
            f"{TOKEN_TTL_SECONDS // 60} minutes):\n{link}"
        )
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

    def verify(self, token: str) -> int | None:
        pending = self._pending.pop(token, None)
        if pending is None:
            return None
        if time.time() > pending.expires_at:
            return None
        return pending.telegram_user_id
