#!/usr/bin/env python3
"""Launch the Mangasurf GUI."""

import multiprocessing
import sys

from mangasurf.gui import run_gui


def main():
    multiprocessing.freeze_support()
    sys.exit(run_gui())


if __name__ == "__main__":
    main()
