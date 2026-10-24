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


def link_path(text: str) -> str:
    return text.split("http://portal.test", 1)[1].strip()


def test_same_browser_signs_in_directly_and_the_link_is_single_use(calls, matrix_login):
    c = client_as(None)
    r = c.post("/login", json={"login": "@MIA:hs.test"})
    assert r.status_code == 200
    (user, text), = matrix_login.sent
    assert user == "@mia:hs.test"
    path = link_path(text)
    assert c.get(path, follow_redirects=False).status_code == 303
    assert c.get("/api/profile").json()["name"] == "Mia Ops"
    assert client_as(None).get(path).status_code == 400


def test_another_browser_must_confirm_and_sees_whose_account(calls, matrix_login):
    client_as(None).post("/login", json={"login": "@mia:hs.test"})
    path = link_path(matrix_login.sent[0][1])
    other = client_as(None)            # e.g. a victim who was sent the attacker's link
    page = other.get(path)
    assert page.status_code == 200 and "Mia Ops" in page.text and "portal_session" not in page.headers.get("set-cookie", "")
    token = path.split("token=", 1)[1]
    assert other.post("/login/verify", data={"token": token}, follow_redirects=False).status_code == 303
    assert other.get("/api/profile").json()["name"] == "Mia Ops"


def test_login_answers_the_same_for_everyone(calls, matrix_login, monkeypatch):
    answers = {client_as(None).post("/login", json={"login": login}).text
               for login in ("@nobody:hs.test", "@ghost", "12345", "@mia:hs.test")}
    assert len(answers) == 1
    assert [u for u, _ in matrix_login.sent] == ["@mia:hs.test"]


def test_login_links_are_rate_limited(calls, matrix_login):
    for _ in range(6):
        client_as(None).post("/login", json={"login": "@mia:hs.test"})
    assert len(matrix_login.sent) == 3


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


class FakeHomeserver:
    """Just enough client API for MatrixDM."""
    def __init__(self, direct_code=200, direct=None, membership="join", members=2):
        self.direct_code, self.direct = direct_code, direct if direct is not None else {}
        self.membership, self.members = membership, members
        self.created, self.sent, self.put_direct = [], [], None

    def __call__(self, method, path, body=None):
        if path.endswith("/account/whoami"):
            return 200, {"user_id": "@portal:hs"}
        if "/account_data/m.direct" in path:
            if method == "PUT":
                self.put_direct = body
                return 200, {}
            return self.direct_code, dict(self.direct)
        if "/state/m.room.member/" in path:
            return 200, {"membership": self.membership}
        if path.endswith("/joined_members"):
            return 200, {"joined": {f"@u{i}:hs": {} for i in range(self.members)}}
        if path.endswith("/createRoom"):
            self.created.append(body)
            return 200, {"room_id": "!new:hs"}
        if "/send/m.room.message/" in path:
            self.sent.append(path)
            return 200, {}
        return 404, {}


def dm_with(hs):
    from app.auth.magic_link import MatrixDM
    dm = MatrixDM("http://hs", "tok")
    dm._call = hs
    return dm


def test_dm_reuses_a_live_two_person_room():
    hs = FakeHomeserver(direct={"@mia:hs": ["!old:hs"]})
    dm_with(hs).send("@mia:hs", "link")
    assert hs.created == [] and "%21old%3Ahs" in hs.sent[0]


@pytest.mark.parametrize("membership,members", [("leave", 2), ("join", 3)])
def test_dm_opens_a_new_room_when_the_old_one_is_unsafe(membership, members):
    hs = FakeHomeserver(direct={"@mia:hs": ["!old:hs"], "@bob:hs": ["!b:hs"]}, membership=membership, members=members)
    dm_with(hs).send("@mia:hs", "link")
    assert len(hs.created) == 1 and hs.put_direct["@bob:hs"] == ["!b:hs"]   # other DMs kept


def test_dm_never_overwrites_the_dm_list_on_a_read_error():
    hs = FakeHomeserver(direct_code=500)
    with pytest.raises(RuntimeError):
        dm_with(hs).send("@mia:hs", "link")
    assert hs.put_direct is None and hs.sent == []
