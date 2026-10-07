#!/usr/bin/env python3
"""Create three clearly-labelled review artifacts through hermes-bridge.

Run only when intentionally seeding the live board:
  HERMES_BRIDGE_URL=http://127.0.0.1:8765 \
  HERMES_BRIDGE_API_KEY=... KANBAN_DB_PATH=~/.hermes/kanban.db \
  python3 scripts/seed_demo_artifacts.py --confirm

This script never writes SQLite. It uses the bridge for create/comment/review
transitions. Seeded items use the existing `marketing` tenant so there is no
extra demo tenant; they are visible only to users allowed to see that tenant.
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


def existing_titles(db_path: Path) -> set[str]:
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {row[0] for row in conn.execute("SELECT title FROM tasks WHERE title LIKE 'DEMO · %'")}
    finally:
        conn.close()


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
    raise RuntimeError(f"Could not extract task ID from bridge create response: {detail[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true", help="confirm creation of live test cards")
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
    known = existing_titles(db_path)
    headers = {"X-API-Key": key}
    created = []
    with httpx.Client(base_url=base, headers=headers, timeout=30) as client:
        for title, body, sla_hours in SAMPLES:
            if title in known:
                print(f"skip existing: {title}")
                continue
            r = client.post("/kanban/tasks", json={"title": title, "tenant": args.tenant, "body": body})
            r.raise_for_status()
            task_id = task_id_from_detail(r.json().get("detail", ""))
            deadline = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=sla_hours)).isoformat().replace("+00:00", "Z")
            for text in ("DEMO-ARTIFACT: yes", f"SLA-DEADLINE: {deadline}"):
                c = client.post(f"/kanban/tasks/{task_id}/comments", json={"text": text, "author": "demo-seeder"})
                c.raise_for_status()
            pub = client.post(f"/kanban/tasks/{task_id}/publish-for-review", json={"summary": f"Demo/test artifact; SLA target approximately {sla_hours}h."})
            pub.raise_for_status()
            print(f"created {task_id}: {title} [{args.tenant}] → review")
            created.append(task_id)
    print(f"done: {len(created)} created; {len(SAMPLES)-len(created)} already existed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
