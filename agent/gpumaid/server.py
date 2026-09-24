"""The HTTP surface: a small JSON API in front of the Maid."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import IS_WIN


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
                self._send(200, maid.snapshot())
            elif self.path.startswith("/events"):
                n = None
                if "n=" in self.path:
                    try:
                        n = max(1, min(1000, int(self.path.split("n=")[-1])))
                    except ValueError:
                        n = None
                self._send(200, {"events": maid.recent_events(n)})
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
