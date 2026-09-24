"""gpu-maid agent package — the VRAM butler for a household GPU box.

Modules:
    config     — residents.json loading and validation
    logic      — pure decision functions (no I/O, unit-testable anywhere)
    telemetry  — nvidia-smi queries, best effort
    maid       — the Maid: registry, watchdog, make-room arbitration
    server     — the HTTP surface
    __main__   — entry point (`python -m gpumaid`)
"""

import sys

__version__ = "0.1.0"

IS_WIN = sys.platform == "win32"
# DETACHED | NEW_PROCESS_GROUP | NO_WINDOW — children must outlive the agent
DETACHED_FLAGS = (0x00000008 | 0x00000200 | 0x08000000) if IS_WIN else 0
