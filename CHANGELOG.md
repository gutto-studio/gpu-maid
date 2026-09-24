# Changelog

## 0.1.0 — first public release (2026-09-24)

- **agent** (`gpumaid` package, stdlib-only): resident registry, VRAM
  make-room gate with measured settle, three resident protocols
  (process / cooperative / always_on), revive watchdog with cooldowns,
  master switch (persisted), idle suspension, drop-in registration
  (`residents.d`), HTTP API with optional token auth, graceful shutdown,
  live telemetry (memory / utilization / temperature / per-process holders
  where the OS reports them)
- **cli**: `connect / list / wake / ensure / sleep / touch / events /
  register / unregister / master on|off`
- **desktop**: first-party macOS menu-bar app (Swift/AppKit, one file) +
  SwiftBar plugin; Windows system-tray companion (PowerShell + WinForms)
- **agent skill** (`skills/gpu-maid/SKILL.md`): teaches coding agents the
  loop and the house rules
- **validation**: 77 unit tests; real-box harness `scripts/validate_on_pc.py`
  (15/15 checks on a live RTX 4070S under render load)
- **packaging/ci**: pyproject with `gpumaid` + `gpumaid-agent` entry points;
  GitHub Actions (Linux/Windows test matrix, markdownlint, macOS compile)
