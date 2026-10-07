"""
RBAC — the one place that decides who sees what.

Loads users.yaml and answers: "can user X read tenant Y?", "can they
approve artifacts in tenant Y?", "do they get the rollup (all tenants)
view?". Every route in main.py must call through here before touching
kanban data — this module is the actual security boundary this app exists
to provide (Hermes/Kanban itself only has soft, label-level tenant scoping).

Identity is user-facing by Telegram @username, but delivery remains best
with numeric chat/user IDs: Telegram bots generally cannot start arbitrary
DMs to a @username unless the user has already started the bot. users.yaml
therefore supports both:
  - telegram_username: user-facing login handle ("@alice" or "alice")
  - telegram_user_id: stable numeric ID used for the session key
  - telegram_chat_id: optional delivery target; defaults to telegram_user_id
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import yaml


def normalize_username(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    if v.startswith("@"):
        v = v[1:]
    return v.lower()


@dataclasses.dataclass(frozen=True)
class UserScope:
    telegram_user_id: int
    name: str
    role: str
    tenants: tuple
    can_rollup: bool
    can_approve_artifacts: tuple
    telegram_username: str | None = None
    telegram_chat_id: str | None = None

    @property
    def delivery_target(self) -> str:
        # Reliable path: numeric chat/user id. If a deployment explicitly
        # wants to try @username delivery, set telegram_chat_id to that handle
        # in users.yaml; otherwise use the numeric user id.
        return str(self.telegram_chat_id or self.telegram_user_id)

    def can_read_tenant(self, tenant: str) -> bool:
        return self.can_rollup or tenant in self.tenants

    def can_approve_tenant(self, tenant: str) -> bool:
        return tenant in self.can_approve_artifacts

    def readable_tenants(self, all_tenants: list) -> list:
        if self.can_rollup:
            return list(all_tenants)
        return [t for t in all_tenants if t in self.tenants]


class RBAC:
    def __init__(self, users_yaml_path: Path):
        self._path = users_yaml_path
        self._by_id: dict[int, UserScope] = {}
        self._by_username: dict[str, UserScope] = {}
        self.reload()

    def reload(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"{self._path} not found — copy users.yaml.example to users.yaml "
                "and fill in real Telegram IDs/usernames before starting the portal."
            )
        data = yaml.safe_load(self._path.read_text()) or {}
        by_id: dict[int, UserScope] = {}
        by_username: dict[str, UserScope] = {}
        for entry in data.get("users", []):
            username = normalize_username(entry.get("telegram_username"))
            scope = UserScope(
                telegram_user_id=int(entry["telegram_user_id"]),
                telegram_username=username,
                telegram_chat_id=str(entry.get("telegram_chat_id")) if entry.get("telegram_chat_id") else None,
                name=entry.get("name", "Unknown"),
                role=entry.get("role", "member"),
                tenants=tuple(entry.get("tenants", [])),
                can_rollup=bool(entry.get("can_rollup", False)),
                can_approve_artifacts=tuple(entry.get("can_approve_artifacts", [])),
            )
            by_id[scope.telegram_user_id] = scope
            if username:
                by_username[username] = scope
        self._by_id = by_id
        self._by_username = by_username

    def get(self, telegram_user_id: int) -> Optional[UserScope]:
        return self._by_id.get(telegram_user_id)

    def resolve_login(self, login: str) -> Optional[UserScope]:
        """Resolve a login string: @username preferred, numeric ID accepted
        for backwards compatibility and recovery."""
        raw = str(login).strip()
        if not raw:
            return None
        username = normalize_username(raw)
        if username and not raw.isdigit():
            return self._by_username.get(username)
        try:
            return self._by_id.get(int(raw))
        except ValueError:
            return self._by_username.get(username) if username else None
