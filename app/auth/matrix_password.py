"""Self-service Matrix password change for the Profile page, so people who
only have a mobile Matrix app (which cannot change it) are not stuck with
the initial password. The Portal acts as the user: it proves the current
password with a fresh login, changes the password with user-interactive
auth, and logs that one-off session out again. Other sessions (the
person's phone) stay signed in. No admin rights involved."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

MIN_LENGTH = 12
ATTEMPTS = 5                 # per person per window: guessing the current password
WINDOW_SECONDS = 15 * 60


@dataclass
class Outcome:
    ok: bool
    status: int = 200
    error: str = ""


class PasswordChanger:
    def __init__(self, homeserver: str, client: httpx.Client | None = None):
        self._base = homeserver.rstrip("/")
        self._client = client or httpx.Client(timeout=15)
        self._attempts: dict[str, list[float]] = {}

    def _call(self, path: str, body: dict, token: str | None = None) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = self._client.post(self._base + path, json=body, headers=headers)
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, {}

    def change(self, user_id: str, current: str, new: str) -> Outcome:
        if len(new) < MIN_LENGTH:
            return Outcome(False, 422, f"Use at least {MIN_LENGTH} characters")
        if new == current:
            return Outcome(False, 422, "The new password must differ from the current one")
        now = time.time()
        recent = [t for t in self._attempts.get(user_id, []) if now - t < WINDOW_SECONDS]
        if len(recent) >= ATTEMPTS:
            return Outcome(False, 429, "Too many attempts; try again in 15 minutes")
        self._attempts[user_id] = recent + [now]
        localpart = user_id[1:].split(":", 1)[0]
        ident = {"type": "m.id.user", "user": localpart}
        try:
            code, resp = self._call("/_matrix/client/v3/login", {
                "type": "m.login.password", "identifier": ident, "password": current,
                "initial_device_display_name": "Team Portal (password change)"})
            if code == 403:
                return Outcome(False, 403, "Current password is wrong")
            if code == 429:
                return Outcome(False, 429, "Too many attempts; wait a minute and try again")
            if code != 200:
                return Outcome(False, 502, f"Matrix login failed ({code})")
            token = resp["access_token"]
            try:
                body = {"new_password": new, "logout_devices": False}
                code, resp = self._call("/_matrix/client/v3/account/password", body, token)
                if code == 401:   # user-interactive auth: prove the current password
                    body["auth"] = {"type": "m.login.password", "session": resp.get("session"),
                                    "identifier": ident, "password": current}
                    code, resp = self._call("/_matrix/client/v3/account/password", body, token)
                if code != 200:
                    return Outcome(False, 502, f"Matrix refused the change ({resp.get('errcode', code)})")
            finally:
                self._call("/_matrix/client/v3/logout", {}, token)
        except httpx.HTTPError:
            return Outcome(False, 502, "Matrix server not reachable")
        self._attempts.pop(user_id, None)
        return Outcome(True)
