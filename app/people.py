"""People management for the Portal's People page: add a person, change
their tenants, remove them. The Portal decides who may do what (see the
rules in main.py); the change itself (Matrix account, room membership, bot
allowlists, users.yaml) is made on the host by hermes-bridge's /people hook.
Bridge mode only: there is no direct-CLI fallback for this."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

BRIDGE_URL = os.environ.get("HERMES_BRIDGE_URL")
BRIDGE_API_KEY = os.environ.get("HERMES_BRIDGE_API_KEY")
TIMEOUT = float(os.environ.get("PEOPLE_TIMEOUT", "200"))   # the hook restarts the gateway


@dataclass
class Result:
    ok: bool
    data: dict = field(default_factory=dict)
    error: str = ""


def _call(method: str, path: str, body: dict | None = None) -> Result:
    if not BRIDGE_URL:
        return Result(False, error="people management needs HERMES_BRIDGE_URL")
    headers = {"X-API-Key": BRIDGE_API_KEY} if BRIDGE_API_KEY else {}
    try:
        resp = httpx.request(method, f"{BRIDGE_URL}/people{path}", json=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        return Result(False, error=f"bridge request failed: {e}")
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code >= 300:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        return Result(False, error=str(detail or resp.text)[:300])
    return Result(True, payload if isinstance(payload, dict) else {})


def add(localpart: str, name: str, tenants: list[str], approve: list[str]) -> Result:
    return _call("POST", "", {"localpart": localpart, "name": name, "tenants": tenants, "approve": approve})


def update(localpart: str, tenants: list[str], approve: list[str]) -> Result:
    return _call("PUT", f"/{localpart}", {"tenants": tenants, "approve": approve})


def remove(localpart: str) -> Result:
    return _call("DELETE", f"/{localpart}")
