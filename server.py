#!/usr/bin/env python3
"""Run Mangasurf as a LAN server you can drive from a phone.

    python server.py             # http://<this-pc>:8577
    python server.py --gui       # with a small control window

The implementation lives in :mod:`readerm.server`. This file is a thin
wrapper so the command above keeps working from a checkout, while the real
code sits inside the package where PyInstaller's ``collect_submodules``
finds it -- a top-level script is invisible to that, so the packaged exe
shipped without it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from readerm.server import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
