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


def load_autonomy() -> dict:
    """The client's autonomy ladder (harness-kit clients/<client>/autonomy.yaml,
    mounted at AUTONOMY_PATH); {} when not configured."""
    path = os.environ.get("AUTONOMY_PATH")
    if not path or not Path(path).exists():
        return {}
    return yaml.safe_load(Path(path).read_text()) or {}


def autonomy_level(skills: list) -> int | None:
    """Lowest level among the skills (the most careful wins, same rule as
    hermes-team's SLA sweep); None without skills or without a ladder."""
    ladder = load_autonomy()
    if not ladder or not skills:
        return None
    default = (ladder.get("defaults") or {}).get("level", 1)
    return min(int(((ladder.get("skills") or {}).get(s) or {}).get("level", default)) for s in skills)


def veto_window_hours() -> float:
    return float((load_autonomy().get("defaults") or {}).get("veto_window_hours", 24))


def default_sla_hours() -> float:
    return float(load_sla_defaults().get("default_hours", 48))


def on_miss_direction(tenant: str) -> str:
    return load_sla_defaults().get("on_miss_by_tenant", {}).get(tenant, "reject")
