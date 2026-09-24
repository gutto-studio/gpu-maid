"""Tests for the gpu-maid agent — pure logic + Maid state machine.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from gpumaid import logic  # noqa: E402
from gpumaid.config import DEFAULT_POLICIES, load_config  # noqa: E402
from gpumaid.maid import Maid  # noqa: E402

RESIDENTS = {
    "llm": {"protocol": "process", "vram_gb": 5},
    "image": {"protocol": "cooperative", "vram_gb": 8},
    "voice": {"protocol": "process", "vram_gb": 4},
    "widget": {"protocol": "always_on", "vram_gb": 1},
}
STATES_UP = {
    "llm": {"alive": True, "suspend_req": False},
    "image": {"alive": True, "suspend_req": False},
    "voice": {"alive": False, "suspend_req": False},
    "widget": {"alive": True, "suspend_req": False},
}


class TestPlanEvictions(unittest.TestCase):
    def test_no_eviction_when_room_enough(self):
        evict, short = logic.plan_evictions(RESIDENTS, STATES_UP, 10.0, 8.0,
                                            "video", 0.5)
        self.assertEqual(evict, [])
        self.assertEqual(short, 0.0)

    def test_evicts_largest_first_and_skips_always_on_and_target(self):
        # need 12 free, have 9.5 -> short 3.0 -> evict llm (5) alone;
        # widget (always_on) and the target itself must never be touched.
        evict, short = logic.plan_evictions(RESIDENTS, STATES_UP, 9.5, 12.0,
                                            "image", 0.5)
        self.assertEqual(evict, ["llm"])
        self.assertEqual(short, 0.0)

    def test_multiple_evictions_by_size_desc(self):
        evict, short = logic.plan_evictions(RESIDENTS, STATES_UP, 1.0, 12.0,
                                            "video", 0.5)
        self.assertEqual(evict, ["image", "llm"])  # 8 then 5, largest first
        self.assertEqual(short, 0.0)

    def test_reports_shortage_when_even_evictions_cannot_fit(self):
        evict, short = logic.plan_evictions(RESIDENTS, STATES_UP, 1.0, 50.0,
                                            "video", 0.5)
        self.assertEqual(evict, ["image", "llm"])
        self.assertGreater(short, 0.0)

    def test_unknown_vram_disables_planning(self):
        evict, short = logic.plan_evictions(RESIDENTS, STATES_UP, None, 8.0,
                                            "video", 0.5)
        self.assertEqual((evict, short), ([], 0.0))

    def test_skips_already_suspended(self):
        states = {**STATES_UP, "llm": {"alive": True, "suspend_req": True}}
        evict, _ = logic.plan_evictions(RESIDENTS, states, 9.5, 12.0,
                                        "image", 0.5)
        self.assertEqual(evict, [])


class TestShouldRevive(unittest.TestCase):
    POLICIES = {"fails_to_revive": 3, "revive_cooldown_s": 300}

    def _st(self, **kw):
        st = {"fails": 0, "last_revive": 0.0, "suspend_req": False,
              "wanted": True}
        st.update(kw)
        return st

    def test_needs_consecutive_fails(self):
        self.assertFalse(logic.should_revive(self._st(fails=2), 1000,
                                             self.POLICIES))
        self.assertTrue(logic.should_revive(self._st(fails=3), 1000,
                                            self.POLICIES))

    def test_cooldown_blocks_machine_gunning(self):
        self.assertTrue(logic.should_revive(self._st(fails=3, last_revive=0),
                                            301, self.POLICIES))
        self.assertFalse(logic.should_revive(self._st(fails=3, last_revive=100),
                                             300, self.POLICIES))

    def test_suspended_or_unwanted_stay_down(self):
        self.assertFalse(logic.should_revive(
            self._st(fails=3, suspend_req=True), 10_000, self.POLICIES))
        self.assertFalse(logic.should_revive(
            self._st(fails=3, wanted=False), 10_000, self.POLICIES))


class TestParseSmiLine(unittest.TestCase):
    def test_full_line(self):
        st = logic.parse_smi_line("2457, 12288, 3, 42")
        self.assertEqual(st, {"free_gb": 2.4, "total_gb": 12.0,
                              "util_pct": 3, "temp_c": 42})

    def test_na_fields_parse_as_none(self):
        st = logic.parse_smi_line("2457, 12288, [N/A], [N/A]")
        self.assertEqual(st["free_gb"], 2.4)
        self.assertIsNone(st["util_pct"])
        self.assertIsNone(st["temp_c"])

    def test_garbage_is_all_none(self):
        st = logic.parse_smi_line("")
        self.assertIsNone(st["free_gb"])
        self.assertIsNone(st["temp_c"])


class TestConfigValidation(unittest.TestCase):
    def _write(self, cfg):
        p = os.path.join(self.tmp, "residents.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return p

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_minimal_process_resident_ok(self):
        cfg = {"residents": {"llm": {"port": 11434, "start": "ollama serve"}}}
        out = load_config(self._write(cfg))
        self.assertEqual(out["policies"]["fails_to_revive"],
                         DEFAULT_POLICIES["fails_to_revive"])

    def test_cooperative_requires_sleep_url(self):
        cfg = {"residents": {"img": {"port": 8188, "protocol": "cooperative"}}}
        with self.assertRaises(ValueError):
            load_config(self._write(cfg))

    def test_empty_registry_rejected(self):
        with self.assertRaises(ValueError):
            load_config(self._write({"residents": {}}))


def _make_maid(state_dir):
    """A Maid with one process resident and one always_on, real policies."""
    cfg = {
        "residents": {
            "demo": {"protocol": "process", "port": 9751,
                     "start": "echo demo", "kill_pat": "demo_pat",
                     "vram_gb": 1},
            "fixed": {"protocol": "always_on", "port": 9752},
        },
        "policies": dict(DEFAULT_POLICIES),
        "server": {},
    }
    return Maid(cfg, os.path.join(state_dir, "state.json"))


class TestMaid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_wake_unknown_resident(self):
        ok, msg, _ = _make_maid(self.tmp).wake("nobody")
        self.assertFalse(ok)
        self.assertIn("unknown", msg)

    def test_wake_refused_when_master_off(self):
        maid = _make_maid(self.tmp)
        maid.master_off = True
        ok, msg, _ = maid.wake("demo")
        self.assertFalse(ok)
        self.assertIn("master switch is OFF", msg)

    def test_always_on_never_sleeps(self):
        ok, msg = _make_maid(self.tmp).sleep("fixed")
        self.assertFalse(ok)
        self.assertIn("never", msg)

    def test_master_off_persists_across_restart(self):
        _make_maid(self.tmp).master(off=True)
        maid2 = _make_maid(self.tmp)  # same state path: simulates a restart
        maid2.load_state()
        self.assertTrue(maid2.master_off)

    def test_make_room_skips_without_telemetry(self):
        maid = _make_maid(self.tmp)
        with unittest.mock.patch("gpumaid.maid.gpu_status",
                                 return_value={"free_gb": None}):
            ok, msg = maid.make_room("demo", 4.0)
        self.assertTrue(ok)
        self.assertIn("gate skipped", msg)

    def test_snapshot_shape(self):
        snap = _make_maid(self.tmp).snapshot()
        self.assertIn("demo", snap["residents"])
        self.assertFalse(snap["master_off"])
        self.assertEqual(snap["gate"], {"holder": None, "waiting": []})
        self.assertIsNone(snap["gpu"]["free_gb"])


class TestEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_transitions_are_recorded(self):
        maid = _make_maid(self.tmp)
        maid.master(off=True)
        msgs = [e["msg"] for e in maid.events]
        self.assertTrue(any("MASTER OFF" in m for m in msgs))
        self.assertTrue(any("asleep" in m for m in msgs))
        for e in maid.events:
            self.assertIn("ts", e)

    def test_recent_events_slice(self):
        maid = _make_maid(self.tmp)
        maid.master(off=True)
        self.assertEqual(len(maid.recent_events(1)), 1)
        self.assertGreaterEqual(len(maid.recent_events()), 2)


if __name__ == "__main__":
    unittest.main()
