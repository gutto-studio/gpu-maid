"""Tests for pure decision logic (plan_evictions / should_revive / smi parse)."""

import _bootstrap  # noqa: F401  (sys.path setup)
import unittest

from gpumaid import logic

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


if __name__ == "__main__":
    unittest.main()
