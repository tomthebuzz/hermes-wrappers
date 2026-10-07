"""
Stub for the production auth path — Telegram Login Widget.

Only wire this up once team-portal.example.com (or whatever the real domain is) is
live and BotFather's /setdomain has been pointed at it. The widget posts a
signed payload (user id, name, auth_date, hash) to a callback URL; verifying
the hash requires the bot token as an HMAC key — see Telegram's own docs for
the exact algorithm (not duplicated here since it's outside Hermes' scope
and well-documented upstream: https://core.telegram.org/widgets/login).

NOT IMPLEMENTED YET — Phase 4 work. Left as a stub so main.py's auth
backend switch has somewhere to point once this is written.
"""
from __future__ import annotations


def verify_telegram_widget_payload(payload: dict, bot_token: str) -> int | None:
    raise NotImplementedError(
        "Telegram Login Widget verification not implemented yet — Phase 4, "
        "once team-portal.example.com + BotFather /setdomain exist. Use magic_link.py "
        "until then."
    )
