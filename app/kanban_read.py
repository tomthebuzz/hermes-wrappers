"""
Read-only access to ~/.hermes/kanban.db.

Verified against the live Hermes Kanban schema pasted from the Mac mini:
  - tasks has no updated_at column; we synthesize one from the latest
    task_events.created_at, falling back to completed_at/started_at/created_at.
  - task_comments stores its text in `body`, not `text`; list_comments()
    aliases body AS text so the rest of the app can use one stable key.

All writes still go through hermes-bridge / `hermes kanban`, never raw SQL.
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
        sql = """
            SELECT
                t.*,
                COALESCE(
                    (SELECT MAX(e.created_at) FROM task_events e WHERE e.task_id = t.id),
                    t.completed_at,
                    t.started_at,
                    t.created_at
                ) AS updated_at
            FROM tasks t
            WHERE 1=1
        """
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
        row = conn.execute("""
            SELECT
                t.*,
                COALESCE(
                    (SELECT MAX(e.created_at) FROM task_events e WHERE e.task_id = t.id),
                    t.completed_at,
                    t.started_at,
                    t.created_at
                ) AS updated_at
            FROM tasks t
            WHERE t.id = ?
        """, (task_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_comments(db_path: Path, task_id: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                task_id,
                author,
                body,
                body AS text,
                created_at
            FROM task_comments
            WHERE task_id = ?
            ORDER BY created_at ASC
            """,
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


def list_attachments(db_path: Path, task_id: str) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """SELECT id, task_id, filename, content_type, size, uploaded_by, created_at
               FROM task_attachments WHERE task_id = ? ORDER BY created_at ASC""",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_attachment(db_path: Path, attachment_id: int) -> Optional[dict]:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, task_id, filename, stored_path, content_type, size, uploaded_by, created_at FROM task_attachments WHERE id = ?",
            (attachment_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()