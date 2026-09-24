"""Tests for the Maid state machine: wake/sleep/master/gate/events/snapshot."""

import _bootstrap  # noqa: F401
import os
import tempfile
import unittest
import unittest.mock

from gpumaid.config import DEFAULT_POLICIES
from gpumaid.maid import Maid


def _make_maid(state_dir):
    """A Maid with one process resident and one always_on, real policies.

    Process control (_ps_kill / start) is stubbed per-instance: tests must
    never fire real pkill — `pkill -f <pattern>` matches any process whose
    command line merely contains the pattern string, including the test
    runner's own wrapper shell.
    """
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
    maid = Maid(cfg, os.path.join(state_dir, "state.json"))
    maid._ps_kill = unittest.mock.Mock()  # noqa: SLF001 — stub, see docstring
    maid._stubbed_start = maid.start
    maid.start = unittest.mock.Mock()  # noqa: SLF001
    return maid


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

    def test_sleep_confirms_death_before_reporting_asleep(self):
        maid = _make_maid(self.tmp)
        maid.probe = unittest.mock.Mock(return_value=True)  # never dies
        ok, msg = maid.sleep("demo")
        self.assertFalse(ok)
        self.assertIn("still up", msg)
        self.assertFalse(maid.state["demo"]["suspend_req"])

    def test_sleep_reports_asleep_once_port_is_down(self):
        maid = _make_maid(self.tmp)
        maid.probe = unittest.mock.Mock(return_value=False)
        ok, msg = maid.sleep("demo")
        self.assertTrue(ok)
        self.assertEqual(msg, "asleep")
        self.assertTrue(maid.state["demo"]["suspend_req"])

    def test_master_off_persists_across_restart(self):
        _make_maid(self.tmp).master(off=True)
        maid2 = _make_maid(self.tmp)  # same state path: simulates a restart
        maid2.load_state()
        self.assertTrue(maid2.master_off)

    def test_master_on_clears_roster(self):
        maid = _make_maid(self.tmp)
        maid.master(off=True)
        maid.master(off=False)
        self.assertFalse(maid.master_off)
        self.assertFalse(all(st["wanted"] for st in maid.state.values()))

    def test_make_room_skips_without_telemetry(self):
        maid = _make_maid(self.tmp)
        with unittest.mock.patch("gpumaid.maid.gpu_status",
                                 return_value={"free_gb": None}):
            ok, msg = maid.make_room("demo", 4.0)
        self.assertTrue(ok)
        self.assertIn("gate skipped", msg)

    def test_make_room_settles_when_vram_enough(self):
        maid = _make_maid(self.tmp)
        with unittest.mock.patch("gpumaid.maid.gpu_status",
                                 return_value={"free_gb": 9.9}):
            ok, msg = maid.make_room("demo", 4.0)
        self.assertTrue(ok)
        self.assertIn("settled", msg)

    def test_snapshot_shape(self):
        snap = _make_maid(self.tmp).snapshot()
        self.assertIn("demo", snap["residents"])
        self.assertFalse(snap["master_off"])
        self.assertEqual(snap["gate"], {"holder": None, "waiting": []})
        self.assertIsNone(snap["gpu"]["free_gb"])

    def test_mark_busy_updates_anchor(self):
        maid = _make_maid(self.tmp)
        before = maid.state["demo"]["last_busy"]
        maid.state["demo"]["last_busy"] = 0.0
        maid.mark_busy("demo")
        self.assertGreater(maid.state["demo"]["last_busy"], before)
        maid.mark_busy("nobody")  # unknown: silently ignored


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
