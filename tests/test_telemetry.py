"""Tests for nvidia-smi output parsing (telemetry)."""

import _bootstrap  # noqa: F401
import unittest
import unittest.mock

from gpumaid import telemetry


def _run_result(stdout: str):
    return unittest.mock.Mock(stdout=stdout.encode())


class TestComputeApps(unittest.TestCase):
    def test_parses_rows(self):
        raw = " 1234, python.exe, 4300\n 5678, ollama.exe, 5120\n"
        with unittest.mock.patch("gpumaid.telemetry.subprocess.run",
                                 return_value=_run_result(raw)):
            apps = telemetry.compute_apps()
        self.assertEqual(apps, [
            {"pid": "1234", "name": "python.exe", "mb": 4300},
            {"pid": "5678", "name": "ollama.exe", "mb": 5120},
        ])

    def test_skips_malformed_rows(self):
        raw = " 1234, python.exe\n , , \n 9, x.exe, [N/A]\n"
        with unittest.mock.patch("gpumaid.telemetry.subprocess.run",
                                 return_value=_run_result(raw)):
            apps = telemetry.compute_apps()
        self.assertEqual(apps, [{"pid": "9", "name": "x.exe", "mb": None}])

    def test_failure_returns_empty(self):
        with unittest.mock.patch("gpumaid.telemetry.subprocess.run",
                                 side_effect=OSError("no smi")):
            self.assertEqual(telemetry.compute_apps(), [])


class TestGpuStatus(unittest.TestCase):
    def test_parses_fields(self):
        with unittest.mock.patch("gpumaid.telemetry.subprocess.run",
                                 return_value=_run_result("2457, 12288, 3, 42")):
            st = telemetry.gpu_status()
        self.assertEqual(st["free_gb"], 2.4)
        self.assertEqual(st["temp_c"], 42)

    def test_failure_returns_nones(self):
        with unittest.mock.patch("gpumaid.telemetry.subprocess.run",
                                 side_effect=OSError("no smi")):
            st = telemetry.gpu_status()
        self.assertIsNone(st["free_gb"])
        self.assertIsNone(st["total_gb"])


if __name__ == "__main__":
    unittest.main()
