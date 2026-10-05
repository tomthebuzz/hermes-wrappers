"""
Magic-link-via-Telegram-DM auth. No domain/widget dependency — works today
on the tailnet, and is the bridge until futuretree.com + the real Telegram
Login Widget exist (see auth/telegram_widget.py stub).

Flow:
  1. User visits /login, enters their Telegram numeric user ID (or we look
     it up from a name->id map in users.yaml in a future iteration).
  2. We generate a short random token, store it with an expiry (in-memory
     here — swap for Redis/DB before any multi-instance deployment).
  3. We DM the token as a link to that Telegram user ID via `hermes send`.
     UNVERIFIED: `hermes send telegram --chat-id <id> "<text>"` shape is a
     best-effort guess from the CLI reference docs; confirm the real flag
     name for targeting an arbitrary chat_id (vs. the default configured
     recipient) before relying on this.
  4. User clicks the link (/login/verify?token=...), session cookie set.

This is intentionally simple for Phase 1. Token store is process-local and
single-instance only — fine for a 10-20 person internal tool on one host,
not fine once this runs replicated/behind a load balancer (swap the dict
for Redis at that point).
"""
from __future__ import annotations

import secrets
import subprocess
import time
from dataclasses import dataclass


TOKEN_TTL_SECONDS = 600  # 10 minutes


@dataclass
class PendingToken:
    telegram_user_id: int
    expires_at: float


class MagicLinkAuth:
    def __init__(self, hermes_bin: str, portal_base_url: str):
        self._hermes_bin = hermes_bin
        self._portal_base_url = portal_base_url.rstrip("/")
        self._pending: dict[str, PendingToken] = {}

    def issue(self, telegram_user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self._pending[token] = PendingToken(
            telegram_user_id=telegram_user_id,
            expires_at=time.time() + TOKEN_TTL_SECONDS,
        )
        link = f"{self._portal_base_url}/login/verify?token={token}"
        message = (
            "FutureTree Team Portal login link (expires in "
            f"{TOKEN_TTL_SECONDS // 60} minutes):\n{link}"
        )
        # UNVERIFIED invocation shape — see module docstring.
        subprocess.run(
            [self._hermes_bin, "send", "telegram",
             "--chat-id", str(telegram_user_id), message],
            capture_output=True, text=True, check=False, timeout=15,
        )
        return token

    def verify(self, token: str) -> int | None:
        pending = self._pending.pop(token, None)
        if pending is None:
            return None
        if time.time() > pending.expires_at:
            return None
        return pending.telegram_user_id
