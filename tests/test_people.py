"""People page: who may manage whom, and what reaches the bridge hook."""
from __future__ import annotations

import pytest

from app import people
from app.people import Result

from conftest import client_as


@pytest.fixture
def hook(monkeypatch, calls) -> list:
    recorded: list = []
    monkeypatch.setattr(people, "add", lambda *a: recorded.append(("add", *a)) or
                        Result(True, {"matrix_id": f"@{a[0]}:hs.test", "initial_password": "pw-1"}))
    monkeypatch.setattr(people, "update", lambda *a: recorded.append(("update", *a)) or Result(True, {}))
    monkeypatch.setattr(people, "remove", lambda *a: recorded.append(("remove", *a)) or Result(True, {}))
    return recorded


def test_owner_lists_people_on_own_server_with_edit_rights(hook):
    r = client_as("@own:hs.test").get("/api/people").json()
    rows = {p["localpart"]: p["editable"] for p in r["people"]}
    assert rows == {"lead": True, "mia": True, "own": False, "sam": True, "tim": True}
    assert "tech" in r["tenants"] and r["server"] == "hs.test"


def test_add_returns_the_initial_password_once(hook):
    r = client_as("@own:hs.test").post("/api/people", json={"localpart": "Ana", "name": "Ana Example",
                                                             "tenants": ["tech"], "approve": []})
    assert r.status_code == 200 and r.json()["initial_password"] == "pw-1"
    assert hook == [("add", "ana", "Ana Example", ["tech"], [])]


def test_members_without_the_right_get_nothing(hook):
    for who in ("@tim:hs.test", "@mia:hs.test", "101"):
        c = client_as(who)
        assert c.get("/api/people").status_code == 403
        assert c.post("/api/people", json={"localpart": "x", "name": "X", "tenants": ["tech"]}).status_code == 403
        assert c.delete("/api/people/tim").status_code == 403
    assert hook == []


@pytest.mark.parametrize("body, code", [
    ({"localpart": "ana", "name": "A", "tenants": ["ops"]}, 403),                      # lead cannot read ops
    ({"localpart": "ana", "name": "A", "tenants": ["sales"], "approve": ["sales"]}, 403),  # lead may not approve sales
    ({"localpart": "ana", "name": "A", "tenants": ["tech"], "approve": ["sales"]}, 422),   # approve outside tenants
    ({"localpart": "ana", "name": "A", "tenants": []}, 422),
    ({"localpart": "ana b", "name": "A", "tenants": ["tech"]}, 422),
    ({"localpart": "admin", "name": "A", "tenants": ["tech"]}, 422),
    ({"localpart": "ana", "name": 'A"', "tenants": ["tech"]}, 422),
    ({"localpart": "tim", "name": "T", "tenants": ["tech"]}, 409),
])
def test_a_manager_cannot_hand_out_more_than_they_have(hook, body, code):
    assert client_as("@lead:hs.test").post("/api/people", json=body).status_code == code
    assert hook == []


def test_a_limited_manager_changes_only_people_inside_their_reach(hook):
    lead = client_as("@lead:hs.test")
    assert lead.put("/api/people/tim", json={"tenants": ["tech", "sales"], "approve": ["tech"]}).status_code == 200
    assert lead.put("/api/people/sam", json={"tenants": ["sales"]}).status_code == 403     # sam also has ops
    assert lead.delete("/api/people/sam").status_code == 403
    assert lead.delete("/api/people/own").status_code == 403                               # owner
    assert lead.delete("/api/people/lead").status_code == 403                              # self
    assert lead.delete("/api/people/nobody").status_code == 404
    assert hook == [("update", "tim", ["tech", "sales"], ["tech"])]


def test_bridge_errors_reach_the_page(hook, monkeypatch):
    monkeypatch.setattr(people, "remove", lambda *a: Result(False, error="[kit] ERROR: boom"))
    r = client_as("@own:hs.test").delete("/api/people/tim")
    assert r.status_code == 502 and "boom" in r.json()["detail"]


def test_users_yaml_changes_apply_without_restart(hook, tmp_path):
    from app import main
    path = main.USERS_YAML_PATH
    before = path.read_text()
    try:
        path.write_text(before.replace('name: "Tim Tech"', 'name: "Tim Renamed"'))
        import os, time
        os.utime(path, (time.time() + 5, time.time() + 5))
        names = [p["name"] for p in client_as("@own:hs.test").get("/api/people").json()["people"]]
        assert "Tim Renamed" in names
    finally:
        path.write_text(before)
        main.rbac.reload()
