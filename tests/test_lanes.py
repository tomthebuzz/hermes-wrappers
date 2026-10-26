"""Swimlanes: a team's own lanes on the board, cards in lanes, the lane and
team filters' data, moving objectives between teams, and the list of every
attached file with team, lane, owner and reviewers."""
from __future__ import annotations

import json
import sqlite3

import pytest

from app import kanban_write, team_write
from app.kanban_write import CLIResult
from app.team_write import StoreResult
from conftest import TEAM_DB, client_as


@pytest.fixture
def lanes():
    rows = [
        ("swimlane_01", "Swimlane", {"tenant": "tech", "name": "Speed", "order": 1, "color": "#3a7afe", "objective": "obj_t1", "status": "active"}),
        ("swimlane_02", "Swimlane", {"tenant": "tech", "name": "Old", "order": 0, "status": "archived"}),
        ("swimlane_s1", "Swimlane", {"tenant": "sales", "name": "Pipeline", "order": 1}),
        ("tasklane_01", "TaskLane", {"task_id": "t_tech1", "tenant": "tech", "lane": "swimlane_01"}),
        ("tasklane_02", "TaskLane", {"task_id": "t_tech2", "tenant": "tech", "lane": "swimlane_02"}),      # archived lane: shows as none
    ]
    with sqlite3.connect(TEAM_DB) as conn:
        for oid, ty, data in rows:
            conn.execute("INSERT INTO objects(id, type, data, source, created_at, updated_at) VALUES (?,?,?,'t',1,1)", (oid, ty, json.dumps(data)))
    yield
    with sqlite3.connect(TEAM_DB) as conn:
        conn.execute("DELETE FROM objects WHERE id IN (%s)" % ",".join("?" for _ in rows), [r[0] for r in rows])


@pytest.fixture
def writes(monkeypatch):
    recorded = []

    def fake(name):
        def f(*args, **kwargs):
            recorded.append((name, args, kwargs))
            return StoreResult(True, object={"id": "tasklane_new", "moved": {"kpis": ["kpi_t1"], "lanes_unlinked": []}})
        return f
    for name in ("upsert", "delete", "move", "link"):
        monkeypatch.setattr(team_write, name, fake(name))
    return recorded


def test_board_carries_active_lanes_and_each_cards_lane(alice, lanes):
    d = alice.get("/api/board").json()
    assert [l["name"] for l in d["lanes"]["tech"]] == ["Speed"]           # archived lanes stay off the board
    by_id = {t["id"]: t for t in d["tasks"]}
    assert by_id["t_tech1"]["lane"] == "swimlane_01" and by_id["t_tech1"]["lane_name"] == "Speed" and by_id["t_tech1"]["lane_color"] == "#3a7afe"
    assert by_id["t_tech2"]["lane"] is None                                # its lane is archived
    assert alice.get("/api/lanes?tenant=tech").json()["lanes"] == [{"id": "swimlane_01", "name": "Speed", "color": "#3a7afe"}]
    assert alice.get("/api/lanes?tenant=sales").status_code == 403
    t = alice.get("/api/tasks/t_tech1").json()
    assert t["lane"] == "swimlane_01" and [l["name"] for l in t["lanes"]] == ["Speed"]


def test_members_put_cards_in_their_teams_lanes_only(alice, bob, lanes, writes):
    tim = client_as("@tim:hs.test")
    r = tim.post("/api/tasks/t_tech2/lane", json={"lane": "swimlane_01"})
    assert r.status_code == 200, r.text
    name, args, kwargs = writes[-1]
    assert name == "upsert" and args[0] == "TaskLane" and args[1] == {"task_id": "t_tech2", "tenant": "tech", "lane": "swimlane_01"}
    assert kwargs["object_id"] == "tasklane_02" and kwargs["actor"] == "Tim Tech"      # the existing record is updated, not doubled
    assert tim.post("/api/tasks/t_tech2/lane", json={"lane": "swimlane_s1"}).status_code == 422
    assert bob.post("/api/tasks/t_tech2/lane", json={"lane": "swimlane_01"}).status_code == 403
    r = alice.post("/api/tasks/t_tech1/lane", json={"lane": None})
    assert r.status_code == 200 and writes[-1][0] == "delete" and writes[-1][1][0] == "tasklane_01"
    n = len(writes)
    assert alice.post("/api/tasks/t_tech3/lane", json={"lane": None}).json() == {"ok": True} and len(writes) == n


def test_a_new_card_can_start_in_a_lane(alice, lanes, writes, monkeypatch):
    monkeypatch.setattr(kanban_write, "create_task", lambda *a, **k: CLIResult(True, json.dumps({"id": "t_new1"}), ""))
    r = alice.post("/api/tasks", json={"title": "x", "tenant": "tech", "status": "ready", "lane": "swimlane_01"})
    assert r.status_code == 200, r.text
    assert any(w[0] == "upsert" and w[1][0] == "TaskLane" and w[1][1]["lane"] == "swimlane_01" for w in writes)
    assert alice.post("/api/tasks", json={"title": "x", "tenant": "tech", "status": "ready", "lane": "swimlane_s1"}).status_code == 422


def test_dashboard_lists_lanes_with_open_cards_and_where_owners_may_move(alice, lanes):
    d = alice.get("/api/dashboard").json()
    lanes_by = {l["name"]: l for l in d["lanes"]}
    assert set(lanes_by) == {"Speed", "Old"} and lanes_by["Speed"]["open_cards"] == 1 and lanes_by["Speed"]["objective"] == "obj_t1"
    assert d["movable_to"] == []                                            # Alice belongs to tech only
    lea = client_as("@lead:hs.test")
    d = lea.get("/api/dashboard?tenant=tech").json()
    assert d["movable_to"] == ["sales"]
    assert [l["name"] for l in client_as("@tim:hs.test").get("/api/dashboard").json()["lanes"]] == ["Speed"]   # members: active lanes


def test_owners_define_lanes_in_their_team(alice, writes):
    r = alice.post("/api/okr/objects", json={"type": "Swimlane", "data": {"tenant": "tech", "name": "Quality", "order": 2}})
    assert r.status_code == 200 and writes[-1][1][0] == "Swimlane"
    assert client_as("@tim:hs.test").post("/api/okr/objects", json={"type": "Swimlane", "data": {"tenant": "tech", "name": "x"}}).status_code == 403


def test_move_needs_ownership_here_and_membership_there(alice, writes):
    lea = client_as("@lead:hs.test")
    r = lea.post("/api/okr/objects/obj_t1/move", json={"tenant": "sales"})
    assert r.status_code == 200, r.text
    assert writes[-1][0] == "move" and writes[-1][1][:2] == ("obj_t1", "sales") and writes[-1][2]["actor"] == "Lea Lead"
    assert r.json()["object"]["moved"]["kpis"] == ["kpi_t1"]
    assert alice.post("/api/okr/objects/obj_t1/move", json={"tenant": "sales"}).status_code == 403     # not in sales
    assert client_as("@tim:hs.test").post("/api/okr/objects/obj_t1/move", json={"tenant": "sales"}).status_code == 403   # no approval rights
    assert lea.post("/api/okr/objects/obj_t1/move", json={"tenant": "tech"}).status_code == 422
    assert lea.post("/api/okr/objects/kpi_s1/move", json={"tenant": "tech"}).status_code == 403     # not an owner of sales


def test_every_attached_file_with_team_lane_owner_and_reviewers(alice, bob, rolly, lanes):
    files = alice.get("/api/artifacts/files").json()["files"]
    assert [f["filename"] for f in files] == ["report.md"]
    f = files[0]
    assert f["tenant"] == "tech" and f["lane_name"] == "Speed" and f["status"] == "review" and f["task_title"]
    assert f["owner"] == "Tim Tech" and f["reviewers"] == []
    sales = bob.get("/api/artifacts/files").json()["files"]
    assert [f["filename"] for f in sales] == ["deal.md"] and sales[0]["lane"] is None and sales[0]["owner"]   # falls back to who uploaded / created it
    assert sorted(f["filename"] for f in rolly.get("/api/artifacts/files").json()["files"]) == ["deal.md", "report.md"]
