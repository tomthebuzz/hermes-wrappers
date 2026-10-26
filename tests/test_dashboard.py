"""The dashboard: one tenant's objectives, KPIs, work and approved reviews,
scoped like the board; roll-up tiles for people who see every tenant."""
from __future__ import annotations

from pathlib import Path

from app import main


def test_default_tenant_and_content(alice):
    d = alice.get("/api/dashboard").json()
    assert d["available"] and d["tenant"] == "tech" and d["tenants"] == ["tech"]
    assert [o["title"] for o in d["objectives"]] == ["Ship faster"]
    kr = d["objectives"][0]["key_results"][0]
    assert kr["title"] == "Cycle time" and [m["value"] for m in kr["measurements"]] == [60, 40]
    assert [k["title"] for k in d["kpis"]] == ["Throughput"]
    assert [r["week"] for r in d["reviews"]] == ["2026-W43"]          # pending reviews stay hidden
    assert d["can_approve"] is True
    assert [t["id"] for t in d["work"]["awaiting_my_approval"]] == ["t_tech1"]
    assert "rollup" not in d


def test_other_tenant_is_refused_and_no_approvals_without_the_right(alice, bob):
    assert alice.get("/api/dashboard?tenant=sales").status_code == 403
    d = bob.get("/api/dashboard").json()
    assert d["tenant"] == "sales" and [k["title"] for k in d["kpis"]] == ["Leads"]
    assert d["can_approve"] is False and d["work"]["awaiting_my_approval"] == []


def test_rollup_tiles_for_leadership(rolly):
    d = rolly.get("/api/dashboard?tenant=tech").json()
    tiles = {t["tenant"]: t for t in d["rollup"]}
    assert set(tiles) >= {"tech", "sales", "ops", "leadership"}
    assert tiles["tech"]["objectives"] == {"active": 1} and tiles["tech"]["key_results"] == {"at_risk": 1}
    assert tiles["sales"]["kpis"] == {"crit": 1} and tiles["tech"]["board"]["review"] == 2


def test_without_a_team_store(alice, monkeypatch):
    monkeypatch.setattr(main, "TEAM_DB_PATH", Path("/nonexistent/ontology.db"))
    d = alice.get("/api/dashboard").json()
    assert d["available"] is False and d["tenants"] == ["tech"]
