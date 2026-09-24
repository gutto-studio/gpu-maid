#!/usr/bin/env python3
"""Thin launcher for source users: `python3 cli/gpumaid.py list`.

The real CLI lives in the gpumaid package (agent/gpumaid/cli.py) and is
also exposed as the `gpumaid` command when pip-installed.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "agent"))

from gpumaid.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
