"""
Read-only access to ~/.hermes/kanban.db.

UNVERIFIED SCHEMA: the actual table/column names for kanban.db were not
published in the docs excerpts available when this was written (the docs
describe the CLI/tool/REST surface, not the raw SQLite schema). The queries
below are a best-effort guess at a plausible schema (a `tasks` table with
id/title/status/tenant/assignee/body/created_at/updated_at columns, plus a
`task_events` append-only table). BEFORE WIRING THIS UP FOR REAL:

    sqlite3 ~/.hermes/kanban.db ".schema"

and fix every query in this file to match the actual column names. This
module is deliberately isolated so that fix is a single-file change.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def _connect(db_path: Path) -> sqlite3.Connection:
    # Read-only URI connection — refuses to write even if a query tried to.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def list_tasks(db_path: Path, tenants: Optional[list] = None, status: Optional[str] = None) -> list[dict]:
    """tenants=None means no tenant filter (rollup view)."""
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if tenants:
            placeholders = ",".join("?" for _ in tenants)
            sql += f" AND tenant IN ({placeholders})"
            params.extend(tenants)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC"
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_task(db_path: Path, task_id: str) -> Optional[dict]:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_comments(db_path: Path, task_id: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def distinct_tenants(db_path: Path) -> list[str]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT tenant FROM tasks WHERE tenant IS NOT NULL ORDER BY tenant"
        ).fetchall()
        return [r["tenant"] for r in rows]
    finally:
        conn.close()
