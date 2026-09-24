#!/usr/bin/env python3
"""gpu-maid menu-bar plugin for SwiftBar (macOS) — also xbar compatible.

Shows live GPU memory / utilization / temperature, the resident roster with
one-click wake/sleep, the make-room queue and recent maid events — right in
the macOS menu bar. Standalone stdlib script; no repo checkout needed.

Setup:
  1. brew install --cask swiftbar        (or download from swiftbar.app)
  2. Point SwiftBar at a plugin folder, then copy this file into it.
  3. The agent address comes from $GPUMAID_URL or ~/.gpumaid/config.json
     (written by `gpumaid connect`). $GPUMAID_TOKEN is used if set.

The filename suffix (.5s.) makes SwiftBar refresh every 5 seconds.
"""

import json
import os
import sys
import urllib.request

CONFIG_PATH = os.path.expanduser("~/.gpumaid/config.json")
CURL = "/usr/bin/curl"


def agent_url():
    url = os.environ.get("GPUMAID_URL", "")
    if not url:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                url = json.load(f).get("url", "")
        except (OSError, ValueError):
            url = ""
    return url.rstrip("/")


def _token():
    return os.environ.get("GPUMAID_TOKEN", "")


def _fetch(path, timeout=5):
    req = urllib.request.Request(agent_url() + path)
    tok = _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _act(path):
    """SwiftBar menu-item params: run curl POST in background, then refresh."""
    parts = [f"shell={CURL}", "param1=-s", "param2=-m", "param3=3",
             "param4=-X", "param5=POST"]
    tok = _token()
    if tok:
        parts += ["param6=-H", f"param7=Authorization: Bearer {tok}"]
    parts.append(f"param8={agent_url()}{path}")
    parts += ["terminal=false", "refresh=true"]
    return " | " + " ".join(parts)


def render(data, events=None):
    """Render the SwiftBar DSL for one /list payload. Pure function."""
    g = data.get("gpu") or {}
    lines = []

    # menu bar title
    if data.get("master_off"):
        lines.append("maid 💤 | color=purple")
    elif g.get("free_gb") is None:
        lines.append("maid ? | color=gray")
    else:
        title = f"GPU {g['free_gb']}/{g.get('total_gb', '?')}G"
        if g.get("util_pct") is not None:
            title += f" · {g['util_pct']}%"
        if g.get("temp_c") is not None:
            title += f" · {g['temp_c']}°C"
        color = ("green" if g["free_gb"] > 2
                 else "orange" if g["free_gb"] > 0.5 else "red")
        lines.append(f"{title} | color={color}")

    lines.append("---")

    # make-room gate
    gate = data.get("gate") or {}
    if gate.get("holder"):
        waiting = ", ".join(gate.get("waiting") or []) or "-"
        lines.append(f"making room: {gate['holder']} (waiting: {waiting}) | color=yellow")
        lines.append("---")

    # residents
    for name, st in sorted((data.get("residents") or {}).items()):
        if st.get("alive"):
            dot, color = "●", "green"
        elif st.get("suspended"):
            dot, color = "○", "gray"
        else:
            dot, color = "✕", "red"
        lines.append(f"{dot} {name} · {st.get('protocol')} · {st.get('vram_gb')}G"
                     f" | color={color}")
        if st.get("alive") or st.get("suspended"):
            lines.append(f"-- wake {name}{_act(f'/wake/{name}')}")
        if st.get("alive"):
            lines.append(f"-- sleep {name}{_act(f'/sleep/{name}')}")
        if st.get("desc"):
            lines.append(f"-- {st['desc']} | size=11 color=gray")

    # processes holding VRAM
    apps = data.get("compute_apps") or []
    if apps:
        lines.append("---")
        lines.append(f"holding VRAM ({len(apps)}) | size=11 color=gray")
        for app in apps:
            lines.append(f"-- {app['name']} · {app['mb']} MB · pid {app['pid']}"
                         " | size=11")

    # recent events
    if events:
        lines.append("---")
        lines.append("recent | size=11 color=gray")
        for e in events[-8:]:
            lines.append(f"-- {e['ts']}  {e['msg']} | size=11")

    # master switch
    lines.append("---")
    if data.get("master_off"):
        lines.append(f"master on{_act('/master/on')}")
    else:
        lines.append(f"master off{_act('/master/off')}")

    return "\n".join(lines) + "\n"


def main():
    if not agent_url():
        print("maid: connect first | color=red")
        print("---")
        print("run: gpumaid connect HOST:PORT | size=11")
        return
    try:
        data = _fetch("/list")
        events = _fetch("/events?n=8").get("events")
    except Exception as e:  # noqa: BLE001 — a dead maid must not beachball the bar
        print("maid ✗ | color=red")
        print("---")
        print(str(e)[:120] + " | size=11")
        return
    print(render(data, events), end="")


if __name__ == "__main__":
    sys.exit(main())
