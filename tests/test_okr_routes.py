"""Dashboard writes: owners (approval rights) define objectives, key results
and KPIs of their team; every member checks in; everything else is refused
before the bridge is called."""
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
            return StoreResult(True, object={"id": "x_000001", "type": kwargs.get("type_name", args[0] if args else "")})
        return f
    for name in ("upsert", "delete", "checkin"):
        monkeypatch.setattr(team_write, name, fake(name))
    return recorded


@pytest.fixture
def tim(writes):
    return client_as("@tim:hs.test")      # tech member without approval rights


def test_owner_creates_and_edits_in_own_team(alice, writes):
    r = alice.post("/api/okr/objects", json={"type": "Objective", "data": {"tenant": "tech", "title": "Faster", "period": "2026-Q4"}})
    assert r.status_code == 200, r.text
    assert writes[-1][0] == "upsert" and writes[-1][2]["actor"] == "Alice Tech" and writes[-1][1][0] == "Objective"
    r = alice.post("/api/okr/objects", json={"type": "KeyResult", "objective_id": "obj_t1", "data": {"title": "Cycle", "target": 24}})
    assert r.status_code == 200 and writes[-1][2]["objective_id"] == "obj_t1"
    r = alice.post("/api/okr/objects", json={"type": "KPI", "id": "kpi_t1", "data": {"target": 6}})
    assert r.status_code == 200 and writes[-1][2]["object_id"] == "kpi_t1"


def test_other_teams_and_members_are_refused(alice, bob, tim, writes):
    assert alice.post("/api/okr/objects", json={"type": "Objective", "data": {"tenant": "sales", "title": "x"}}).status_code == 403
    assert bob.post("/api/okr/objects", json={"type": "KPI", "id": "kpi_t1", "data": {"target": 1}}).status_code == 403
    assert tim.post("/api/okr/objects", json={"type": "Objective", "data": {"tenant": "tech", "title": "x"}}).status_code == 403
    assert alice.post("/api/okr/objects", json={"type": "KPI", "id": "kpi_t1", "data": {"tenant": "sales"}}).status_code == 403
    assert alice.post("/api/okr/objects", json={"type": "Measurement", "data": {}}).status_code == 422
    assert alice.post("/api/okr/objects", json={"type": "KeyResult", "data": {"title": "orphan"}}).status_code == 422
    assert alice.post("/api/okr/objects/kpi_s1/delete").status_code == 403
    assert alice.post("/api/okr/objects/kpi_t1/delete").status_code == 200 and writes[-1][0] == "delete"
    assert writes.count(("upsert",)) == 0 and len(writes) == 1


def test_members_check_in_on_their_team_only(tim, bob, writes):
    r = tim.post("/api/okr/checkin", json={"target_id": "kr_t1", "value": 30, "note": "steady"})
    assert r.status_code == 200 and writes[-1] == ("checkin", ("kr_t1", 30.0), {"actor": "Tim Tech", "reason": "check-in", "note": "steady"})
    assert bob.post("/api/okr/checkin", json={"target_id": "kr_t1", "value": 1}).status_code == 403
    assert bob.post("/api/okr/checkin", json={"target_id": "kpi_s1", "value": 1}).status_code == 200
    assert tim.post("/api/okr/checkin", json={"target_id": "nope_1", "value": 1}).status_code == 403


def test_bridge_failure_is_a_502_with_the_reason(alice, monkeypatch):
    monkeypatch.setattr(team_write, "upsert", lambda *a, **k: StoreResult(False, error="Objective.status: must start at draft"))
    r = alice.post("/api/okr/objects", json={"type": "Objective", "data": {"tenant": "tech", "title": "x", "status": "closed"}})
    assert r.status_code == 502 and "must start at draft" in r.json()["detail"]
