"""residents.json loading and validation."""

from __future__ import annotations

import json

DEFAULT_PORT = 9700

DEFAULT_POLICIES = {
    "check_interval_s": 30,   # watchdog cadence
    "fails_to_revive": 3,     # consecutive dead probes before a revive
    "revive_cooldown_s": 300, # per-resident revive cooldown (no machine-gunning)
    "ensure_timeout_s": 90,   # bounded wait for a cold-started resident
    "settle_timeout_s": 120,  # max wait for VRAM to settle after evictions
    "settle_poll_s": 3,       # settle poll cadence
    "baseline_gb": 0.5,       # CUDA contexts & always_on overhead
}

VALID_PROTOCOLS = ("process", "cooperative", "always_on")


def load_config(path):
    """Load and validate residents.json; raise ValueError on bad input."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    residents = cfg.get("residents") or {}
    if not residents:
        raise ValueError("config has no residents — nobody to look after")
    seen = set()
    for name, r in residents.items():
        if not _res_name_ok(name):
            raise ValueError(f"bad resident name {name!r} (use [a-z0-9_-])")
        if name in seen:
            raise ValueError(f"duplicate resident {name}")
        seen.add(name)
        proto = r.get("protocol", "process")
        if proto not in VALID_PROTOCOLS:
            raise ValueError(f"{name}: protocol must be one of {VALID_PROTOCOLS}")
        if proto == "cooperative" and not r.get("sleep_url"):
            raise ValueError(f"{name}: cooperative residents need sleep_url")
        if proto == "process" and not r.get("start"):
            raise ValueError(f"{name}: process residents need a start command")
        if "port" not in r and not r.get("probe"):
            raise ValueError(f"{name}: needs a port (TCP probe) or a probe url")
    policies = dict(DEFAULT_POLICIES)
    policies.update(cfg.get("policies") or {})
    server = dict(cfg.get("server") or {})
    return {"residents": residents, "policies": policies, "server": server}


def _res_name_ok(name):
    return bool(name) and all(c.isalnum() and c.isascii() or c in "_-" for c in name)
