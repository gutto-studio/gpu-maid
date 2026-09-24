"""Tests for the SwiftBar menu-bar plugin (loaded standalone via importlib)."""

import _bootstrap  # noqa: F401
import importlib.util
import os
import unittest

PLUGIN = os.path.join(os.path.dirname(__file__), "..", "menubar",
                      "gpu-maid.5s.py")
spec = importlib.util.spec_from_file_location("gpumaid_menubar", PLUGIN)
mb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mb)

FIXTURE = {
    "gpu": {"free_gb": 9.1, "total_gb": 12.0, "util_pct": 3, "temp_c": 42},
    "master_off": False,
    "gate": {"holder": None, "waiting": []},
    "residents": {
        "llm": {"alive": True, "suspended": False, "wanted": True,
                "protocol": "process", "vram_gb": 5, "desc": "Ollama"},
        "voice": {"alive": False, "suspended": True, "wanted": True,
                  "protocol": "process", "vram_gb": 4, "desc": "TTS"},
    },
    "compute_apps": [{"pid": "7", "name": "ollama.exe", "mb": 4300}],
}


class TestRender(unittest.TestCase):
    def test_bar_line_shows_gpu_state(self):
        out = mb.render(FIXTURE)
        first = out.splitlines()[0]
        self.assertIn("GPU 9.1/12.0G", first)
        self.assertIn("42°C", first)
        self.assertIn("color=green", first)

    def test_residents_rendered_with_actions(self):
        out = mb.render(FIXTURE)
        self.assertIn("● llm", out)
        self.assertIn("-- wake voice", out)
        self.assertIn("-- sleep llm", out)
        self.assertIn("terminal=false", out)  # actions don't pop a terminal

    def test_gate_line_when_busy(self):
        fx = {**FIXTURE, "gate": {"holder": "video", "waiting": ["llm"]}}
        self.assertIn("making room: video", mb.render(fx))

    def test_master_off_variant(self):
        fx = {**FIXTURE, "master_off": True}
        first = mb.render(fx).splitlines()[0]
        self.assertIn("color=purple", first)
        self.assertIn("master on", mb.render(fx))

    def test_no_telemetry_degrades(self):
        fx = {**FIXTURE, "gpu": {"free_gb": None}}
        self.assertIn("color=gray", mb.render(fx).splitlines()[0])

    def test_events_section(self):
        out = mb.render(FIXTURE, events=[{"ts": "09-24 11:00:00",
                                          "msg": "demo woken"}])
        self.assertIn("demo woken", out)


if __name__ == "__main__":
    unittest.main()
