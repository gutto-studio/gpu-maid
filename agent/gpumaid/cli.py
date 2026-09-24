"""gpu-maid CLI — the thin client for the household GPU butler.

Talks to the agent over HTTP. stdlib only.

    gpumaid connect 192.168.1.20:9700   # point at your maid (saved once)
    gpumaid list                        # who's awake, VRAM headroom
    gpumaid wake video                  # ask for the room
    gpumaid ensure video                # wake and block until ready
    gpumaid sleep voice                 # put one resident to bed
    gpumaid touch voice                 # renew a resident's idle timer
    gpumaid events                      # what happened while you were away
    gpumaid master off                  # whole household rests

The agent address is read from --url, $GPUMAID_URL, or ~/.gpumaid/config.json
(saved by `connect`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from . import __version__

CONFIG_PATH = os.path.expanduser("~/.gpumaid/config.json")


def base_url(args) -> str:
    url = getattr(args, "url", None) or os.environ.get("GPUMAID_URL", "")
    if not url and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                url = json.load(f).get("url", "")
        except (OSError, ValueError):
            url = ""
    if not url:
        sys.exit("no agent address: run `gpumaid connect HOST[:PORT]` "
                 "or set GPUMAID_URL")
    return url.rstrip("/")


def token() -> str:
    return os.environ.get("GPUMAID_TOKEN", "")


def call(method, url, path, body=None):
    req = urllib.request.Request(
        url + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token()}"} if token() else {})})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"maid is unreachable: {e}")


def cmd_connect(args):
    url = args.address if "://" in args.address else f"http://{args.address}"
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"url": url.rstrip("/")}, f)
    print(f"saved: {url} -> {CONFIG_PATH}")


def cmd_list(args):
    _, data = call("GET", base_url(args), "/list")
    g = data.get("gpu") or {}
    if g.get("free_gb") is None:
        head = "GPU: nvidia-smi unavailable"
    else:
        head = f"GPU free {g['free_gb']}/{g['total_gb']} GB"
        if g.get("util_pct") is not None:
            head += f" · util {g['util_pct']}%"
        if g.get("temp_c") is not None:
            head += f" · {g['temp_c']}C"
    print(head + ("  [MASTER OFF]" if data.get("master_off") else ""))
    gate = data.get("gate") or {}
    if gate.get("holder"):
        waiting = gate.get("waiting") or []
        extra = f" (waiting: {', '.join(waiting)})" if waiting else ""
        print(f"gate: {gate['holder']} is making room{extra}")
    for name, st in sorted((data.get("residents") or {}).items()):
        flag = "up" if st["alive"] else ("suspended" if st["suspended"] else "down")
        print(f"  {name:<14} {flag:<10} {st['protocol']:<12}"
              f"{st['vram_gb']:>5} GB   {st['desc']}")
    apps = data.get("compute_apps") or []
    if apps:
        print(f"  holding VRAM now ({len(apps)}):")
        for app in apps:
            print(f"    pid {app['pid']:<7} {app['name'][:28]:<28} {app['mb']} MB")


def cmd_wake(args):
    st, data = call("POST", base_url(args), f"/wake/{args.resident}")
    print(("ok: " if data.get("ok") else "no: ") + data.get("msg", ""))
    sys.exit(0 if data.get("ok") else 1)


def cmd_ensure(args):
    """Wake if needed and block until the resident is ready to take a job."""
    st, data = call("POST", base_url(args), f"/ensure/{args.resident}")
    print(("ok: " if data.get("ok") else "no: ") + data.get("msg", ""))
    sys.exit(0 if data.get("ok") else 1)


def cmd_sleep(args):
    st, data = call("POST", base_url(args), f"/sleep/{args.resident}")
    print(("ok: " if data.get("ok") else "no: ") + data.get("msg", ""))
    sys.exit(0 if data.get("ok") else 1)


def cmd_touch(args):
    _, data = call("POST", base_url(args), f"/touch/{args.resident}")
    print("ok" if data.get("ok") else "no: " + data.get("msg", ""))


def cmd_events(args):
    _, data = call("GET", base_url(args), "/events")
    if data.get("error"):
        print("no: " + data["error"])
        return
    items = (data.get("events") or [])[-args.n:]
    if not items:
        print("no events yet — the maid has been quiet")
        return
    for e in items:
        print(f"{e['ts']}  {e['msg']}")


def cmd_master(args):
    st, data = call("POST", base_url(args), f"/master/{args.op}")
    print(("ok: " if data.get("ok") else "no: ") + data.get("msg", ""))
    sys.exit(0 if data.get("ok") else 1)


def main():
    ap = argparse.ArgumentParser(prog="gpumaid", description="ask the maid")
    ap.add_argument("--url", help="agent base url (overrides saved config)")
    ap.add_argument("--version", action="version",
                    version=f"gpumaid {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("connect", help="save the agent address")
    p.add_argument("address", help="host[:port] or full url")
    p.set_defaults(fn=cmd_connect)

    p = sub.add_parser("list", help="residents and VRAM headroom")
    p.set_defaults(fn=cmd_list)

    for verb, fn, help_text in (
            ("wake", cmd_wake, "wake a resident (maid makes room)"),
            ("ensure", cmd_ensure, "wake and block until ready to take a job"),
            ("sleep", cmd_sleep, "put a resident to bed"),
            ("touch", cmd_touch, "renew a resident's idle timer")):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument("resident")
        p.set_defaults(fn=fn)

    p = sub.add_parser("events", help="recent agent events")
    p.add_argument("-n", type=int, default=30, help="how many to show")
    p.set_defaults(fn=cmd_events)

    p = sub.add_parser("master", help="whole-household switch")
    p.add_argument("op", choices=["on", "off"])
    p.set_defaults(fn=cmd_master)

    args = ap.parse_args()
    if args.cmd != "connect":
        base_url(args)  # fail fast with a friendly message
    args.fn(args)


if __name__ == "__main__":
    main()
