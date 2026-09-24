"""Tests for the CLI: address resolution, connect persistence, rendering."""

import _bootstrap  # noqa: F401
import io
import json
import os
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout

from gpumaid import cli


def _args(**kw):
    return unittest.mock.Mock(url=None, **kw)


class TestBaseUrl(unittest.TestCase):
    def test_env_var_wins(self):
        with unittest.mock.patch.dict(os.environ, {"GPUMAID_URL": "http://1.2.3.4:9700"}):
            self.assertEqual(cli.base_url(_args()), "http://1.2.3.4:9700")

    def test_saved_config_used_when_no_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.json")
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"url": "http://5.6.7.8:9700/"}, f)
            with unittest.mock.patch.object(cli, "CONFIG_PATH", cfg), \
                 unittest.mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GPUMAID_URL", None)
                self.assertEqual(cli.base_url(_args()), "http://5.6.7.8:9700")

    def test_missing_address_exits_with_hint(self):
        os.environ.pop("GPUMAID_URL", None)
        with unittest.mock.patch.object(cli, "CONFIG_PATH", "/nonexistent/x.json"):
            with self.assertRaises(SystemExit):
                cli.base_url(_args())


class TestConnect(unittest.TestCase):
    def test_saves_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.json")
            with unittest.mock.patch.object(cli, "CONFIG_PATH", cfg):
                cli.cmd_connect(_args(address="192.168.1.20:9700"))
            with open(cfg, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["url"],
                                 "http://192.168.1.20:9700")

    def test_full_url_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, "config.json")
            with unittest.mock.patch.object(cli, "CONFIG_PATH", cfg):
                cli.cmd_connect(_args(address="http://box:1234"))
            with open(cfg, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["url"], "http://box:1234")


class TestListRendering(unittest.TestCase):
    FIXTURE = {
        "gpu": {"free_gb": 9.1, "total_gb": 12.0, "util_pct": 3, "temp_c": 42},
        "master_off": False,
        "gate": {"holder": "video", "waiting": ["llm"]},
        "residents": {
            "llm": {"alive": True, "suspended": False, "wanted": True,
                    "protocol": "process", "vram_gb": 5, "desc": "Ollama"},
            "voice": {"alive": False, "suspended": True, "wanted": True,
                      "protocol": "process", "vram_gb": 4, "desc": "TTS"},
        },
        "compute_apps": [{"pid": "123", "name": "ollama.exe", "mb": 4300}],
    }

    def setUp(self):
        # base_url must resolve without touching ~/.gpumaid or sys.exit-ing
        self._env = unittest.mock.patch.dict(
            os.environ, {"GPUMAID_URL": "http://127.0.0.1:9700"})
        self._env.start()
        self.addCleanup(self._env.stop)

    def test_list_prints_gpu_gate_residents_and_apps(self):
        out = io.StringIO()
        with unittest.mock.patch("gpumaid.cli.call",
                                 return_value=(200, self.FIXTURE)), \
             redirect_stdout(out):
            cli.cmd_list(_args())
        text = out.getvalue()
        self.assertIn("GPU free 9.1/12.0 GB", text)
        self.assertIn("42C", text)
        self.assertIn("gate: video is making room", text)
        self.assertIn("llm", text)
        self.assertIn("suspended", text)
        self.assertIn("ollama.exe", text)

    def test_list_degrades_without_telemetry(self):
        fixture = {**self.FIXTURE, "gpu": {"free_gb": None}}
        out = io.StringIO()
        with unittest.mock.patch("gpumaid.cli.call",
                                 return_value=(200, fixture)), \
             redirect_stdout(out):
            cli.cmd_list(_args())
        self.assertIn("nvidia-smi unavailable", out.getvalue())

    def test_events_prints_error_not_silence(self):
        out = io.StringIO()
        with unittest.mock.patch("gpumaid.cli.call",
                                 return_value=(404, {"error": "unknown route"})), \
             redirect_stdout(out):
            cli.cmd_events(_args(n=30))
        self.assertIn("unknown route", out.getvalue())


if __name__ == "__main__":
    unittest.main()
