"""HTTP-surface integration tests: routes, status codes, token auth.

Starts the real server on an ephemeral port against a fake Maid — no GPU,
no real residents, just the wire contract.
"""

import _bootstrap  # noqa: F401
import json
import threading
import unittest
import urllib.error
import urllib.request

from gpumaid.server import build_server


class FakeMaid:
    """Duck-typed Maid: records calls, returns canned answers."""

    residents = {"demo": {}, "fixed": {}}
    master_off = False

    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"residents": {
                    "demo": {"alive": True, "suspended": False, "wanted": True,
                             "protocol": "process", "vram_gb": 1,
                             "desc": "fake"},
                },
                "master_off": False,
                "gate": {"holder": None, "waiting": []},
                "gpu": {"free_gb": 9.1, "total_gb": 12.0,
                        "util_pct": 3, "temp_c": 42},
                "compute_apps": [{"pid": "1", "name": "x.exe", "mb": 100}]}

    def wake(self, name):
        self.calls.append(("wake", name))
        if name not in self.residents:
            return False, f"unknown resident {name}", {}
        return True, "waking", {}

    def ensure(self, name):
        self.calls.append(("ensure", name))
        return name in self.residents, "already up"

    def sleep(self, name):
        self.calls.append(("sleep", name))
        return name in self.residents, "asleep"

    def mark_busy(self, name):
        self.calls.append(("touch", name))

    def master(self, off, force=False):
        self.calls.append(("master", off))
        return True, "ok"

    def recent_events(self, n=None):
        return [{"ts": "09-24 11:00:00", "msg": "demo woken"}]


class ServerTestBase(unittest.TestCase):
    token = ""

    @classmethod
    def setUpClass(cls):
        cls.maid = FakeMaid()
        cls.srv = build_server(cls.maid, 0, cls.token)
        cls.port = cls.srv.server_address[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _req(self, path, method="GET", headers=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode())
            except ValueError:
                return e.code, {}


class TestRoutes(ServerTestBase):
    def test_health(self):
        st, data = self._req("/health")
        self.assertEqual(st, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["residents"], 2)

    def test_list_shape(self):
        st, data = self._req("/list")
        self.assertEqual(st, 200)
        self.assertEqual(data["gpu"]["temp_c"], 42)
        self.assertIn("demo", data["residents"])
        self.assertIn("gate", data)

    def test_events(self):
        st, data = self._req("/events?n=5")
        self.assertEqual(st, 200)
        self.assertEqual(data["events"][0]["msg"], "demo woken")

    def test_wake_dispatches_to_maid(self):
        st, data = self._req("/wake/demo", method="POST")
        self.assertEqual(st, 200)
        self.assertTrue(data["ok"])
        self.assertIn(("wake", "demo"), self.maid.calls)

    def test_wake_unknown_is_409(self):
        st, data = self._req("/wake/nobody", method="POST")
        self.assertEqual(st, 409)
        self.assertFalse(data["ok"])

    def test_sleep_dispatches(self):
        st, data = self._req("/sleep/demo", method="POST")
        self.assertEqual(st, 200)
        self.assertIn(("sleep", "demo"), self.maid.calls)

    def test_touch_dispatches(self):
        st, _ = self._req("/touch/demo", method="POST")
        self.assertEqual(st, 200)
        self.assertIn(("touch", "demo"), self.maid.calls)

    def test_master_on_off(self):
        st, data = self._req("/master/off", method="POST")
        self.assertEqual(st, 200)
        self.assertTrue(data["ok"])
        self.assertIn(("master", True), self.maid.calls)

    def test_unknown_route_is_404(self):
        st, _ = self._req("/nope")
        self.assertEqual(st, 404)


class TestTokenAuth(ServerTestBase):
    token = "sekrit"

    def test_post_without_token_is_401(self):
        st, data = self._req("/wake/demo", method="POST")
        self.assertEqual(st, 401)
        self.assertIn("token", data["error"])

    def test_post_with_token_passes(self):
        st, data = self._req("/wake/demo", method="POST",
                             headers={"Authorization": "Bearer sekrit"})
        self.assertEqual(st, 200)
        self.assertTrue(data["ok"])

    def test_gets_stay_open(self):
        st, _ = self._req("/list")
        self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main()
