#!/usr/bin/env python3
"""Create or repair three clearly-labelled review artifacts through hermes-bridge.

Run only when intentionally seeding the live board:
  HERMES_BRIDGE_URL=http://127.0.0.1:8765 \
  HERMES_BRIDGE_API_KEY=... KANBAN_DB_PATH=~/.hermes/kanban.db \
  python3 scripts/seed_demo_artifacts.py --confirm

The script never writes SQLite. It reads task status/comments read-only, then uses
the bridge for creation, comments and review transitions. It re-attempts the
review transition for an existing demo task that is not yet in `review`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import httpx

SAMPLES = [
    ("DEMO · Q3 campaign brief", "TEST ARTIFACT — review workflow sample. Draft campaign brief for a fictional product launch. Please approve or request changes; this is not a real deliverable.", 48),
    ("DEMO · Sales enablement one-pager", "TEST ARTIFACT — review workflow sample. Fictional sales enablement copy with positioning, key benefits, and a sample call to action. Please comment, approve, or request changes.", 48),
    ("DEMO · Monthly marketing performance summary", "TEST ARTIFACT — review workflow sample. Synthetic monthly summary: reach up 12%, engagement up 4%, conversion unchanged. Numbers are invented for testing only.", 48),
]


def existing_demo_tasks(db_path: Path) -> dict[str, dict]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {r["title"]: dict(r) for r in conn.execute(
            "SELECT id, title, body, status FROM tasks WHERE title LIKE 'DEMO · %'"
        )}
    finally:
        conn.close()


def has_marker(db_path: Path, task_id: str, marker: str) -> bool:
    if not db_path.exists():
        return False
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT 1 FROM task_comments WHERE task_id = ? AND body LIKE ? LIMIT 1",
            (task_id, f"%{marker}%"),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def require_success(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        try:
            detail = response.json().get("detail", response.text)
        except (ValueError, AttributeError):
            detail = response.text
        print(f"Bridge returned HTTP {response.status_code}: {detail}", file=sys.stderr)
        print('Check `curl -H "X-API-Key: $HERMES_BRIDGE_API_KEY" http://127.0.0.1:8765/diagnostics` and the bridge logs.', file=sys.stderr)
        raise SystemExit(1)


def task_id_from_detail(detail: str) -> str:
    try:
        data = json.loads(detail)
        for key in ("id", "task_id"):
            if data.get(key):
                return str(data[key])
        if isinstance(data.get("task"), dict) and data["task"].get("id"):
            return str(data["task"]["id"])
    except (json.JSONDecodeError, AttributeError):
        pass
    match = re.search(r"\bt_[A-Za-z0-9_-]+\b", detail)
    if match:
        return match.group(0)
    raise RuntimeError(f"Could not extract task ID from bridge response: {detail[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="confirm creation/repair of live test cards")
    parser.add_argument("--tenant", default="marketing", choices=["tech", "marketing", "sales", "finance", "ops", "leadership"])
    args = parser.parse_args()
    if not args.confirm:
        parser.error("refusing to create live Kanban records without --confirm")
    base = os.environ.get("HERMES_BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")
    key = os.environ.get("HERMES_BRIDGE_API_KEY")
    if not key:
        print("HERMES_BRIDGE_API_KEY is required", file=sys.stderr)
        return 2
    db_path = Path(os.path.expanduser(os.environ.get("KANBAN_DB_PATH", "~/.hermes/kanban.db")))
    known = existing_demo_tasks(db_path)
    headers = {"X-API-Key": key}
    created = repaired = skipped = 0
    with httpx.Client(base_url=base, headers=headers, timeout=60) as client:
        for title, body, sla_hours in SAMPLES:
            current = known.get(title)
            if current and current["status"] == "review":
                print(f"already in review: {title} ({current['id']})")
                skipped += 1
                continue
            if current:
                task_id = str(current["id"])
                if current["status"] == "blocked":
                    un = client.post(f"/kanban/tasks/{task_id}/transition", json={"status": "todo"})
                    require_success(un)
                repaired += 1
                print(f"repairing existing demo task {task_id} from status={current['status']}: {title}")
            else:
                r = client.post("/kanban/tasks", json={
                    "title": title, "tenant": args.tenant, "body": body,
                    "status": "running", "priority": 1,
                })
                require_success(r)
                task_id = task_id_from_detail(r.json().get("detail", ""))
                created += 1
            deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=sla_hours)).isoformat().replace("+00:00", "Z")
            if not has_marker(db_path, task_id, "DEMO-ARTIFACT"):
                c = client.post(f"/kanban/tasks/{task_id}/comments", json={
                    "text": "DEMO-ARTIFACT: yes", "author": "demo-seeder"})
                require_success(c)
            if not has_marker(db_path, task_id, "SLA-DEADLINE"):
                c = client.post(f"/kanban/tasks/{task_id}/comments", json={
                    "text": f"SLA-DEADLINE: {deadline}", "author": "demo-seeder"})
                require_success(c)
            pub = client.post(f"/kanban/tasks/{task_id}/publish-for-review", json={
                "summary": f"Demo/test artifact; SLA target approximately {sla_hours}h."})
            require_success(pub)
            print(f"ready for review {task_id}: {title} [{args.tenant}]")
    print(f"done: {created} created, {repaired} repaired, {skipped} already in review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
