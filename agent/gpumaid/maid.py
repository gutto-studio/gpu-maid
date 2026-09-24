"""The Maid: resident registry, watchdog and make-room arbitration."""

from __future__ import annotations

import collections
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request

from . import DETACHED_FLAGS, IS_WIN
from .config import validate_resident
from .logic import plan_evictions, should_revive
from .telemetry import compute_apps, gpu_status

LOG = logging.getLogger("gpumaid")


class Maid:
    def __init__(self, cfg, state_path, log_path=None, dropin_dir=None):
        self.residents = cfg["residents"]
        self.policies = cfg["policies"]
        self.server_cfg = cfg["server"]
        self.state_path = state_path
        self.log_path = log_path
        self.dropin_dir = dropin_dir
        self.lock = threading.Lock()
        # the gate serializes make-room sections: two concurrent wakes would
        # otherwise evict for each other and fight over the same VRAM.
        self.gate = threading.Lock()
        self._gate_holder = None
        self._gate_waiting = []
        self.events = collections.deque(maxlen=200)  # state-transition log
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
        self._event(f"starting {name}: {cmd}")
        subprocess.Popen(cmd, shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         creationflags=DETACHED_FLAGS)

    def _ps_kill(self, pattern):
        """Kill processes whose command line matches pattern (cross-platform).

        The PowerShell helper is transient (we wait for it), so it gets
        NO_WINDOW only — DETACHED|NEW_PROCESS_GROUP here makes it die
        silently when the agent itself descends from an SSH chain
        (battle-tested lesson; production butlers run NO_WINDOW).
        """
        if IS_WIN:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process | Where-Object { "
                 "$_.CommandLine -match '" + pattern + "' } | "
                 "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                capture_output=True, timeout=30, creationflags=0x08000000)
        else:
            subprocess.run(["pkill", "-f", pattern], capture_output=True,
                           timeout=15)

    def sleep_one(self, name, reason="suspended"):
        """Put one resident to sleep, honouring its protocol. Idempotent-ish."""
        r = self.residents[name]
        if r.get("protocol") == "always_on":
            return False, "always_on residents are never evicted"
        with self.lock:
            if self.state[name]["suspend_req"] and not self.state[name]["alive"]:
                return True, "already asleep"
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
                self._event(f"{name} asleep via unload endpoint ({reason})")
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
        # a kill is a signal, not a fact: confirm the resident actually
        # let go before telling anyone it is asleep.
        deadline = time.time() + self.policies.get("sleep_confirm_s", 10)
        while time.time() < deadline and self.probe(name):
            time.sleep(0.5)
        if self.probe(name):
            self._event(f"{name} sleep: kill signalled, still up")
            return False, "kill signalled, but the resident is still up"
        with self.lock:
            self.state[name]["suspend_req"] = True
            self.state[name]["alive"] = False  # stamped now; watchdog verifies
        self.save_state()
        self._event(f"{name} asleep ({reason})")
        return True, "asleep"

    # -- the make-room ritual --

    def make_room(self, target, needed_gb):
        """Evict + settle until measured free VRAM covers the request.

        Returns (ok, detail). Suspended residents stay suspended — waking
        them again later is one ``wake`` away; that is the whole deal.
        """
        free = gpu_status().get("free_gb")
        evict, still_short = plan_evictions(
            self.residents, self.state, free, needed_gb, target,
            self.policies["baseline_gb"])
        for n in evict:
            self._event(f"asking {n} to make room for {target}")
            self.sleep_one(n, reason=f"making room for {target}")
        if free is None:
            return True, "vram unknown — gate skipped (no nvidia-smi)"
        deadline = time.time() + self.policies["settle_timeout_s"]
        while time.time() < deadline:
            free = gpu_status().get("free_gb")
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
        if self.probe(name):
            with self.lock:
                self.state[name]["alive"] = True
                self.state[name]["wanted"] = True
            self.save_state()
            return True, "already up", {}
        # queue at the gate: one make-room ritual at a time, first come first
        # served (the queue is visible in /list).
        with self.lock:
            self._gate_waiting.append(name)
        with self.gate:
            with self.lock:
                if name in self._gate_waiting:
                    self._gate_waiting.remove(name)
                self._gate_holder = name
            try:
                return self._wake_gated(name)
            finally:
                with self.lock:
                    self._gate_holder = None

    def _wake_gated(self, name):
        with self.lock:
            st = self.state[name]
            st["suspend_req"] = False
            st["fails"] = 0
            st["wanted"] = True          # waking = joining the keepalive roster
            st["last_revive"] = time.time()  # watchdog must not double-start
        self.save_state()
        r = self.residents.get(name)
        if r is None:
            return False, f"unknown resident {name}", {}
        if r.get("protocol") == "cooperative" and r.get("start") is None:
            return False, "resident is down and has no start command", {}
        ok, detail = self.make_room(name, r.get("vram_gb", 0))
        if not ok:
            self._event(f"{name} wake refused: {detail}")
            return False, detail, {"vram": gpu_status().get("free_gb")}
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

    # -- registration (drop-in residents) --

    def register_resident(self, name, fields):
        """Register a new resident at runtime; persisted as a residents.d
        drop-in so it survives restarts. Refuses duplicates."""
        fields = dict(fields or {})
        fields.pop("name", None)
        try:
            validate_resident(name, fields)
        except ValueError as e:
            return False, str(e)
        with self.lock:
            if name in self.residents:
                return False, f"{name} is already registered"
            self.residents[name] = fields
            self.state[name] = {
                "alive": False, "fails": 0, "last_revive": 0.0,
                "suspend_req": False,
                "wanted": bool(fields.get("wanted_default", True)),
                "last_busy": time.time(),
            }
        if self.dropin_dir:
            try:
                os.makedirs(self.dropin_dir, exist_ok=True)
                with open(os.path.join(self.dropin_dir, name + ".json"),
                          "w", encoding="utf-8") as f:
                    json.dump(fields, f, ensure_ascii=False, indent=1)
            except OSError as e:
                return False, f"registered in memory, but drop-in write failed: {e}"
        self._event(f"{name} registered "
                    f"({fields.get('protocol', 'process')})")
        return True, "registered"

    def unregister_resident(self, name):
        """Remove a drop-in registered resident. Static residents.json
        entries must be edited by hand — the maid never deletes those."""
        with self.lock:
            if name not in self.residents:
                return False, f"unknown resident {name}"
        path = (os.path.join(self.dropin_dir, name + ".json")
                if self.dropin_dir else None)
        if not path or not os.path.exists(path):
            return (False, f"{name} comes from the static residents.json; "
                           "edit that file instead")
        if self.probe(name):
            self.sleep_one(name, reason="unregistered")
        try:
            os.remove(path)
        except OSError as e:
            return False, f"drop-in removal failed: {e}"
        with self.lock:
            self.residents.pop(name, None)
            self.state.pop(name, None)
        self._event(f"{name} unregistered")
        return True, "unregistered"

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
            self._event("MASTER OFF (owner mode)")
            return True, "master off: VRAM returned to the owner"
        with self.lock:
            self.master_off = False
            for name in self.state:
                self.state[name]["wanted"] = False  # on-demand roster: empty
        self.save_state()
        self._event("MASTER ON (on-demand mode)")
        return True, "master on: residents load on demand"

    # -- watchdog --

    def watch_loop(self):
        while True:
            now = time.time()
            # snapshot the registry: registration can mutate it mid-cycle
            for name, r in list(self.residents.items()):
                alive = self.probe(name)
                with self.lock:
                    st = self.state.get(name)
                    if st is None:
                        continue
                    st["alive"] = alive
                    if alive:
                        st["fails"] = 0
                        continue
                    if self.master_off or st["suspend_req"] or not st["wanted"]:
                        continue
                    if r.get("start") is None:
                        continue  # no way to start it — not the maid's problem
                    st["fails"] += 1
                    rev = should_revive(st, now, self.policies)
                if rev:
                    with self.lock:
                        st["fails"] = 0
                        st["last_revive"] = time.time()
                    self._event(f"{name} dead, reviving (watchdog)")
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
            self._event(f"{name} idle for {ttl}s, suspending (VRAM back)")
            self.sleep_one(name, reason="idle timeout")

    # -- event log (what happened while you were away) --

    def _event(self, msg):
        with self.lock:
            self.events.append({"ts": time.strftime("%m-%d %H:%M:%S"),
                                "msg": msg})
        LOG.info("%s", msg)

    def recent_events(self, n=None):
        with self.lock:
            items = list(self.events)
        return items[-n:] if n else items

    # -- snapshots for /list --

    def snapshot(self):
        with self.lock:
            residents = {name: {
                "alive": st["alive"],
                "suspended": st["suspend_req"],
                "wanted": st["wanted"],
                "fails": st["fails"],
                "protocol": self.residents[name].get("protocol", "process"),
                "vram_gb": self.residents[name].get("vram_gb", 0),
                "icon": self.residents[name].get("icon", ""),
                "desc": self.residents[name].get("desc", ""),
            } for name, st in self.state.items()}
            gate = {"holder": self._gate_holder,
                    "waiting": list(self._gate_waiting)}
            master_off = self.master_off
        return {"residents": residents, "master_off": master_off,
                "gate": gate, "gpu": gpu_status(),
                "compute_apps": compute_apps()}
