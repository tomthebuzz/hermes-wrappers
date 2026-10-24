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

os.environ.update({"KANBAN_DB_PATH": str(DB), "KANBAN_ATTACHMENTS_ROOT": str(ATTACH), "USERS_YAML_PATH": str(USERS),
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
