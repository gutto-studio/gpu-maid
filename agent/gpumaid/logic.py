"""Pure decision logic — no I/O, no threads, unit-testable anywhere."""

from __future__ import annotations


def _int_or_none(s):
    s = s.strip()
    return int(s) if s.isdigit() else None


def parse_smi_line(raw):
    """Parse one nvidia-smi csv line: free/total (MiB), util %, temp C.

    Fields that come back "[N/A]" (util on some drivers) parse as None —
    partial telemetry beats no telemetry.
    """
    def gb(s):
        v = _int_or_none(s)
        return round(v / 1024, 2) if v is not None else None
    try:
        p = [x.strip() for x in raw.strip().splitlines()[0].split(",")]
    except (IndexError, AttributeError):
        p = []
    if len(p) < 4:
        return {"free_gb": None, "total_gb": None, "util_pct": None,
                "temp_c": None}
    return {"free_gb": gb(p[0]), "total_gb": gb(p[1]),
            "util_pct": _int_or_none(p[2]), "temp_c": _int_or_none(p[3])}


def plan_evictions(residents, states, free_gb, needed_gb, target, baseline_gb):
    """Who should be asked to sleep so ``target`` can fit? Pure function.

    Evictable = alive, not suspended, not ``always_on``, not the target.
    Candidates are evicted largest-claimed-first until the *estimate* fits;
    the caller still verifies against measured VRAM afterwards.
    Returns ``(evict_list, still_short_gb)``.
    """
    if free_gb is None or not needed_gb:
        return [], 0.0
    short = needed_gb + baseline_gb - free_gb
    if short <= 0:
        return [], 0.0
    cands = [
        n for n, r in residents.items()
        if n != target
        and r.get("protocol") != "always_on"
        and states[n].get("alive")
        and not states[n].get("suspend_req")
    ]
    cands.sort(key=lambda n: residents[n].get("vram_gb", 0), reverse=True)
    evict = []
    for n in cands:
        evict.append(n)
        short -= residents[n].get("vram_gb", 0)
        if short <= 0:
            break
    return evict, max(short, 0.0)


def should_revive(st, now, policies):
    """Watchdog decision for one resident (master switch handled by caller)."""
    return (st["fails"] >= policies["fails_to_revive"]
            and now - st["last_revive"] > policies["revive_cooldown_s"]
            and not st["suspend_req"]
            and st["wanted"])
