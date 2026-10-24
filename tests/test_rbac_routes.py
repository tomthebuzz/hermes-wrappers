"""The Portal is the security boundary in front of a board whose tenants are
only labels: every route must refuse what a user's scope does not allow."""
from __future__ import annotations

import pytest

from conftest import client_as


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/board"), ("GET", "/api/tasks/t_tech1"), ("GET", "/api/artifacts"),
    ("GET", "/api/attachments/1"), ("POST", "/api/tasks/t_tech1/comments"), ("GET", "/api/profile"),
])
def test_every_api_route_needs_a_session(calls, method, path):
    r = client_as(None).request(method, path, json={"text": "x"})
    assert r.status_code == 401


def test_a_forged_or_unknown_session_gets_nothing(calls):
    c = client_as(None)
    c.cookies.set("portal_session", "forged.value.sig")
    assert c.get("/api/board").status_code == 401
    assert client_as("999").get("/api/board").status_code == 403


def test_board_is_scoped_to_the_users_tenants(alice, rolly):
    assert {t["tenant"] for t in alice.get("/api/board").json()["tasks"]} == {"tech"}
    assert {t["tenant"] for t in rolly.get("/api/board").json()["tasks"]} == {"tech", "sales", "ops"}


@pytest.mark.parametrize("path", ["/api/tasks/t_sales1", "/api/attachments/2"])
def test_other_tenants_tasks_and_files_are_invisible(alice, path):
    assert alice.get(path).status_code in (403, 404)


def test_own_attachment_is_served_from_the_mounted_root(alice):
    r = alice.get("/api/attachments/1")
    assert r.status_code == 200 and r.text == "contents of report.md"


@pytest.mark.parametrize("call", [
    lambda c: c.post("/api/tasks/t_sales1/comments", json={"text": "hi"}),
    lambda c: c.patch("/api/tasks/t_sales1", json={"title": "x"}),
    lambda c: c.post("/api/tasks/t_sales1/transition", json={"status": "running"}),
    lambda c: c.post("/api/tasks/t_sales1/claim"),
    lambda c: c.post("/api/tasks/t_sales1/attachments", files={"file": ("a.txt", b"x")}),
    lambda c: c.post("/api/tasks", json={"title": "x", "tenant": "sales", "status": "ready"}),
    lambda c: c.post("/api/artifacts/publish", json={"task_id": "t_sales1"}),
])
def test_writes_outside_scope_are_refused_and_never_reach_hermes(alice, calls, call):
    assert call(alice).status_code == 403
    assert calls == []


def test_completing_needs_review_rights(bob, calls):
    assert bob.post("/api/tasks/t_sales1/transition", json={"status": "done"}).status_code == 403
    assert bob.post("/api/tasks", json={"title": "x", "tenant": "sales", "status": "done"}).status_code == 403
    assert calls == []


def test_review_needs_approval_rights_even_with_read_access(bob, rolly, calls):
    assert bob.post("/api/artifacts/review", json={"task_id": "t_sales1", "approve": True}).status_code == 403
    # Rollup reads everything but approves only leadership.
    assert rolly.post("/api/artifacts/review", json={"task_id": "t_tech1", "approve": True}).status_code == 403
    assert calls == []


def test_reject_credits_the_reviewer(alice, calls):
    r = alice.post("/api/artifacts/review", json={"task_id": "t_tech1", "approve": False, "note": "fix it"})
    assert r.status_code == 200
    assert calls == [("reject_artifact", ("t_tech1", "fix it"), {"author": "Alice Tech"})]


def test_uploads_and_comments_are_attributed(alice, calls):
    alice.post("/api/tasks/t_tech1/comments", json={"text": "hello"})
    alice.post("/api/tasks/t_tech1/attachments", files={"file": ("a.txt", b"data", "text/plain")})
    assert calls[0] == ("comment_task", ("t_tech1", "hello"), {"author": "Alice Tech"})
    assert calls[1][0] == "upload_attachment" and calls[1][2]["author"] == "Alice Tech"


def test_upload_limits(alice, calls):
    assert alice.post("/api/tasks/t_tech1/attachments", files={"file": ("e.txt", b"")}).status_code == 400
    big = b"x" * (25 * 1024 * 1024 + 1)
    assert alice.post("/api/tasks/t_tech1/attachments", files={"file": ("b.bin", big)}).status_code == 413
    assert calls == []


def test_claim_only_from_ready(alice, calls):
    assert alice.post("/api/tasks/t_tech1/claim").status_code == 409   # in review
    assert alice.post("/api/tasks/t_tech2/claim").status_code == 200


def test_artifact_queue_is_scoped_and_flags_review_rights(alice, rolly, mia):
    assert [(t["id"], t["can_review"]) for t in alice.get("/api/artifacts").json()["tasks"]] == [("t_tech1", True)]
    rolly_view = {t["id"]: t["can_review"] for t in rolly.get("/api/artifacts").json()["tasks"]}
    assert rolly_view == {"t_tech1": False, "t_ops1": False}
    assert [t["id"] for t in mia.get("/api/artifacts").json()["tasks"]] == ["t_ops1"]


def test_review_deadline_from_marker_or_hand_off(alice, mia):
    # t_tech1 has no marker: deadline = review_requested + default 48 h.
    assert alice.get("/api/tasks/t_tech1").json()["sla_deadline"] == "2026-09-23T14:13:20Z"  # 1_790_000_000 + 48 h
    assert mia.get("/api/tasks/t_ops1").json()["sla_deadline"] == "2030-01-01T00:00:00Z"


def test_assignees_come_from_the_bridge(alice):
    assert alice.get("/api/assignees").json() == {"assignees": ["ops", "tech"]}


def test_matrix_only_user_cannot_edit_a_telegram_handle(mia):
    assert mia.patch("/api/profile", json={"telegram_username": "mia"}).status_code == 409
    assert mia.get("/api/profile").json()["matrix_id"] == "@mia:hs.test"


def test_index_is_never_cached(calls):
    assert client_as(None).get("/").headers["cache-control"] == "no-cache"


def test_approval_credits_the_approver(alice, calls):
    assert alice.post("/api/artifacts/review", json={"task_id": "t_tech1", "approve": True, "note": "ok"}).status_code == 200
    assert calls == [("approve_artifact", ("t_tech1", "ok"), {"author": "Alice Tech"})]


def test_drag_to_done_credits_the_approver(alice, calls):
    assert alice.post("/api/tasks/t_tech2/transition", json={"status": "done"}).status_code == 200
    assert calls[0][0] == "transition_task" and calls[0][2] == {"author": "Alice Tech"}


def test_autonomy_level_drives_deadline_and_label(alice, monkeypatch, tmp_path):
    import json, sqlite3
    from conftest import DB
    ladder = tmp_path / "autonomy.yaml"
    ladder.write_text("defaults: {level: 1, veto_window_hours: 24}\nskills:\n  research: {level: 3, ceiling: 4}\n")
    monkeypatch.setenv("AUTONOMY_PATH", str(ladder))
    with sqlite3.connect(DB) as conn:
        conn.execute("UPDATE tasks SET skills=? WHERE id='t_tech1'", (json.dumps(["research"]),))
    try:
        card = alice.get("/api/artifacts").json()["tasks"][0]
        assert card["autonomy_level"] == 3
        assert card["sla_deadline"] == "2026-09-22T14:13:20Z"   # hand-off + 24 h veto window
        monkeypatch.delenv("AUTONOMY_PATH")
        assert alice.get("/api/artifacts").json()["tasks"][0]["autonomy_level"] is None
    finally:
        with sqlite3.connect(DB) as conn:
            conn.execute("UPDATE tasks SET skills=NULL WHERE id='t_tech1'")
