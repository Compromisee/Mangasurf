#!/usr/bin/env python3
"""Serve your downloaded library as an OPDS catalog for Readest and friends.

    python opdsserve.py             # http://<this-pc>:8578/opds
    python opdsserve.py --gui       # with a control window

The implementation lives in :mod:`readerm.opdsserve`. This file is a thin
wrapper so the command above works from a checkout, while the real code sits
inside the package where PyInstaller can find it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from readerm.opdsserve import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
