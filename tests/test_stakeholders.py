"""Stakeholders on a card: owners, reviewers and watchers from the team
store; named reviewers narrow who may approve; the card links to its
Matrix thread; a card can serve a key result."""
from __future__ import annotations

import pytest

from app import team_write
from app.team_write import StoreResult
from tests.conftest import client_as


@pytest.fixture
def writes(monkeypatch):
    recorded = []

    def fake(name):
        def f(*args, **kwargs):
            recorded.append((name, args, kwargs))
            return StoreResult(True, object={"id": "tasklink_new"})
        return f
    for name in ("upsert", "delete", "link"):
        monkeypatch.setattr(team_write, name, fake(name))
    return recorded


def test_task_detail_shows_stakeholders_and_thread(alice):
    t = alice.get("/api/tasks/t_tech1").json()
    assert [(s["role"], s["person"]) for s in t["stakeholders"]] == [("owner", "Tim Tech")]
    assert t["stakeholders"][0]["serves"] == [{"id": "kr_t1", "title": "Cycle time"}]
    assert t["thread_url"] == "/#/room/!tech:hs.test/$abc"
    assert t["can_review"] is True and t["can_name_stakeholders"] is True
    t3 = alice.get("/api/tasks/t_tech3").json()
    assert [(s["role"], s["person"]) for s in t3["stakeholders"]] == [("reviewer", "Lea Lead")]
    assert t3["can_review"] is False         # Alice may approve tech, but Lea is the named reviewer


def test_named_reviewers_narrow_approval(alice, calls):
    lea = client_as("@lead:hs.test")
    r = alice.post("/api/artifacts/review", json={"task_id": "t_tech3", "approve": True, "note": ""})
    assert r.status_code == 403 and "names its reviewers" in r.json()["detail"]
    assert lea.post("/api/artifacts/review", json={"task_id": "t_tech3", "approve": True, "note": ""}).status_code == 200
    assert [t["id"] for t in alice.get("/api/dashboard").json()["work"]["awaiting_my_approval"]] == ["t_tech1"]
    assert {t["id"] for t in lea.get("/api/dashboard?tenant=tech").json()["work"]["awaiting_my_approval"]} == {"t_tech1", "t_tech3"}


def test_members_and_key_results_are_scoped(alice, bob):
    names = [m["name"] for m in alice.get("/api/members?tenant=tech").json()["members"]]
    assert "Lea Lead" in names and "Tim Tech" in names and "Bob Sales" not in names
    assert bob.get("/api/members?tenant=tech").status_code == 403
    assert alice.get("/api/okr/key-results?tenant=tech").json()["key_results"] == [{"id": "kr_t1", "title": "Cycle time", "objective": "Ship faster"}]


def test_add_and_remove_stakeholders(alice, bob, writes):
    tim = client_as("@tim:hs.test")
    r = alice.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@lead:hs.test", "role": "reviewer"})
    assert r.status_code == 200, r.text
    assert writes[-1][0] == "upsert" and writes[-1][1][1]["role"] == "reviewer" and writes[-1][1][1]["person"] == "Lea Lead"
    # a member without approval rights cannot be a reviewer, and only approvers name owners/reviewers
    assert alice.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@tim:hs.test", "role": "reviewer"}).status_code == 422
    assert tim.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@lead:hs.test", "role": "owner"}).status_code == 403
    assert tim.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@tim:hs.test", "role": "watcher"}).status_code == 200
    assert alice.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@Mia:hs.test", "role": "watcher"}).status_code == 422
    assert bob.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@lead:hs.test", "role": "watcher"}).status_code == 403
    r = alice.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@lead:hs.test", "role": "owner", "key_result": "kr_t1"})
    assert r.status_code == 200 and writes[-1][0] == "link" and writes[-1][1][:3] == ("serves", "tasklink_new", "kr_t1")
    assert alice.post("/api/tasks/t_tech2/stakeholders", json={"matrix_id": "@lead:hs.test", "role": "owner", "key_result": "kpi_s1"}).status_code == 422
    # removal: yourself, or with approval rights
    assert tim.post("/api/tasks/t_tech3/stakeholders/tl_1/delete").status_code == 403
    assert tim.post("/api/tasks/t_tech1/stakeholders/tl_2/delete").status_code == 200
    assert alice.post("/api/tasks/t_tech3/stakeholders/tl_1/delete").status_code == 200
    assert alice.post("/api/tasks/t_tech1/stakeholders/tl_1/delete").status_code == 404


def test_portal_created_card_gets_its_creator_as_owner(calls, writes, monkeypatch):
    from app import kanban_write
    from app.kanban_write import CLIResult
    lea = client_as("@lead:hs.test")
    monkeypatch.setattr(kanban_write, "create_task", lambda *a, **k: CLIResult(True, '{"id": "t_new1"}', ""))
    r = lea.post("/api/tasks", json={"title": "Serve it", "tenant": "tech", "status": "ready", "key_result": "kr_t1"})
    assert r.status_code == 200 and r.json()["task_id"] == "t_new1"
    assert writes[0][0] == "upsert" and writes[0][1][1] == {"task_id": "t_new1", "person": "Lea Lead", "matrix_id": "@lead:hs.test", "role": "owner"}
    assert writes[1][0] == "link" and writes[1][1] == ("serves", "tasklink_new", "kr_t1")
    assert lea.post("/api/tasks", json={"title": "x", "tenant": "tech", "status": "ready", "key_result": "kpi_s1"}).status_code == 422
