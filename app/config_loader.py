"""
Loads the shared tenants.yaml / sla-defaults.yaml config — same files that
live in the hermes-team-bots repo's config/ dir. In K8s both services mount
these from the SAME ConfigMap (see infra/configmap.yaml) so they can't
drift. Locally, team-portal keeps its own copy under config/ — keep it in
sync by hand with hermes-team-bots/config/ until a shared package exists.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

CONFIG_DIR = Path(os.environ.get("SHARED_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config"))


def load_tenants() -> dict:
    return yaml.safe_load((CONFIG_DIR / "tenants.yaml").read_text())["tenants"]


def load_sla_defaults() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sla-defaults.yaml").read_text())


def default_sla_hours() -> float:
    return float(load_sla_defaults().get("default_hours", 48))


def on_miss_direction(tenant: str) -> str:
    return load_sla_defaults().get("on_miss_by_tenant", {}).get(tenant, "reject")
