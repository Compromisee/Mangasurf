#!/usr/bin/env python3
"""Unified entry point for the packaged executable.

    ReaderM.exe                 -> the launcher window (pick an interface)
    ReaderM.exe gui             -> desktop app
    ReaderM.exe menu            -> interactive terminal menu
    ReaderM.exe tui             -> full-screen terminal UI
    ReaderM.exe server          -> LAN server for your phone
    ReaderM.exe opds            -> OPDS catalog for Readest etc.
    ReaderM.exe server --gui    -> ...with its control window
    ReaderM.exe <url> [...]     -> CLI download
    ReaderM.exe search "query"  -> CLI search
    ReaderM.exe --help          -> CLI help

Double-clicking opens the **launcher**, not the desktop app directly. The
exe is five programs in one, and a double-click previously committed you to
the GUI with no way to reach the TUI, the menu or the phone server short of
opening a terminal and knowing the subcommand. The launcher makes those
visible, and reaching the desktop app is one click.

``ReaderM.exe gui`` still goes straight there, so an existing shortcut
keeps its behaviour.
"""

import multiprocessing
import sys


def main():
    # Required for PyInstaller: worker threads/processes must not re-launch
    # the whole app when they spawn.
    multiprocessing.freeze_support()

    args = sys.argv[1:]

    # No arguments -> the launcher window.
    if not args:
        try:
            from readerm.landing import run_landing
            sys.exit(run_landing())
        except ImportError:
            # pywebview missing: fall back to the desktop app, which prints
            # its own explanation, rather than dying with a traceback.
            from readerm.gui import run_gui
            sys.exit(run_gui())

    command = args[0]

    if command == "launcher":
        from readerm.landing import run_landing
        sys.exit(run_landing())

    if command == "gui":
        from readerm.gui import run_gui
        sys.exit(run_gui())

    if command == "server":
        from readerm.server import main as server_main
        sys.exit(server_main(args[1:]))

    if command == "opds":
        from readerm.opdsserve import main as opds_main
        sys.exit(opds_main(args[1:]))

    from readerm.cli import main as cli_main
    sys.exit(cli_main(args))


if __name__ == "__main__":
    main()
