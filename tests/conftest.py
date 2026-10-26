"""Portal tests: a temporary kanban.db (real Hermes schema), a users.yaml with
one user per RBAC shape, and every kanban_write call recorded instead of
reaching hermes-bridge."""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

ROOT = Path(tempfile.mkdtemp(prefix="portal-tests-"))
DB = ROOT / "kanban.db"
ATTACH = ROOT / "attachments"
USERS = ROOT / "users.yaml"

USERS.write_text("""
users:
  - telegram_username: alice
    telegram_user_id: 101
    name: "Alice Tech"
    role: tech
    tenants: [tech]
    can_rollup: false
    can_approve_artifacts: [tech]
  - telegram_username: bob
    telegram_user_id: 102
    name: "Bob Sales"
    role: sales
    tenants: [sales]
    can_rollup: false
    can_approve_artifacts: []
  - telegram_username: rolly
    telegram_user_id: 103
    name: "Rolly Lead"
    role: ceo
    tenants: [leadership]
    can_rollup: true
    can_approve_artifacts: [leadership]
  - matrix_id: "@Mia:hs.test"
    name: "Mia Ops"
    role: ops
    tenants: [ops]
    can_rollup: false
    can_approve_artifacts: [ops]
  - matrix_id: "@own:hs.test"
    name: "Owen Owner"
    role: owner
    tenants: [tech, sales, ops, leadership]
    can_rollup: true
    can_approve_artifacts: [tech, sales, ops, leadership]
    can_manage_people: true
  - matrix_id: "@lead:hs.test"
    name: "Lea Lead"
    role: member
    tenants: [tech, sales]
    can_rollup: false
    can_approve_artifacts: [tech]
    can_manage_people: true
  - matrix_id: "@tim:hs.test"
    name: "Tim Tech"
    role: member
    tenants: [tech]
    can_rollup: false
    can_approve_artifacts: []
  - matrix_id: "@sam:hs.test"
    name: "Sam Wide"
    role: member
    tenants: [sales, ops]
    can_rollup: false
    can_approve_artifacts: []
defaults:
  unknown_user_tenants: []
  unknown_user_can_rollup: false
""")

conn = sqlite3.connect(DB)
conn.executescript((Path(__file__).parent / "kanban_schema.sql").read_text())
now = 1_790_000_000
for tid, tenant, status in [("t_tech1", "tech", "review"), ("t_tech2", "tech", "ready"),
                            ("t_sales1", "sales", "ready"), ("t_ops1", "ops", "review")]:
    conn.execute("INSERT INTO tasks(id, title, body, status, tenant, priority, created_by, created_at, workspace_kind)"
                 " VALUES (?,?,?,?,?,0,'user',?,'scratch')", (tid, f"Task {tid}", "body", status, tenant, now))
conn.execute("INSERT INTO task_events(task_id, kind, payload, created_at) VALUES ('t_tech1','review_requested','{}',?)", (now,))
conn.execute("INSERT INTO task_comments(task_id, author, body, created_at) VALUES ('t_ops1','x','SLA-DEADLINE: 2030-01-01T00:00:00Z',?)", (now,))
for aid, tid, name in [(1, "t_tech1", "report.md"), (2, "t_sales1", "deal.md")]:
    (ATTACH / tid).mkdir(parents=True, exist_ok=True)
    (ATTACH / tid / name).write_text(f"contents of {name}")
    conn.execute("INSERT INTO task_attachments(id, task_id, filename, stored_path, content_type, size, uploaded_by, created_at)"
                 " VALUES (?,?,?,?,?,?,?,?)", (aid, tid, name, f"/elsewhere/{tid}/{name}", "text/markdown", 10, "agent", now))
conn.commit()
conn.close()

# The team store (dashboard): objects + links as hermes-ontology keeps them.
TEAM_DB = ROOT / "team" / "ontology.db"
TEAM_DB.parent.mkdir()
tconn = sqlite3.connect(TEAM_DB)
tconn.executescript("CREATE TABLE objects(id TEXT PRIMARY KEY, type TEXT, data TEXT, lawful_basis TEXT, source TEXT,"
                    " created_at INTEGER, updated_at INTEGER, expires_at INTEGER);"
                    "CREATE TABLE links(rel TEXT, from_id TEXT, to_id TEXT, created_at INTEGER);")
import json as _json  # noqa: E402
for oid, ty, data in [
    ("obj_t1", "Objective", {"tenant": "tech", "title": "Ship faster", "period": "2026-Q4", "status": "active", "owner": "Alice"}),
    ("kr_t1", "KeyResult", {"title": "Cycle time", "start": 72, "target": 24, "current": 40, "unit": "h", "measure": "board",
                            "metric": "board.cycle_time_p50_h", "status": "at_risk"}),
    ("m_1", "Measurement", {"value": 60, "at": "2026-10-01T06:00:00Z", "method": "cron", "actor": "measure"}),
    ("m_2", "Measurement", {"value": 40, "at": "2026-10-08T06:00:00Z", "method": "cron", "actor": "measure"}),
    ("kpi_t1", "KPI", {"tenant": "tech", "title": "Throughput", "current": 5, "target": 4, "status": "ok", "measure": "board", "unit": "cards"}),
    ("kpi_s1", "KPI", {"tenant": "sales", "title": "Leads", "current": 2, "target": 10, "status": "crit", "measure": "manual"}),
    ("rev_t1", "Review", {"tenant": "tech", "week": "2026-W43", "status": "approved", "summary": "Cycle time fell."}),
    ("rev_t2", "Review", {"tenant": "tech", "week": "2026-W44", "status": "pending", "summary": "draft"}),
]:
    tconn.execute("INSERT INTO objects(id, type, data, source, created_at, updated_at) VALUES (?,?,?,'t',?,?)", (oid, ty, _json.dumps(data), now, now))
for rel, f, t in [("key_results", "obj_t1", "kr_t1"), ("kr_measurements", "kr_t1", "m_1"), ("kr_measurements", "kr_t1", "m_2")]:
    tconn.execute("INSERT INTO links VALUES (?,?,?,?)", (rel, f, t, now))
tconn.commit()
tconn.close()

os.environ.update({"KANBAN_DB_PATH": str(DB), "KANBAN_ATTACHMENTS_ROOT": str(ATTACH), "USERS_YAML_PATH": str(USERS), "TEAM_DB_PATH": str(TEAM_DB),
                   "SESSION_SECRET": "test-secret-0123456789", "PORTAL_BASE_URL": "http://portal.test",
                   "SHARED_CONFIG_DIR": str(Path(__file__).resolve().parents[1] / "config")})
os.environ.pop("HERMES_BRIDGE_URL", None)
os.environ.pop("PORTAL_AUTH_BACKEND", None)

from fastapi.testclient import TestClient  # noqa: E402

from app import kanban_write, main  # noqa: E402
from app.kanban_write import CLIResult  # noqa: E402

WRITES = ["create_task", "edit_task", "assign_task", "transition_task", "claim_task", "comment_task",
          "upload_attachment", "approve_artifact", "reject_artifact", "publish_artifact_for_review"]


@pytest.fixture
def calls(monkeypatch) -> list:
    recorded: list = []
    for name in WRITES:
        def fake(*args, _name=name, **kwargs):
            recorded.append((_name, args[1:], kwargs))  # drop hermes_bin
            return CLIResult(True, "ok", "")
        monkeypatch.setattr(kanban_write, name, fake)
    monkeypatch.setattr(kanban_write, "list_assignees", lambda: ["ops", "tech"])
    return recorded


def client_as(key: str | None) -> TestClient:
    c = TestClient(main.app)
    if key is not None:
        c.cookies.set(main.SESSION_COOKIE, main.signer.dumps(key))
    return c


@pytest.fixture
def alice(calls):
    return client_as("101")


@pytest.fixture
def bob(calls):
    return client_as("102")


@pytest.fixture
def rolly(calls):
    return client_as("103")


@pytest.fixture
def mia(calls):
    return client_as("@mia:hs.test")
