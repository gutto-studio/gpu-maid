#!/usr/bin/env python3
"""gpu-maid agent — the VRAM butler for a household GPU box.

One consumer GPU, several AI residents (LLM, TTS, image, video). The agent
keeps the resident registry, runs a revive watchdog, arbitrates VRAM between
residents (the "make room" ritual) and exposes a small HTTP API.

Design rules, inherited from a production butler that has run a TTS + image +
video + LLM household on one 12 GB card since 2025:

* stdlib only, zero VRAM, tiny RAM — the butler must never be a tenant itself.
* state survives restarts (master switch + keepalive roster + suspend marks
  are persisted; nothing "resurrects" behind your back after a reboot).
* closed-loop gate: decisions are made on *measured* free VRAM, never on
  promises; if the card hasn't settled after a polite eviction, the wake
  fails loudly instead of swapping into RAM.
* residents are classified: ``process`` (start/stop by command and process
  pattern), ``cooperative`` (sleep = call its unload endpoint) and
  ``always_on`` (baseline load, never evicted).

Usage::

    python gpumaid_agent.py --config residents.json

Windows notes: detached launch flags, exclusive port bind and PowerShell
command-line kills are used when available; on other platforms the agent
degrades gracefully (pkill for kills, no detached flags) so development
and CI can run the pure logic anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IS_WIN = sys.platform == "win32"
# DETACHED | NEW_PROCESS_GROUP | NO_WINDOW — children must outlive the agent
DETACHED_FLAGS = (0x00000008 | 0x00000200 | 0x08000000) if IS_WIN else 0

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


def log(msg, log_path=None):
    line = time.strftime("[%m-%d %H:%M:%S] ") + str(msg)
    print(line, flush=True)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


# ---- configuration -----------------------------------------------------------

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


# ---- pure decision logic (unit-testable without a GPU) -----------------------

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


# ---- measured reality --------------------------------------------------------

def nvidia_smi_gb(field):
    """Query one memory field (GB) from nvidia-smi; None when unavailable."""
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={field}",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=8).stdout.decode()
        return round(int(out.strip().splitlines()[0]) / 1024, 2)
    except Exception:
        return None


# ---- the maid ----------------------------------------------------------------

class Maid:
    def __init__(self, cfg, state_path, log_path=None):
        self.residents = cfg["residents"]
        self.policies = cfg["policies"]
        self.server_cfg = cfg["server"]
        self.state_path = state_path
        self.log_path = log_path
        self.lock = threading.Lock()
        self.master_off = False
        self.state = {
            name: {"alive": False, "fails": 0, "last_revive": 0.0,
                   "suspend_req": False, "wanted": self._wanted_default(name),
                   "last_busy": 0.0}
            for name in self.residents
        }

    def _wanted_default(self, name):
        return bool(self.residents[name].get("wanted_default", True))

    # -- persistence --

    def load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self.master_off = bool(data.get("master_off", False))
        with self.lock:
            for name, st in self.state.items():
                saved = data.get("services", {}).get(name, {})
                st["wanted"] = bool(saved.get(
                    "wanted", self._wanted_default(name)))
                st["suspend_req"] = bool(saved.get("suspend_req", False))

    def save_state(self):
        snap = {
            "master_off": self.master_off,
            "services": {name: {"wanted": st["wanted"],
                                "suspend_req": st["suspend_req"]}
                         for name, st in self.state.items()},
        }
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # -- probing & process control --

    def probe(self, name):
        r = self.residents[name]
        url = r.get("probe")
        try:
            if url:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    return resp.status == 200
            import socket
            with socket.create_connection(("127.0.0.1", r["port"]), timeout=4):
                return True
        except Exception:
            return False

    def start(self, name):
        cmd = self.residents[name].get("start")
        if not cmd:
            return
        self._log(f"starting {name}: {cmd}")
        subprocess.Popen(cmd, shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         creationflags=DETACHED_FLAGS)

    def _ps_kill(self, pattern):
        """Kill processes whose command line matches pattern (cross-platform)."""
        if IS_WIN:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process | Where-Object { "
                 "$_.CommandLine -match '" + pattern + "' } | "
                 "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                capture_output=True, creationflags=DETACHED_FLAGS)
        else:
            subprocess.run(["pkill", "-f", pattern], capture_output=True)

    def sleep_one(self, name, reason="suspended"):
        """Put one resident to sleep, honouring its protocol. Idempotent-ish."""
        r = self.residents[name]
        if r.get("protocol") == "always_on":
            return False, "always_on residents are never evicted"
        if r.get("protocol") == "cooperative" and r.get("sleep_url"):
            try:
                body = (json.dumps(r["sleep_body"]).encode()
                        if r.get("sleep_body") else None)
                req = urllib.request.Request(
                    r["sleep_url"], data=body, method="POST",
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    ok = resp.status == 200
            except Exception:
                ok = False
            if not ok and not r.get("kill_pat"):
                return False, "unload endpoint failed"
            if ok:
                with self.lock:
                    self.state[name]["suspend_req"] = True
                self.save_state()
                self._log(f"{name} asleep via unload endpoint ({reason})")
                return True, "asleep (unloaded)"
            # unload failed but a kill pattern exists: fall through to kill
        if r.get("stop"):
            subprocess.Popen(r["stop"], shell=True,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL,
                             creationflags=DETACHED_FLAGS)
        elif r.get("kill_pat"):
            self._ps_kill(r["kill_pat"])
        else:
            return False, "no way to sleep this resident"
        with self.lock:
            self.state[name]["suspend_req"] = True
            self.state[name]["alive"] = False  # stamped now; watchdog verifies
        self.save_state()
        self._log(f"{name} asleep ({reason})")
        return True, "asleep"

    # -- the make-room ritual --

    def make_room(self, target, needed_gb):
        """Evict + settle until measured free VRAM covers the request.

        Returns (ok, detail). Suspended residents stay suspended — waking
        them again later is one ``wake`` away; that is the whole deal.
        """
        free = nvidia_smi_gb("memory.free")
        evict, still_short = plan_evictions(
            self.residents, self.state, free, needed_gb, target,
            self.policies["baseline_gb"])
        for n in evict:
            self._log(f"asking {n} to make room for {target}")
            self.sleep_one(n, reason=f"making room for {target}")
        if free is None:
            return True, "vram unknown — gate skipped (no nvidia-smi)"
        deadline = time.time() + self.policies["settle_timeout_s"]
        while time.time() < deadline:
            free = nvidia_smi_gb("memory.free")
            if free is not None and free >= needed_gb + self.policies["baseline_gb"]:
                return True, f"settled at {free} GB free"
            time.sleep(self.policies["settle_poll_s"])
        return (False, f"vram never settled (need {needed_gb} GB, "
                       f"still short ~{still_short:.1f} GB even after evictions)")

    # -- wake / sleep / ensure --

    def wake(self, name):
        if name not in self.residents:
            return False, f"unknown resident {name}", {}
        if self.master_off:
            return False, "master switch is OFF: flip it on first", {}
        with self.lock:
            st = self.state[name]
            st["suspend_req"] = False
            st["fails"] = 0
            st["wanted"] = True          # waking = joining the keepalive roster
            st["last_revive"] = time.time()  # watchdog must not double-start
        self.save_state()
        if self.probe(name):
            with self.lock:
                self.state[name]["alive"] = True
            return True, "already up", {}
        r = self.residents[name]
        if r.get("protocol") == "cooperative" and self.probe(name) is False \
                and r.get("start") is None:
            return False, "resident is down and has no start command", {}
        ok, detail = self.make_room(name, r.get("vram_gb", 0))
        if not ok:
            return False, detail, {"vram": nvidia_smi_gb("memory.free")}
        self.start(name)
        # quick stamp: fast starters show up in /list immediately; slow cold
        # starts are stamped by the watchdog or a later ensure instead.
        for _ in range(3):
            if self.probe(name):
                with self.lock:
                    self.state[name]["alive"] = True
                break
            time.sleep(1)
        return True, "waking", {"settle": detail}

    def ensure(self, name):
        """Wake (if needed) and block until the probe passes, bounded."""
        if name not in self.residents:
            return False, f"unknown resident {name}"
        if self.master_off:
            return False, "master switch is OFF: flip it on first"
        if self.probe(name):
            with self.lock:
                self.state[name]["wanted"] = True
                self.state[name]["alive"] = True
            self.save_state()
            return True, "already up"
        ok, msg, _ = self.wake(name)
        if not ok:
            return False, msg
        deadline = time.time() + self.policies["ensure_timeout_s"]
        while time.time() < deadline:
            time.sleep(3)
            if self.probe(name):
                with self.lock:
                    self.state[name]["alive"] = True
                return True, "woken"
        return False, f"wake timeout ({self.policies['ensure_timeout_s']}s)"

    def sleep(self, name):
        if name not in self.residents:
            return False, f"unknown resident {name}"
        return self.sleep_one(name)

    def mark_busy(self, name):
        if name in self.residents:
            with self.lock:
                self.state[name]["last_busy"] = time.time()

    # -- master switch --

    def master(self, off, force=False):
        if off:
            for name in self.residents:
                self.sleep_one(name, reason="master switch")
            with self.lock:
                self.master_off = True
                for name in self.state:
                    self.state[name]["wanted"] = False
            self.save_state()
            self._log("MASTER OFF (owner mode)")
            return True, "master off: VRAM returned to the owner"
        with self.lock:
            self.master_off = False
            for name in self.state:
                self.state[name]["wanted"] = False  # on-demand roster: empty
        self.save_state()
        self._log("MASTER ON (on-demand mode)")
        return True, "master on: residents load on demand"

    # -- watchdog --

    def watch_loop(self):
        while True:
            now = time.time()
            for name in self.residents:
                alive = self.probe(name)
                with self.lock:
                    st = self.state[name]
                    st["alive"] = alive
                    if alive:
                        st["fails"] = 0
                        continue
                    if self.master_off or st["suspend_req"] or not st["wanted"]:
                        continue
                    st["fails"] += 1
                    rev = should_revive(st, now, self.policies)
                if rev:
                    with self.lock:
                        st["fails"] = 0
                        st["last_revive"] = time.time()
                    self._log(f"{name} dead, reviving (watchdog)")
                    self.start(name)
            self._idle_suspend_check()
            time.sleep(self.policies["check_interval_s"])

    def _idle_suspend_check(self):
        """Return VRAM from residents nobody has touched for idle_suspend s."""
        hits = []
        with self.lock:
            for name, r in self.residents.items():
                ttl = r.get("idle_suspend")
                st = self.state[name]
                if ttl and st["alive"] and not st["suspend_req"] \
                        and time.time() - st["last_busy"] > ttl:
                    st["last_busy"] = time.time()  # claim the slot first
                    hits.append((name, ttl))
        for name, ttl in hits:
            self._log(f"{name} idle for {ttl}s, suspending (VRAM back)")
            self.sleep_one(name, reason="idle timeout")

    # -- snapshots for /list --

    def snapshot(self):
        with self.lock:
            out = {name: {
                "alive": st["alive"],
                "suspended": st["suspend_req"],
                "wanted": st["wanted"],
                "protocol": self.residents[name].get("protocol", "process"),
                "vram_gb": self.residents[name].get("vram_gb", 0),
                "desc": self.residents[name].get("desc", ""),
            } for name, st in self.state.items()}
            out["_master_off"] = self.master_off
        return out

    def _log(self, msg):
        log(msg, self.log_path)


# ---- HTTP surface ------------------------------------------------------------

def build_server(maid, port, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self):
            return not token or self.headers.get("Authorization") == f"Bearer {token}"

        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"ok": True, "residents": len(maid.residents),
                                 "master_off": maid.master_off})
            elif self.path == "/list":
                self._send(200, {"residents": maid.snapshot(),
                                 "vram": {"free_gb": nvidia_smi_gb("memory.free"),
                                          "total_gb": nvidia_smi_gb("memory.total")}})
            else:
                self._send(404, {"error": "unknown route"})

        def do_POST(self):
            if not self._authed():
                self._send(401, {"error": "bad or missing token"})
                return
            path = self.path.split("?")[0].rstrip("/")
            parts = path.split("/", 2)
            try:
                if path == "/master/on":
                    ok, msg = maid.master(off=False)
                    self._send(200, {"ok": ok, "msg": msg})
                elif path == "/master/off":
                    ok, msg = maid.master(off=True, force="force=1" in self.path)
                    self._send(200, {"ok": ok, "msg": msg})
                elif len(parts) == 3 and parts[1] in ("wake", "sleep", "ensure", "touch"):
                    name = parts[2].strip()
                    if parts[1] == "wake":
                        ok, msg, extra = maid.wake(name)
                        self._send(200 if ok else 409, {"ok": ok, "msg": msg, **extra})
                    elif parts[1] == "ensure":
                        ok, msg = maid.ensure(name)
                        self._send(200, {"ok": ok, "msg": msg})
                    elif parts[1] == "sleep":
                        ok, msg = maid.sleep(name)
                        self._send(200 if ok else 409, {"ok": ok, "msg": msg})
                    else:  # touch
                        maid.mark_busy(name)
                        self._send(200, {"ok": True, "msg": f"{name} idle timer reset"})
                else:
                    self._send(404, {"error": "unknown route"})
            except Exception as e:  # noqa: BLE001 — report, never crash the maid
                self._send(500, {"error": str(e)})

    class ExclusiveServer(ThreadingHTTPServer):
        # Windows: exclusive bind makes an accidentally duplicated agent die
        # instantly (SO_REUSEADDR would allow double listens there — no ghost
        # maids). POSIX: reuse to dodge TIME_WAIT sockets from recent clients.
        allow_reuse_address = not IS_WIN

        def server_bind(self):
            if IS_WIN:
                import socket
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    self.socket.setsockopt(
                        socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    return ExclusiveServer(("0.0.0.0", port), Handler)


def main():
    ap = argparse.ArgumentParser(description="gpu-maid agent (VRAM butler)")
    ap.add_argument("--config", required=True, help="residents.json path")
    ap.add_argument("--port", type=int, help="override server port")
    ap.add_argument("--state", help="state file path (default: alongside config)")
    ap.add_argument("--log", help="log file path (default: stdout only)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    state_path = args.state or os.path.join(
        os.path.dirname(os.path.abspath(args.config)), "gpumaid_state.json")
    maid = Maid(cfg, state_path, args.log)
    maid.load_state()
    # startup = everyone considered just-busy: let a full idle period pass
    # before any idle suspension (never kill a running job on a reboot).
    with maid.lock:
        for st in maid.state.values():
            st["last_busy"] = time.time()
    threading.Thread(target=maid.watch_loop, daemon=True).start()

    port = args.port or cfg["server"].get("port", DEFAULT_PORT)
    token = cfg["server"].get("token", "")
    log(f"gpu-maid agent on :{port}, watching {list(maid.residents)}"
        f"{' [MASTER OFF]' if maid.master_off else ''}")
    build_server(maid, port, token).serve_forever()


if __name__ == "__main__":
    main()
