"""
Read-only access to the Hermes board's kanban.db.

Verified against the live Hermes Kanban schema pasted from the Mac mini:
  - tasks has no updated_at column; we synthesize one from the latest
    task_events.created_at, falling back to completed_at/started_at/created_at.
  - task_comments stores its text in `body`, not `text`; list_comments()
    aliases body AS text so the rest of the app can use one stable key.

All writes still go through hermes-bridge / `hermes kanban`, never raw SQL.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional


def _connect(db_path: Path, attempts: int = 8) -> sqlite3.Connection:
    # Read-only URI connection — refuses to write even if a query tried to.
    # A read-only WAL reader cannot create kanban.db-wal/-shm, so opening in
    # the instant a host writer's last connection checkpoints and swaps them
    # fails with "unable to open database file"; through Docker's file
    # sharing that window is long enough to hit right after a board move.
    uri = f"file:{db_path}?mode=ro"
    for attempt in range(attempts):
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except sqlite3.OperationalError as e:
            conn.close()
            if "unable to open" not in str(e) or attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))
            continue
        conn.row_factory = sqlite3.Row
        return conn
    raise AssertionError("unreachable")


def list_tasks(db_path: Path, tenants: Optional[list] = None, status: Optional[str] = None) -> list[dict]:
    """tenants=None means no tenant filter (rollup view); an empty list means
    no tenants at all, i.e. nothing — never "everything"."""
    if tenants is not None and not tenants:
        return []
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
        if tenants is not None:
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


def latest_event_at(db_path: Path, task_id: str, kind: str) -> Optional[int]:
    """Unix time of the task's newest event of this kind (e.g. review_requested)."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT MAX(created_at) AS at FROM task_events WHERE task_id = ? AND kind = ?",
            (task_id, kind),
        ).fetchone()
        return row["at"] if row and row["at"] is not None else None
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

def list_all_attachments(db_path: Path, tenants: Optional[list]) -> list[dict]:
    """Every attachment of the tenants' cards with the card's title, status,
    team, assignee and creator; newest first. tenants=None: all; []: none."""
    if tenants is not None and not tenants:
        return []
    conn = _connect(db_path)
    try:
        sql = """SELECT a.id, a.task_id, a.filename, a.content_type, a.size, a.uploaded_by, a.created_at,
                        t.title AS task_title, t.status, t.tenant, t.assignee, t.created_by
                 FROM task_attachments a JOIN tasks t ON t.id = a.task_id"""
        params: list = []
        if tenants is not None:
            sql += " WHERE t.tenant IN (%s)" % ",".join("?" for _ in tenants)
            params.extend(tenants)
        sql += " ORDER BY a.created_at DESC, a.id DESC"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
