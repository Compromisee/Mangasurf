#!/usr/bin/env python3
"""Unified entry point for the packaged executable.

    Mangasurf.exe                 -> the launcher window (pick an interface)
    Mangasurf.exe gui             -> desktop app
    Mangasurf.exe menu            -> interactive terminal menu
    Mangasurf.exe tui             -> full-screen terminal UI
    Mangasurf.exe server          -> LAN server for your phone
    Mangasurf.exe opds            -> OPDS catalog for Readest etc.
    Mangasurf.exe server --gui    -> ...with its control window
    Mangasurf.exe <url> [...]     -> CLI download
    Mangasurf.exe search "query"  -> CLI search
    Mangasurf.exe --help          -> CLI help

Double-clicking opens the **launcher**, not the desktop app directly. The
exe is five programs in one, and a double-click previously committed you to
the GUI with no way to reach the TUI, the menu or the phone server short of
opening a terminal and knowing the subcommand. The launcher makes those
visible, and reaching the desktop app is one click.

``Mangasurf.exe gui`` still goes straight there, so an existing shortcut
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
            from mangasurf.landing import run_landing
            sys.exit(run_landing())
        except ImportError:
            # pywebview missing: fall back to the desktop app, which prints
            # its own explanation, rather than dying with a traceback.
            from mangasurf.gui import run_gui
            sys.exit(run_gui())

    command = args[0]

    if command == "launcher":
        from mangasurf.landing import run_landing
        sys.exit(run_landing())

    if command == "gui":
        from mangasurf.gui import run_gui
        sys.exit(run_gui())

    if command == "server":
        from mangasurf.server import main as server_main
        sys.exit(server_main(args[1:]))

    if command == "opds":
        from mangasurf.opdsserve import main as opds_main
        sys.exit(opds_main(args[1:]))

    from mangasurf.cli import main as cli_main
    sys.exit(cli_main(args))


if __name__ == "__main__":
    main()
