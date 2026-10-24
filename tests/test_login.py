from __future__ import annotations

from pathlib import Path

import pytest

from app import main
from app.auth.magic_link import MagicLinkAuth
from app.rbac import RBAC, normalize_matrix_id
from conftest import USERS, client_as


class FakeMatrix:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, user_id: str, text: str) -> None:
        self.sent.append((user_id, text))


@pytest.fixture
def matrix_login(monkeypatch):
    fake = FakeMatrix()
    auth = MagicLinkAuth(hermes_bin="hermes", portal_base_url="http://portal.test", matrix=fake)
    monkeypatch.setattr(main, "magic_link", auth)
    monkeypatch.setattr(main, "matrix_dm", fake)
    return fake


def test_matrix_login_link_is_single_use(calls, matrix_login):
    c = client_as(None)
    r = c.post("/login", json={"login": "@MIA:hs.test"})
    assert r.status_code == 200 and "Matrix" in r.json()["note"]
    (user, text), = matrix_login.sent
    assert user == "@mia:hs.test"
    path = text.split("http://portal.test", 1)[1].strip()
    assert c.get(path, follow_redirects=False).status_code in (302, 307)
    assert c.get("/api/profile").json()["name"] == "Mia Ops"
    assert client_as(None).get(path).status_code == 400


def test_unknown_logins_do_not_reveal_anything(calls, matrix_login):
    for login in ("@nobody:hs.test", "@ghost", "12345", ""):
        assert client_as(None).post("/login", json={"login": login}).status_code == 400
    assert matrix_login.sent == []


def test_rbac_resolves_handles_ids_and_matrix_ids():
    rbac = RBAC(USERS)
    assert rbac.resolve_login("@Alice").name == "Alice Tech"
    assert rbac.resolve_login("101").name == "Alice Tech"
    assert rbac.resolve_login("@mia:HS.TEST").name == "Mia Ops"
    assert rbac.get(101).key == "101" and rbac.get("@mia:hs.test").key == "@mia:hs.test"
    assert normalize_matrix_id("@x") is None and normalize_matrix_id("mia:hs") is None


def test_an_entry_without_any_identity_is_rejected(tmp_path: Path):
    bad = tmp_path / "users.yaml"
    bad.write_text("users:\n  - name: Nobody\n    tenants: [tech]\n")
    with pytest.raises(ValueError, match="telegram_user_id or matrix_id"):
        RBAC(bad)
