#!/usr/bin/env python3
"""Launch the Mangasurf GUI or CLI."""

import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    args = sys.argv[1:]
    if not args or args[0] in ("gui", "--gui"):
        from mangasurf.gui import run_gui
        sys.exit(run_gui())

    from launcher import main as launcher_main
    launcher_main()


if __name__ == "__main__":
    main()
