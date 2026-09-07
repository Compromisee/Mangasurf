#!/usr/bin/env python3
"""Why are some library books missing from the grid?

Run from the repo root:

    python tests/_diag_library.py

It prints, for every library entry:
  * whether it is dropped by reader_library() (no openable items / locked / hidden)
  * what its directory is and whether that directory exists on disk
  * how many chapter files / archives entry_items() actually found
  * whether it's sitting on a locked shelf or the session-clear flag is on

The Library GRID comes from reader_library() -> books.library_books(), which
drops any entry whose chapter files can't be resolved. "Recently read" comes
from reading.json and is keyed by file path, so it keeps showing a book that
the grid has silently dropped. That mismatch is what this tool exposes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangasurf import library
from mangasurf.reader import books


def main():
    print("=" * 74)
    print("SESSION-CLEAR STATUS: session_cleared = %s" % library.session_cleared())
    print("=" * 74)

    try:
        shelf_store = __import__("mangasurf.shelves", fromlist=["shelves"])
        print("shelves:", len(shelf_store.load_shelves()))
    except Exception as e:
        print("shelves check skipped:", e)

    lib = library.load_library()
    print("library entries:", len(lib))
    print("-" * 74)

    for key, entry in lib.items():
        title = entry.get("title") or entry.get("url") or key
        directory = entry.get("directory") or ""
        has_dir = bool(directory) and os.path.isdir(directory)
        items = books.entry_items(entry)
        outputs = [o for o in (entry.get("outputs") or []) if o and os.path.isfile(o)]
        ch = entry.get("chapters") or {}
        dropped = not items
        print("KEY   : %s" % key)
        print("  title      : %s" % title)
        print("  directory  : %s%s" % (directory or "(none)", "  [EXISTS]" if has_dir else "  [MISSING]"))
        print("  items      : %d  (openable chapters resolved)" % len(items))
        print("  outputs    : %d  (existing packaged archives)" % len(outputs))
        print("  chapters   : %d" % len(ch))
        print("  GRID RESULT: %s" % ("DROPPED (no openable items)" if dropped else "shown"))
        if dropped:
            print("    -> this book is in library.json but the grid can't open it;")
            print("       Recently read may still show it via reading.json.")
        print()

    # The raw reader_library() view for the grid:
    try:
        from mangasurf.reader.api import ReaderApi
        api = ReaderApi()
        grid = api.reader_library()
        print("=" * 74)
        print("reader_library() (the exact grid feed): count=%d" % grid.get("count"))
        for b in grid.get("books", []):
            print("  -", b.get("title"), "| dir:", b.get("directory"))
    except Exception as e:
        print("reader_library probe failed:", e)


if __name__ == "__main__":
    main()
