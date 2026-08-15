#!/usr/bin/env python3
"""Open a window to launch any ReaderM interface.

    python landing.py

The implementation lives in :mod:`readerm.landing`. This file is a thin
wrapper so the command above keeps working from a checkout, while the real
code sits inside the package where PyInstaller can find it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from readerm.landing import run_landing  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_landing())
