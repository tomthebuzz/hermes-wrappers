"""
Read-only access to the team store (hermes-ontology, `ontology-team.yaml`:
objectives, key results, KPIs, measurements, reviews) for the dashboard —
same pattern as kanban_read.py: the store's directory is mounted read-only,
WAL visible, and every write goes through the bridge or a bot, never here.

The store is SQLite with one `objects` table (id, type, data JSON,
created_at, updated_at) and a `links` table (rel, from_id, to_id).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

TEAM_DB_PATH = Path(os.environ.get("TEAM_DB_PATH", "/team/ontology.db"))
SPARKLINE_POINTS = 30


def available(db_path: Path = TEAM_DB_PATH) -> bool:
    return db_path.exists()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _objects(conn: sqlite3.Connection, type_name: str) -> list[dict]:
    rows = conn.execute("SELECT id, type, data, created_at, updated_at FROM objects WHERE type = ? ORDER BY updated_at DESC",
                        (type_name,)).fetchall()
    out = []
    for r in rows:
        o = json.loads(r["data"])
        o.update({"id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"]})
        out.append(o)
    return out


def _children(conn: sqlite3.Connection, rel: str, parent_id: str) -> list[str]:
    return [r["to_id"] for r in conn.execute("SELECT to_id FROM links WHERE rel = ? AND from_id = ?", (rel, parent_id))]


def _by_id(conn: sqlite3.Connection, ids: list[str]) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(f"SELECT id, type, data, created_at, updated_at FROM objects WHERE id IN ({placeholders})", ids).fetchall()
    out = []
    for r in rows:
        o = json.loads(r["data"])
        o.update({"id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"]})
        out.append(o)
    return out


def _measurements(conn: sqlite3.Connection, rel: str, parent_id: str, limit: int = SPARKLINE_POINTS) -> list[dict]:
    """Newest `limit` measurements, returned oldest first for a sparkline."""
    ms = _by_id(conn, _children(conn, rel, parent_id))
    ms.sort(key=lambda m: m.get("at", ""))
    return [{"at": m.get("at"), "value": m.get("value"), "method": m.get("method"), "actor": m.get("actor"), "note": m.get("note")}
            for m in ms[-limit:]]


def objectives(db_path: Path, tenant: str) -> list[dict]:
    """Objectives of a tenant with their key results and recent measurements."""
    conn = _connect(db_path)
    try:
        out = []
        for o in _objects(conn, "Objective"):
            if o.get("tenant") != tenant:
                continue
            krs = _by_id(conn, _children(conn, "key_results", o["id"]))
            for kr in krs:
                kr["measurements"] = _measurements(conn, "kr_measurements", kr["id"])
            krs.sort(key=lambda k: k.get("title", ""))
            o["key_results"] = krs
            out.append(o)
        out.sort(key=lambda o: (o.get("status") != "active", o.get("period", ""), o.get("title", "")))
        return out
    finally:
        conn.close()


def kpis(db_path: Path, tenant: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        out = []
        for k in _objects(conn, "KPI"):
            if k.get("tenant") != tenant:
                continue
            k["measurements"] = _measurements(conn, "kpi_measurements", k["id"])
            out.append(k)
        out.sort(key=lambda k: k.get("title", ""))
        return out
    finally:
        conn.close()


def reviews(db_path: Path, tenant: str, status: Optional[str] = "approved", limit: int = 8) -> list[dict]:
    conn = _connect(db_path)
    try:
        rs = [r for r in _objects(conn, "Review") if r.get("tenant") == tenant and (status is None or r.get("status") == status)]
        rs.sort(key=lambda r: r.get("week", ""), reverse=True)
        return rs[:limit]
    finally:
        conn.close()


def tenant_summary(db_path: Path, tenant: str) -> dict:
    """Counts for a roll-up tile: objectives by status, KRs and KPIs by status."""
    conn = _connect(db_path)
    try:
        objs = [o for o in _objects(conn, "Objective") if o.get("tenant") == tenant]
        kr_status: dict[str, int] = {}
        for o in objs:
            for kr in _by_id(conn, _children(conn, "key_results", o["id"])):
                s = kr.get("status") or "unknown"
                kr_status[s] = kr_status.get(s, 0) + 1
        kpi_status: dict[str, int] = {}
        for k in _objects(conn, "KPI"):
            if k.get("tenant") == tenant:
                s = k.get("status") or "unknown"
                kpi_status[s] = kpi_status.get(s, 0) + 1
        obj_status: dict[str, int] = {}
        for o in objs:
            s = o.get("status") or "draft"
            obj_status[s] = obj_status.get(s, 0) + 1
        return {"objectives": obj_status, "key_results": kr_status, "kpis": kpi_status}
    finally:
        conn.close()
