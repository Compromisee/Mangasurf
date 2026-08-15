#!/usr/bin/env python3
"""Launch the ReaderM TUI (no install needed)."""

import sys

from readerm.tui import run_tui

if __name__ == "__main__":
    sys.exit(run_tui())
