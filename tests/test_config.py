"""Tests for residents.json validation and policy merging."""

import _bootstrap  # noqa: F401
import json
import os
import tempfile
import unittest

from gpumaid.config import DEFAULT_POLICIES, load_config


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

    def test_policies_merge_overrides_defaults(self):
        cfg = {"residents": {"llm": {"port": 1, "start": "x"}},
               "policies": {"baseline_gb": 1.5}}
        out = load_config(self._write(cfg))
        self.assertEqual(out["policies"]["baseline_gb"], 1.5)
        self.assertEqual(out["policies"]["settle_timeout_s"],
                         DEFAULT_POLICIES["settle_timeout_s"])

    def test_cooperative_requires_sleep_url(self):
        cfg = {"residents": {"img": {"port": 8188, "protocol": "cooperative"}}}
        with self.assertRaises(ValueError):
            load_config(self._write(cfg))

    def test_process_requires_start(self):
        cfg = {"residents": {"x": {"port": 1, "protocol": "process"}}}
        with self.assertRaises(ValueError):
            load_config(self._write(cfg))

    def test_bad_protocol_rejected(self):
        cfg = {"residents": {"x": {"port": 1, "protocol": "magical"}}}
        with self.assertRaises(ValueError):
            load_config(self._write(cfg))

    def test_bad_resident_name_rejected(self):
        cfg = {"residents": {"Bad Name!": {"port": 1, "start": "x"}}}
        with self.assertRaises(ValueError):
            load_config(self._write(cfg))

    def test_probe_or_port_required(self):
        cfg = {"residents": {"x": {"start": "x"}}}
        with self.assertRaises(ValueError):
            load_config(self._write(cfg))

    def test_empty_registry_rejected(self):
        with self.assertRaises(ValueError):
            load_config(self._write({"residents": {}}))


if __name__ == "__main__":
    unittest.main()
