"""Self-service Matrix password change (auth/matrix_password.py)."""
from __future__ import annotations

import json

import httpx
import pytest

from app import main
from app.auth.matrix_password import PasswordChanger

from conftest import client_as


def fake_homeserver(password: str):
    state = {"password": password, "calls": [], "tokens": set()}

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        state["calls"].append(request.url.path)
        if request.url.path.endswith("/login"):
            if body["password"] != state["password"]:
                return httpx.Response(403, json={"errcode": "M_FORBIDDEN"})
            state["tokens"].add("tok")
            return httpx.Response(200, json={"access_token": "tok"})
        if request.url.path.endswith("/account/password"):
            if "auth" not in body:
                return httpx.Response(401, json={"session": "s1", "flows": [{"stages": ["m.login.password"]}]})
            assert body["auth"]["session"] == "s1" and body["logout_devices"] is False
            state["password"] = body["new_password"]
            return httpx.Response(200, json={})
        if request.url.path.endswith("/logout"):
            state["tokens"].discard("tok")
            return httpx.Response(200, json={})
        return httpx.Response(404)

    return state, PasswordChanger("http://hs.test", httpx.Client(transport=httpx.MockTransport(handle)))


def test_change_proves_the_current_password_and_logs_its_session_out():
    state, pc = fake_homeserver("initial-password-1")
    assert pc.change("@tim:hs.test", "initial-password-1", "a-much-better-one").ok
    assert state["password"] == "a-much-better-one" and not state["tokens"]
    assert state["calls"][-1].endswith("/logout")


@pytest.mark.parametrize("current, new, status", [
    ("wrong-password-xx", "a-much-better-one", 403),
    ("initial-password-1", "short", 422),
    ("initial-password-1", "initial-password-1", 422),
])
def test_refusals(current, new, status):
    state, pc = fake_homeserver("initial-password-1")
    out = pc.change("@tim:hs.test", current, new)
    assert not out.ok and out.status == status and state["password"] == "initial-password-1"


def test_guessing_the_current_password_is_limited():
    _, pc = fake_homeserver("initial-password-1")
    for _ in range(5):
        assert pc.change("@tim:hs.test", "guess-guess-guess", "a-much-better-one").status == 403
    assert pc.change("@tim:hs.test", "initial-password-1", "a-much-better-one").status == 429


def test_endpoint_uses_the_signed_in_matrix_account(calls, monkeypatch):
    seen = []
    class Fake:
        def change(self, user_id, current, new):
            seen.append(user_id)
            from app.auth.matrix_password import Outcome
            return Outcome(True)
    monkeypatch.setattr(main, "password_changer", Fake())
    body = {"current_password": "initial-password-1", "new_password": "a-much-better-one"}
    assert client_as("@tim:hs.test").post("/api/profile/password", json=body).status_code == 200
    assert client_as("101").post("/api/profile/password", json=body).status_code == 409   # Telegram-only
    assert client_as(None).post("/api/profile/password", json=body).status_code == 401
    assert seen == ["@tim:hs.test"]
