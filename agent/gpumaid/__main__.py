"""Entry point: `python -m gpumaid --config residents.json`."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time

from . import __version__
from .config import DEFAULT_PORT, load_config
from .maid import Maid
from .server import build_server

LOG = logging.getLogger("gpumaid")


def main():
    ap = argparse.ArgumentParser(prog="gpumaid", description="gpu-maid agent (VRAM butler)")
    ap.add_argument("--config", required=True, help="residents.json path")
    ap.add_argument("--port", type=int, help="override server port")
    ap.add_argument("--state", help="state file path (default: alongside config)")
    ap.add_argument("--log", help="log file path (default: stdout only)")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    handlers = [logging.StreamHandler()]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="[%(asctime)s] %(message)s",
                        datefmt="%m-%d %H:%M:%S")

    cfg = load_config(args.config)
    state_path = args.state or os.path.join(
        os.path.dirname(os.path.abspath(args.config)), "gpumaid_state.json")
    maid = Maid(cfg, state_path)
    maid.load_state()
    # startup = everyone considered just-busy: let a full idle period pass
    # before any idle suspension (never kill a running job on a reboot).
    with maid.lock:
        for st in maid.state.values():
            st["last_busy"] = time.time()
    threading.Thread(target=maid.watch_loop, daemon=True).start()

    port = args.port or cfg["server"].get("port", DEFAULT_PORT)
    token = cfg["server"].get("token", "")
    if not token:
        LOG.warning("no token set - anyone on the network can drive this "
                    "agent; set server.token before leaving localhost/LAN")

    def _bye(signum, _frame):
        LOG.info("signal %s: maid bows out (state persisted)", signum)
        maid.save_state()
        sys.exit(0)

    signal.signal(signal.SIGINT, _bye)
    signal.signal(signal.SIGTERM, _bye)
    LOG.info("gpu-maid %s agent on :%s, watching %s%s", __version__, port,
             list(maid.residents), " [MASTER OFF]" if maid.master_off else "")
    build_server(maid, port, token).serve_forever()


if __name__ == "__main__":
    main()
