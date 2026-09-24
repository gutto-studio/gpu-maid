#!/usr/bin/env python3
"""Real-box validation harness for the gpu-maid agent.

Run ON the GPU box (Windows or Linux), next to the ``gpumaid`` package:

    python validate_on_pc.py

Starts a real agent on :9720 with one throwaway resident (a stdlib
http.server), then exercises every verb over real HTTP:

* live nvidia-smi telemetry (memory / utilization / temperature)
* wake via detached spawn (the real Windows process path)
* sleep via command-line process kill (the real PowerShell/pkill path)
* events log, master-switch roundtrip (deadlock regression check)
* state persistence

Production residents are never touched — the registry contains only the
throwaway resident. Everything is cleaned up on exit; non-zero exit code
means at least one check failed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 9720
RES_PORT = 9761
BASE = f"http://127.0.0.1:{PORT}"
PY = sys.executable

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""),
          flush=True)


def req(path, method="GET", timeout=45):
    r = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode() or "{}")
        except ValueError:
            return {}


def kill_stray():
    pat = f"http.server {RES_PORT}"
    if os.name == "nt":
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine "
             f"-match '{pat}' }} | ForEach-Object {{ Stop-Process -Id "
             "$_.ProcessId -Force }"],
            capture_output=True)
    else:
        subprocess.run(["pkill", "-f", pat], capture_output=True)


def summarize():
    fails = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(fails)}/{len(results)} checks passed", flush=True)
    if fails:
        print("FAILED: " + ", ".join(fails), flush=True)
    return 1 if fails else 0


def main():
    tmpd = os.path.join(HERE, "val_tmp")
    os.makedirs(tmpd, exist_ok=True)
    cfg = {
        "server": {"port": PORT, "token": ""},
        "policies": {"ensure_timeout_s": 30, "settle_timeout_s": 30,
                     "check_interval_s": 5},
        "residents": {
            "demo": {
                "desc": "throwaway validation resident",
                "protocol": "process",
                "port": RES_PORT,
                "probe": f"http://127.0.0.1:{RES_PORT}/",
                "start": (f'"{PY}" -m http.server {RES_PORT} '
                          f'--bind 127.0.0.1 --directory "{tmpd}"'),
                "kill_pat": f"http.server {RES_PORT}",
                "vram_gb": 0,
            },
        },
    }
    cfg_path = os.path.join(HERE, "residents.validate.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=1)
    state_path = os.path.join(HERE, "gpumaid_state.json")
    if os.path.exists(state_path):
        os.remove(state_path)

    agent = None
    try:
        logf = open(os.path.join(HERE, "validate_agent.log"), "w",
                    encoding="utf-8")
        agent = subprocess.Popen(
            [PY, "-m", "gpumaid", "--config", cfg_path, "--port", str(PORT)],
            cwd=HERE, stdout=logf, stderr=subprocess.STDOUT)
        healthy = False
        for _ in range(40):
            try:
                req("/health", timeout=3)
                healthy = True
                break
            except Exception:
                time.sleep(0.5)
        check("agent starts and serves /health", healthy)
        if not healthy:
            return summarize()

        h = req("/health")
        check("health payload", h.get("ok") and h.get("residents") == 1,
              f"residents={h.get('residents')}")

        lst = req("/list")
        g = lst.get("gpu") or {}
        check("live nvidia-smi telemetry",
              g.get("free_gb") is not None and g.get("total_gb") is not None,
              f"free={g.get('free_gb')}G total={g.get('total_gb')}G "
              f"util={g.get('util_pct')}% temp={g.get('temp_c')}C")
        apps = lst.get("compute_apps") or []
        check("compute_apps present", isinstance(lst.get("compute_apps"), list),
              f"{len(apps)} procs holding VRAM")

        t0 = time.time()
        e = req("/ensure/demo", "POST")
        check("ensure wakes throwaway resident (detached spawn)",
              e.get("ok"), f"{time.time() - t0:.1f}s msg={e.get('msg')}")
        lst = req("/list")
        check("resident alive after wake",
              lst["residents"]["demo"].get("alive") is True)
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{RES_PORT}/", timeout=5) as r:
                serving = r.status == 200
        except Exception:
            serving = False
        check("resident actually serves HTTP", serving)

        ev = req("/events?n=20")
        check("events recorded",
              any("starting demo" in x.get("msg", "")
                  for x in ev.get("events", [])))

        s = req("/sleep/demo", "POST")
        check("sleep kills resident process", s.get("ok"), s.get("msg", ""))
        time.sleep(1.5)
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{RES_PORT}/", timeout=3)
            resident_down = False
        except Exception:
            resident_down = True
        check("resident port closed after sleep", resident_down)
        lst = req("/list")
        check("resident suspended after sleep",
              lst["residents"]["demo"].get("suspended") is True)

        m = req("/master/off", "POST")
        check("master off", m.get("ok"))
        w = req("/wake/demo", "POST")
        check("wake refused under master off",
              w.get("ok") is False and "master" in w.get("msg", ""))
        m = req("/master/on", "POST")
        check("master on (deadlock regression)", m.get("ok"), m.get("msg", ""))
        check("state file persisted", os.path.exists(state_path))
    finally:
        if agent and agent.poll() is None:
            agent.terminate()
            try:
                agent.wait(10)
            except Exception:
                agent.kill()
        kill_stray()
    return summarize()


if __name__ == "__main__":
    sys.exit(main())
