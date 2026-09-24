"""Measured reality: nvidia-smi queries. Best effort — never raises."""

from __future__ import annotations

import subprocess

from .logic import parse_smi_line


def gpu_status():
    """One-shot GPU telemetry: memory, utilization, temperature."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.free,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=8).stdout.decode()
        return parse_smi_line(out)
    except Exception:
        return {"free_gb": None, "total_gb": None, "util_pct": None,
                "temp_c": None}


def compute_apps():
    """Processes currently holding VRAM: [{pid, name, mb}] (best effort).

    On Windows (WDDM) ``--query-compute-apps`` reports 0/blank per-process
    memory; when every row comes back empty we fall back to parsing the
    plain ``nvidia-smi`` process table, which still carries real numbers.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=8).stdout.decode()
    except Exception:
        return []
    apps = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0]:
            apps.append({"pid": parts[0], "name": parts[1],
                         "mb": int(parts[2]) if parts[2].isdigit() else None})
    if any((a["mb"] or 0) > 0 for a in apps):
        return apps
    try:
        out = subprocess.run(["nvidia-smi"], capture_output=True,
                             timeout=8).stdout.decode()
    except Exception:
        return apps
    return parse_smi_table(out) or apps


def parse_smi_table(raw):
    """Parse the process table of plain `nvidia-smi` output."""
    apps = []
    for line in raw.splitlines():
        t = line.strip(" |").split()
        if len(t) >= 7 and t[-1].endswith("MiB"):
            try:
                mb = int(t[-1][:-3])
            except ValueError:
                continue
            apps.append({"pid": t[3], "name": t[5], "mb": mb})
    return apps
