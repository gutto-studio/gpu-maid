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


class TestSmiTableFallback(unittest.TestCase):
    TABLE = """
+-----------------------------------------------------------------------------+
| Processes:                                                                  |
|  GPU   GI   CI        PID   Type   Process name                  GPU Memory |
|        ID   ID                                                       Usage      |
|=============================================================================|
|    0   N/A  N/A      1234    C   python.exe                     10735MiB   |
|    0   N/A  N/A      5678    C   dwm.exe                            0MiB   |
+-----------------------------------------------------------------------------+
"""

    def test_parses_real_holders(self):
        apps = telemetry.parse_smi_table(self.TABLE)
        self.assertIn({"pid": "1234", "name": "python.exe", "mb": 10735},
                      apps)

    def test_parses_every_table_row_faithfully(self):
        apps = telemetry.parse_smi_table(self.TABLE)
        self.assertEqual(len(apps), 2)  # headers ignored, zero-mb kept
        self.assertEqual(
            [a["mb"] for a in apps if a["name"] == "dwm.exe"], [0])

    def test_compute_apps_falls_back_when_query_reports_zero(self):
        query = unittest.mock.Mock(stdout=b" 1234, python.exe, 0\n")
        table = unittest.mock.Mock(stdout=self.TABLE.encode())
        with unittest.mock.patch("gpumaid.telemetry.subprocess.run",
                                 side_effect=[query, table]):
            apps = telemetry.compute_apps()
        self.assertIn({"pid": "1234", "name": "python.exe", "mb": 10735},
                      apps)


if __name__ == "__main__":
    unittest.main()
