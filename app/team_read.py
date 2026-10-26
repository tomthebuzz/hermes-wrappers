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


def tenant_of(db_path: Path, object_id: str) -> Optional[str]:
    """The tenant an object belongs to: its own `tenant` (Objective, KPI,
    Source) or, for a KeyResult, its objective's. None when unknown."""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT type, data FROM objects WHERE id = ?", (object_id,)).fetchone()
        if row is None:
            return None
        data = json.loads(row["data"])
        if row["type"] == "KeyResult":
            parent = conn.execute("SELECT from_id FROM links WHERE rel = 'key_results' AND to_id = ?", (object_id,)).fetchone()
            if parent is None:
                return None
            prow = conn.execute("SELECT data FROM objects WHERE id = ?", (parent["from_id"],)).fetchone()
            return json.loads(prow["data"]).get("tenant") if prow else None
        return data.get("tenant")
    finally:
        conn.close()


def task_links(db_path: Path, task_id: str) -> list[dict]:
    """The card's stakeholders (TaskLink) with the key result each one's
    link serves, if any."""
    conn = _connect(db_path)
    try:
        out = []
        for link in _objects(conn, "TaskLink"):
            if link.get("task_id") != task_id:
                continue
            kr_ids = _children(conn, "serves", link["id"])
            krs = _by_id(conn, kr_ids)
            link["serves"] = [{"id": k["id"], "title": k.get("title")} for k in krs]
            out.append(link)
        order = {"owner": 0, "reviewer": 1, "watcher": 2}
        out.sort(key=lambda l: (order.get(l.get("role"), 9), l.get("person", "")))
        return out
    finally:
        conn.close()


def task_thread(db_path: Path, task_id: str) -> Optional[dict]:
    conn = _connect(db_path)
    try:
        for t in _objects(conn, "TaskThread"):
            if t.get("task_id") == task_id:
                return {"room_id": t.get("room_id"), "event_id": t.get("event_id")}
        return None
    finally:
        conn.close()


def key_results_of_tenant(db_path: Path, tenant: str) -> list[dict]:
    """Active objectives' key results, for the "serves" picker."""
    out = []
    for o in objectives(db_path, tenant):
        if o.get("status") == "closed":
            continue
        for kr in o.get("key_results", []):
            out.append({"id": kr["id"], "title": kr.get("title"), "objective": o.get("title")})
    return out


def tasks_serving(db_path: Path, tenant: str) -> dict:
    """key result id -> [task ids] for the dashboard."""
    conn = _connect(db_path)
    try:
        by_kr: dict[str, list] = {}
        for link in _objects(conn, "TaskLink"):
            for kr in _children(conn, "serves", link["id"]):
                by_kr.setdefault(kr, []).append(link["task_id"])
        return by_kr
    finally:
        conn.close()


def sources(db_path: Path, tenant: str) -> list[dict]:
    """Registered sources of a tenant (never a secret: only its name)."""
    conn = _connect(db_path)
    try:
        out = [x for x in _objects(conn, "Source") if x.get("tenant") == tenant]
        out.sort(key=lambda x: x.get("name", ""))
        return out
    finally:
        conn.close()


def swimlanes(db_path: Path, tenant: str, include_archived: bool = False) -> list[dict]:
    """A team's lanes in board order (lowest `order` first, then name)."""
    conn = _connect(db_path)
    try:
        out = [x for x in _objects(conn, "Swimlane") if x.get("tenant") == tenant
               and (include_archived or x.get("status", "active") != "archived")]
        out.sort(key=lambda x: (float(x.get("order") or 0), (x.get("name") or "").lower()))
        return out
    finally:
        conn.close()


def task_lanes(db_path: Path) -> dict:
    """task id -> {"id": TaskLane object id, "lane": Swimlane id}. One lane
    per card; the newest record wins if a card ever has two."""
    conn = _connect(db_path)
    try:
        out: dict[str, dict] = {}
        for x in reversed(_objects(conn, "TaskLane")):      # oldest first, newest overwrites
            if x.get("task_id") and x.get("lane"):
                out[x["task_id"]] = {"id": x["id"], "lane": x["lane"]}
        return out
    finally:
        conn.close()


def task_links_many(db_path: Path) -> dict:
    """task id -> stakeholders (person, matrix_id, role), for lists."""
    conn = _connect(db_path)
    try:
        out: dict[str, list] = {}
        for link in _objects(conn, "TaskLink"):
            if link.get("task_id"):
                out.setdefault(link["task_id"], []).append(
                    {"id": link["id"], "person": link.get("person"), "matrix_id": link.get("matrix_id"), "role": link.get("role")})
        return out
    finally:
        conn.close()
