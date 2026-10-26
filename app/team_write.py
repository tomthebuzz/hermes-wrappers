"""
Writes to the team store (objectives, key results, KPIs, check-ins) go
through hermes-bridge's /okr routes, like Kanban writes go through /kanban:
the bridge runs the store's CLI, the store validates and audits with the
person as actor. No direct write to the store from this container.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

BRIDGE_URL = os.environ.get("HERMES_BRIDGE_URL")
BRIDGE_API_KEY = os.environ.get("HERMES_BRIDGE_API_KEY")
BRIDGE_TIMEOUT = float(os.environ.get("HERMES_BRIDGE_TIMEOUT", "60"))
SANITIZED_NOTICE = "Hidden (invisible) characters were removed from your text."


@dataclass
class StoreResult:
    ok: bool
    object: dict = field(default_factory=dict)
    error: str = ""
    notice: str = ""


def _post(path: str, body: dict) -> StoreResult:
    if not BRIDGE_URL:
        return StoreResult(False, error="HERMES_BRIDGE_URL is not set; the dashboard cannot write")
    headers = {"X-API-Key": BRIDGE_API_KEY} if BRIDGE_API_KEY else {}
    try:
        resp = httpx.post(f"{BRIDGE_URL}{path}", json=body, headers=headers, timeout=BRIDGE_TIMEOUT)
    except httpx.HTTPError as e:
        return StoreResult(False, error=f"bridge request failed: {e}")
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code >= 300:
        detail = payload.get("detail", resp.text) if isinstance(payload, dict) else resp.text
        if isinstance(detail, dict):
            detail = detail.get("detail", detail)
        return StoreResult(False, error=str(detail)[:500])
    return StoreResult(True, object=payload.get("object", {}) if isinstance(payload, dict) else {},
                       notice=SANITIZED_NOTICE if isinstance(payload, dict) and payload.get("sanitized") else "")


def upsert(type_name: str, data: dict, actor: str, reason: str, object_id: str | None = None,
           objective_id: str | None = None) -> StoreResult:
    body = {"type": type_name, "data": data, "actor": actor, "reason": reason}
    if object_id:
        body["id"] = object_id
    if objective_id:
        body["objective_id"] = objective_id
    return _post("/okr/objects", body)


def delete(object_id: str, actor: str, reason: str) -> StoreResult:
    return _post(f"/okr/objects/{object_id}/delete", {"actor": actor, "reason": reason})


def checkin(target_id: str, value: float, actor: str, reason: str, note: str = "") -> StoreResult:
    return _post("/okr/checkin", {"target_id": target_id, "value": value, "note": note, "actor": actor, "reason": reason})


def link(rel: str, from_id: str, to_id: str, actor: str, reason: str) -> StoreResult:
    return _post("/okr/links", {"rel": rel, "from_id": from_id, "to_id": to_id, "actor": actor, "reason": reason})


def move(object_id: str, tenant: str, actor: str, reason: str) -> StoreResult:
    return _post(f"/okr/objects/{object_id}/move", {"tenant": tenant, "actor": actor, "reason": reason})
