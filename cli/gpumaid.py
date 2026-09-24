#!/usr/bin/env python3
"""gpu-maid CLI — the thin client for the household GPU butler.

Talks to the agent over HTTP. stdlib only.

    gpumaid connect 192.168.1.20:9700   # point at your maid (saved once)
    gpumaid list                        # who's awake, VRAM headroom
    gpumaid wake video                  # ask for the room
    gpumaid sleep voice                 # put one resident to bed
    gpumaid touch voice                 # renew a resident's idle timer
    gpumaid master off                  # whole household rests

The agent address is read from --url, $GPUMAID_URL, or ~/.gpumaid/config.json
(saved by `connect`), in that order.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

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
    v = data.get("vram", {})
    print(f"VRAM free {v.get('free_gb')} / {v.get('total_gb')} GB"
          + ("  [MASTER OFF]" if data["residents"].get("_master_off") else ""))
    for name, st in sorted(data["residents"].items()):
        if name.startswith("_"):
            continue
        flag = "up" if st["alive"] else ("suspended" if st["suspended"] else "down")
        print(f"  {name:<14} {flag:<10} {st['protocol']:<12}"
              f"{st['vram_gb']:>5} GB   {st['desc']}")


def cmd_wake(args):
    st, data = call("POST", base_url(args), f"/wake/{args.resident}")
    print(("ok: " if data.get("ok") else "no: ") + data.get("msg", ""))
    sys.exit(0 if data.get("ok") else 1)


def cmd_sleep(args):
    st, data = call("POST", base_url(args), f"/sleep/{args.resident}")
    print(("ok: " if data.get("ok") else "no: ") + data.get("msg", ""))
    sys.exit(0 if data.get("ok") else 1)


def cmd_touch(args):
    _, data = call("POST", base_url(args), f"/touch/{args.resident}")
    print("ok" if data.get("ok") else "no: " + data.get("msg", ""))


def cmd_master(args):
    st, data = call("POST", base_url(args), f"/master/{args.op}")
    print(("ok: " if data.get("ok") else "no: ") + data.get("msg", ""))
    sys.exit(0 if data.get("ok") else 1)


def main():
    ap = argparse.ArgumentParser(prog="gpumaid", description="ask the maid")
    ap.add_argument("--url", help="agent base url (overrides saved config)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("connect", help="save the agent address")
    p.add_argument("address", help="host[:port] or full url")
    p.set_defaults(fn=cmd_connect)

    p = sub.add_parser("list", help="residents and VRAM headroom")
    p.set_defaults(fn=cmd_list)

    for verb, fn, help_text in (
            ("wake", cmd_wake, "wake a resident (maid makes room)"),
            ("sleep", cmd_sleep, "put a resident to bed"),
            ("touch", cmd_touch, "renew a resident's idle timer")):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument("resident")
        p.set_defaults(fn=fn)

    p = sub.add_parser("master", help="whole-household switch")
    p.add_argument("op", choices=["on", "off"])
    p.set_defaults(fn=cmd_master)

    args = ap.parse_args()
    if args.cmd != "connect":
        base_url(args)  # fail fast with a friendly message
    args.fn(args)


if __name__ == "__main__":
    main()
