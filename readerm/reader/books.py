"""Turn what ReaderM has on disk into something the reader can open.

A downloaded manga is one of two shapes, and the reader has to handle both:

*   a packaged file — ``.cbz`` / ``.epub`` / ``.pdf`` produced by ``packager``
*   a plain folder of ``.jpg`` pages, which is what a chapter is before (or
    without) packaging

The second case is the common one and the one an ordinary ebook reader cannot
open at all. Rather than zipping folders on the fly, the reader is handed a
page list and streams the images individually, so a chapter is readable the
moment its first pages land.
"""

if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm.reader"

import os
import re

from .. import library
from ..covers import SKIP_DIRS, images_in
from ..covers import IMAGE_EXTENSIONS as _COVER_IMAGE_EXTENSIONS

#: ``covers.IMAGE_EXTENSIONS`` is a tuple used with ``str.endswith``; a set is
#: wanted here for membership tests. Derived rather than duplicated so the two
#: cannot drift apart.
IMAGE_EXTENSIONS = set(_COVER_IMAGE_EXTENSIONS)

BOOK_EXTENSIONS = {".cbz", ".epub", ".pdf", ".mobi", ".azw3", ".fb2", ".cbr"}

#: Formats the vendored engine can actually render. ``.cbr`` is RAR, which
#: needs an unrar binary we do not ship, so it is listed as known-but-unopenable
#: rather than silently failing in the browser.
READABLE_EXTENSIONS = {".cbz", ".epub", ".pdf", ".mobi", ".azw3", ".fb2"}


def _natural_key(name: str):
    """Sort ``page2`` before ``page10``."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", name)]


def chapter_folders(root: str) -> list:
    """Every folder under ``root`` that directly holds page images."""
    found = []
    if not root or not os.path.isdir(root):
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in SKIP_DIRS)
        pages = [f for f in filenames
                 if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS
                 and not f.lower().startswith("cover.")]
        if pages:
            found.append(dirpath)
    found.sort(key=lambda p: _natural_key(os.path.basename(p)))
    return found


def pages_of(folder: str) -> list:
    """Page images in a chapter folder, in reading order (absolute paths).

    ``covers.images_in`` returns bare file names and already drops cover files
    and sorts numerically, so this only has to make the paths absolute.
    """
    if not folder or not os.path.isdir(folder):
        return []
    return [os.path.join(folder, name) for name in images_in(folder)]


def is_readable(path: str) -> bool:
    ext = os.path.splitext(path or "")[1].lower()
    return ext in READABLE_EXTENSIONS


def describe(path: str) -> dict:
    """What kind of thing is this, and how many pages does it have?"""
    path = os.path.abspath(path or "")
    if os.path.isdir(path):
        pages = pages_of(path)
        return {
            "kind": "folder",
            "path": path,
            "name": os.path.basename(path),
            "pages": len(pages),
            "readable": bool(pages),
        }
    ext = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path) if os.path.isfile(path) else 0
    return {
        "kind": "file",
        "path": path,
        "name": os.path.basename(path),
        "format": ext.lstrip("."),
        "size": size,
        "readable": is_readable(path) and os.path.isfile(path),
        "reason": ("unrar is not bundled, so .cbr cannot be opened"
                   if ext == ".cbr" else ""),
    }


def entry_items(entry: dict) -> list:
    """Everything openable for one library entry, newest-looking first.

    Packaged outputs come first because they are a single seekable file and the
    engine handles them natively; loose chapter folders follow.
    """
    items = []
    seen = set()

    for out in entry.get("outputs") or []:
        if not out or out in seen or not os.path.isfile(out):
            continue
        seen.add(out)
        info = describe(out)
        info["label"] = os.path.splitext(os.path.basename(out))[0]
        items.append(info)

    directory = entry.get("directory")
    if directory and os.path.isdir(directory):
        for folder in chapter_folders(directory):
            if folder in seen:
                continue
            seen.add(folder)
            info = describe(folder)
            if not info["readable"]:
                continue
            info["label"] = os.path.basename(folder)
            items.append(info)

    return items


def library_books() -> list:
    """The whole downloaded library, as reader-openable entries."""
    books = []
    for entry in library.load_library().values():
        items = entry_items(entry)
        if not items:
            continue
        books.append({
            "title": entry.get("title") or "Untitled",
            "url": entry.get("url") or "",
            "source": entry.get("source") or "",
            "cover": entry.get("cover") or "",
            "directory": entry.get("directory") or "",
            "added": entry.get("added") or "",
            "last_download": entry.get("last_download") or "",
            "chapters": len(entry.get("chapters") or {}),
            "items": items,
        })
    books.sort(key=lambda b: (b.get("last_download") or b.get("added") or ""),
               reverse=True)
    return books


def roots_for(entry: dict) -> list:
    """Directories the asset server must allow to serve this entry."""
    roots = []
    directory = entry.get("directory")
    if directory:
        roots.append(directory)
    for out in entry.get("outputs") or []:
        if out:
            roots.append(os.path.dirname(out))
    return [r for r in roots if r and os.path.isdir(r)]
