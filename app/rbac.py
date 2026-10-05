"""
RBAC — the one place that decides who sees what.

Loads users.yaml and answers: "can telegram_user_id X read tenant Y?",
"can they approve artifacts in tenant Y?", "do they get the rollup (all
tenants) view?". Every route in main.py must call through here before
touching kanban data — this module is the actual security boundary this
whole app exists to provide (Hermes/Kanban itself only has soft, label-level
tenant scoping, not real access control; see repo README).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import yaml


@dataclasses.dataclass(frozen=True)
class UserScope:
    telegram_user_id: int
    name: str
    role: str
    tenants: tuple
    can_rollup: bool
    can_approve_artifacts: tuple

    def can_read_tenant(self, tenant: str) -> bool:
        return self.can_rollup or tenant in self.tenants

    def can_approve_tenant(self, tenant: str) -> bool:
        return tenant in self.can_approve_artifacts

    def readable_tenants(self, all_tenants: list) -> list:
        """Tenant list to actually query for this user — None-safe caller
        passes the full board tenant list; we narrow it down here."""
        if self.can_rollup:
            return list(all_tenants)
        return [t for t in all_tenants if t in self.tenants]


class RBAC:
    def __init__(self, users_yaml_path: Path):
        self._path = users_yaml_path
        self._by_id: dict[int, UserScope] = {}
        self.reload()

    def reload(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"{self._path} not found — copy users.yaml.example to users.yaml "
                "and fill in real Telegram user IDs before starting the portal."
            )
        data = yaml.safe_load(self._path.read_text()) or {}
        by_id: dict[int, UserScope] = {}
        for entry in data.get("users", []):
            scope = UserScope(
                telegram_user_id=int(entry["telegram_user_id"]),
                name=entry.get("name", "Unknown"),
                role=entry.get("role", "member"),
                tenants=tuple(entry.get("tenants", [])),
                can_rollup=bool(entry.get("can_rollup", False)),
                can_approve_artifacts=tuple(entry.get("can_approve_artifacts", [])),
            )
            by_id[scope.telegram_user_id] = scope
        self._by_id = by_id

    def get(self, telegram_user_id: int) -> Optional[UserScope]:
        # Fail closed: unknown users get None, callers must treat that as
        # zero access, never as "admin" or "fall back to defaults that grant
        # anything."
        return self._by_id.get(telegram_user_id)
