"""Reader-side endpoints, mixed into the existing GUI ``Api``.

These are deliberately a *mixin* rather than a new API object. The GUI already
exposes 127 methods that the CLI, TUI, phone server and OPDS catalog all lean
on; replacing that wholesale would break every one of them. The reader adds the
handful of calls it needs on top and inherits the rest.

Reading position lives in ``~/.readerm/reading.json``, separate from
``tracking.py``'s read/unread marks. They answer different questions — "have I
finished this chapter" versus "which page and how far down it was I on" — and
keeping them apart means a resync of one cannot corrupt the other.
"""

if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm.reader"

import json
import logging
import os
import secrets
import threading
import time

from .. import library
from .. import shelves as shelf_store
from ..covers import COVER_NAMES
from . import books
from .assets import AssetServer

logger = logging.getLogger(__name__)

from ..paths import ensure as _ensure_data_dir

#: Created on first use, and populated from a MangaDL install if one
#: exists -- see readerm.paths.migrate.
DIR = _ensure_data_dir()
READING_PATH = os.path.join(DIR, "reading.json")
ANNOTATIONS_PATH = os.path.join(DIR, "annotations.json")

_lock = threading.RLock()

#: Reading preferences the reader owns. Merged into the GUI's DEFAULT_SETTINGS
#: so they are saved and loaded by the same config machinery as everything else.
READER_DEFAULTS = {
    "reader_mode": "webtoon",          # webtoon | vertical | ltr | rtl
    "reader_theme": "midnight",
    "reader_fit": "contain",           # contain | width | height | original
    "reader_gap": 0,
    "reader_max_width": "100%",
    "reader_spread": False,
    "reader_filter": "none",           # none | dim | dimmer | invert | sepia | gray
    "reader_zoom": 1.0,
    "reader_keep_position": True,
    "reader_fullscreen_default": False,
    "reader_preload": 3,
    "reader_tap_zones": True,
    "reader_animate": True,
    "reader_autoscroll_speed": 60,
}


def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path or ""))


def load_positions() -> dict:
    return _load(READING_PATH, {})


def save_position(path: str, index: int = 0, fraction: float = 0.0,
                  total: int = 0, mode: str = "", title: str = "") -> dict:
    """Remember where reading stopped in one book or chapter."""
    with _lock:
        data = _load(READING_PATH, {})
        record = {
            "path": os.path.abspath(path or ""),
            "index": int(index or 0),
            "fraction": round(float(fraction or 0.0), 4),
            "total": int(total or 0),
            "mode": mode or "",
            "title": title or "",
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        data[_key(path)] = record
        _save(READING_PATH, data)
        return record


def get_position(path: str) -> dict:
    return load_positions().get(_key(path)) or {}


def clear_positions(path: str = None) -> int:
    with _lock:
        data = _load(READING_PATH, {})
        if path is None:
            count = len(data)
            _save(READING_PATH, {})
            return count
        if _key(path) in data:
            del data[_key(path)]
            _save(READING_PATH, data)
            return 1
        return 0


def load_annotations(path: str = None) -> dict:
    data = _load(ANNOTATIONS_PATH, {})
    if path is None:
        return data
    return data.get(_key(path)) or {"bookmarks": [], "notes": []}


def save_annotation(path: str, kind: str, payload: dict) -> dict:
    """Add a bookmark or a note. Returns the stored record."""
    kind = "bookmarks" if kind == "bookmark" else "notes"
    with _lock:
        data = _load(ANNOTATIONS_PATH, {})
        book = data.setdefault(_key(path), {"bookmarks": [], "notes": []})
        record = dict(payload or {})
        # A millisecond timestamp is not unique enough: adding a bookmark and a
        # note in the same tick produced two records with the same id, and
        # deleting one then matched both. Measured collision, so ids get a
        # random suffix.
        record.setdefault("id", f"{int(time.time() * 1000):x}{secrets.token_hex(4)}")
        record["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        book.setdefault(kind, []).append(record)
        _save(ANNOTATIONS_PATH, data)
        return record


def delete_annotation(path: str, kind: str, ident: str) -> bool:
    kind = "bookmarks" if kind == "bookmark" else "notes"
    with _lock:
        data = _load(ANNOTATIONS_PATH, {})
        book = data.get(_key(path))
        if not book:
            return False
        before = len(book.get(kind) or [])
        book[kind] = [r for r in book.get(kind) or [] if str(r.get("id")) != str(ident)]
        if len(book[kind]) == before:
            return False
        _save(ANNOTATIONS_PATH, data)
        return True


class ReaderApi:
    """Reader endpoints. Mixed into the GUI ``Api``.

    Every method returns a plain dict; the GUI's ``_SafeApiMeta`` turns any
    exception into ``{"ok": False, "error": ...}``, so these can stay readable
    and let genuine failures surface rather than swallowing them here.
    """

    _assets = None
    _assets_lock = threading.RLock()

    # ------------------------------------------------------------ asset server

    def _asset_server(self) -> AssetServer:
        with ReaderApi._assets_lock:
            if ReaderApi._assets is None:
                # `self` is the full GUI Api (ReaderApi is mixed into it), so
                # handing it over is what lets the front-end's HTTP fallback
                # reach the same methods the pywebview bridge exposes. Without
                # it every POST to /_api/ answered 501 and the interface came
                # up with no settings, no library and no sources.
                server = AssetServer(api=self)
                server.start()
                ReaderApi._assets = server
            elif ReaderApi._assets.api is None:
                ReaderApi._assets.api = self
            return ReaderApi._assets

    def reader_info(self):
        """Where the reader is served and the token to reach it."""
        server = self._asset_server()
        return {
            "ok": True,
            "port": server.port,
            "token": server.token,
            "base": f"http://127.0.0.1:{server.port}",
            "url": server.url("/"),
        }

    # ------------------------------------------------------------------ library

    def cover_src(self, cover: str) -> str:
        """A cover the browser can actually load.

        The library stores whatever the source gave it, which is usually an
        absolute path on disk -- ``/home/you/Downloads/Series/cover.jpg``. A
        page served over http cannot load that, so every downloaded series
        showed "No cover" no matter how good the file was. Local files are
        served through the asset server instead; remote URLs are passed
        through untouched.
        """
        cover = (cover or "").strip()
        if not cover:
            return ""
        if cover.startswith(("http://", "https://", "data:")):
            return cover
        if not os.path.isfile(cover):
            return ""
        server = self._asset_server()
        server.allow(os.path.dirname(cover))
        return server.url(f"/page?path={_q(cover)}")

    def reader_library(self, include_locked: bool = False):
        """Everything downloaded, as things the reader can open.

        Books on a locked shelf are withheld. The tree hiding them is not
        enough on its own: the main grid is fed by this call, so a lock that
        only filtered the sidebar left every hidden title sitting in the grid
        next to the padlock -- measured, and visible in the screenshots.
        """
        items = books.library_books()
        positions = load_positions()
        for book in items:
            book["cover"] = self.cover_src(book.get("cover"))
            # Shelves file books by this key, so it has to travel with them.
            book["key"] = library._key(book.get("url") or "") or book.get("directory") or ""
            for item in book["items"]:
                pos = positions.get(_key(item["path"]))
                if pos:
                    item["position"] = pos

        hidden = 0
        if not include_locked:
            secret = self._locked_book_keys()
            if secret:
                kept = [b for b in items if b["key"] not in secret]
                hidden = len(items) - len(kept)
                items = kept
        return {"ok": True, "books": items, "count": len(items), "hidden": hidden}

    def _locked_book_keys(self) -> set:
        """Book keys sitting on a shelf that is locked and not yet opened."""
        locked = shelf_store.locked_ids() - set(ReaderApi._unlocked_shelves)
        if not locked:
            return set()
        keys = set()
        for shelf in shelf_store._load():
            if shelf.get("id") in locked:
                keys.update(shelf.get("books") or [])
        return keys

    def _locked_paths(self) -> list:
        """Directories belonging to locked books.

        Reading positions are keyed by path, so hiding a locked book from the
        continue-reading row means going from shelf keys back to folders on
        disk.
        """
        keys = self._locked_book_keys()
        if not keys:
            return []
        roots = []
        for entry in library.load_library().values():
            key = library._key(entry.get("url") or "") or entry.get("directory") or ""
            if key not in keys:
                continue
            if entry.get("directory"):
                roots.append(os.path.abspath(entry["directory"]))
            for out in entry.get("outputs") or []:
                if out:
                    roots.append(os.path.abspath(out))
        return roots

    @staticmethod
    def _is_under(path: str, roots) -> bool:
        """True when *path* is one of *roots* or sits inside one.

        Uses commonpath rather than startswith: "/library/Foo2" starts with
        "/library/Foo" as a string but is a different folder.
        """
        if not roots:
            return False
        target = os.path.abspath(path or "")
        for root in roots:
            if target == root:
                return True
            try:
                if os.path.commonpath([target, root]) == root:
                    return True
            except ValueError:          # different drives on Windows
                continue
        return False

    # ------------------------------------------------------------- shelves

    #: Shelf ids the user has unlocked in this run. Deliberately in memory
    #: only: closing the app re-locks every shelf, which is what a lock is
    #: for. Persisting it would make "locked" mean "locked once, ever".
    _unlocked_shelves = set()

    def shelf_tree(self):
        """The library as a tree of shelves, for the left-hand sidebar.

        Locked shelves come back with their contents removed rather than
        merely flagged -- filtering in the browser would still have shipped
        every hidden title to the page.
        """
        # Asks for the unfiltered list on purpose: shelf_store.tree() does the
        # hiding itself, and it needs the locked books present to report an
        # honest "12 hidden" count. It still never returns their titles.
        library_books = self.reader_library(include_locked=True).get("books", [])
        data = shelf_store.tree(library_books,
                                unlocked=ReaderApi._unlocked_shelves)
        return {"ok": True, **data}

    def shelf_list(self):
        return {"ok": True, "shelves": shelf_store.load_shelves()}

    def shelf_create(self, name: str, parent: str = "", colour: str = "",
                     tags=None, pinned: bool = False):
        return shelf_store.create(name, parent=parent, colour=colour,
                                  tags=tags, pinned=pinned)

    def shelf_rename(self, shelf_id: str, name: str):
        return shelf_store.rename(shelf_id, name)

    def shelf_update(self, shelf_id: str, **changes):
        return shelf_store.update(shelf_id, **changes)

    def shelf_set_parent(self, shelf_id: str, parent: str = ""):
        return shelf_store.set_parent(shelf_id, parent)

    def shelf_delete(self, shelf_id: str, recursive: bool = False):
        return shelf_store.delete(shelf_id, recursive=recursive)

    def shelf_add_book(self, shelf_id: str, key: str):
        return shelf_store.add_book(shelf_id, key)

    def shelf_remove_book(self, shelf_id: str, key: str):
        return shelf_store.remove_book(shelf_id, key)

    def shelf_move_book(self, key: str, shelf_id: str = ""):
        return shelf_store.move_book(key, shelf_id)

    def shelf_tags(self):
        return {"ok": True, "tags": shelf_store.all_tags()}

    def shelf_set_tags(self, shelf_id: str, tags=None):
        return shelf_store.set_tags(shelf_id, tags)

    def shelf_set_lock(self, shelf_id: str, passcode: str,
                       pin_to_open: bool = True):
        result = shelf_store.set_lock(shelf_id, passcode, pin_to_open=pin_to_open)
        if result.get("ok"):
            # Locking a shelf you are looking at should take effect at once.
            ReaderApi._unlocked_shelves.discard(shelf_id)
        return result

    def shelf_unlock(self, shelf_id: str, passcode: str = ""):
        result = shelf_store.unlock(shelf_id, passcode)
        if result.get("ok"):
            ReaderApi._unlocked_shelves.add(shelf_id)
        return result

    def shelf_lock_now(self, shelf_id: str = ""):
        """Re-lock one shelf, or every shelf when no id is given."""
        if shelf_id:
            ReaderApi._unlocked_shelves.discard(shelf_id)
        else:
            ReaderApi._unlocked_shelves.clear()
        return {"ok": True}

    def shelf_clear_lock(self, shelf_id: str, passcode: str = ""):
        return shelf_store.clear_lock(shelf_id, passcode)

    def reader_recent(self, limit: int = 12):
        """Continue-reading shelf: most recently opened, still on disk.

        Also honours shelf locks. This list is built from reading *positions*,
        which are keyed by file path and never went near a shelf -- so locking
        a shelf hid it from the grid and the tree while the book stayed on the
        continue-reading row, complete with title and cover. Measured.
        """
        positions = sorted(load_positions().values(),
                           key=lambda r: r.get("at") or "", reverse=True)
        secret = self._locked_paths()
        out = []
        for record in positions:
            path = record.get("path") or ""
            if not path or not os.path.exists(path):
                continue
            if self._is_under(path, secret):
                continue
            row = {**record, **books.describe(path)}
            # The shelf rendered an empty square: nothing here ever supplied a
            # cover, so there was nothing for the thumbnail to show.
            row["cover"] = self.folder_cover(path)
            out.append(row)
            if len(out) >= max(1, int(limit or 12)):
                break
        return {"ok": True, "items": out}

    # --------------------------------------------------------------- opening

    def folder_cover(self, path: str) -> str:
        """The cover.ext sitting beside a chapter, for the reader's book icon.

        Looks in the chapter folder and then the series folder above it, which
        is where ``covers.propagate_covers`` puts one.
        """
        path = os.path.abspath((path or "").strip())
        if not path:
            return ""
        folders = [path if os.path.isdir(path) else os.path.dirname(path)]
        folders.append(os.path.dirname(folders[0]))
        for folder in folders:
            for name in COVER_NAMES:
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate):
                    return self.cover_src(candidate)
        return ""

    def reader_open(self, path: str):
        """Prepare a book or chapter folder for reading.

        Returns the URLs the front-end should load — either one ``/book`` URL
        for a packaged file, or a page list for a loose chapter folder.
        """
        path = os.path.abspath((path or "").strip())
        if not path or not os.path.exists(path):
            return {"ok": False, "error": "Not found"}

        # Hiding a book from the lists is not the same as refusing to open it.
        # A path is easy to keep -- in a bookmark, in reading.json, in a link
        # someone typed -- so the lock is enforced here as well.
        if self._is_under(path, self._locked_paths()):
            return {"ok": False, "error": "That book is on a locked shelf",
                    "locked": True}

        server = self._asset_server()
        info = books.describe(path)

        if info["kind"] == "folder":
            pages = books.pages_of(path)
            if not pages:
                return {"ok": False, "error": "No page images in that folder"}
            server.allow(path)
            return {
                "ok": True,
                "kind": "pages",
                "title": info["name"],
                "path": path,
                "pages": [server.url(f"/page?path={_q(p)}") for p in pages],
                # The sidebar lists pages by name, the way the screenshot
                # shows ("000000/000001.jpg"), so send the names alongside.
                "names": [os.path.relpath(p, path).replace(os.sep, "/")
                          for p in pages],
                "count": len(pages),
                "cover": self.folder_cover(path),
                "position": get_position(path),
            }

        if not info["readable"]:
            return {"ok": False,
                    "error": info.get("reason") or "That file type cannot be opened"}

        server.allow(os.path.dirname(path))
        server.allow(path)
        return {
            "ok": True,
            "kind": "file",
            "title": info["name"],
            "path": path,
            "format": info.get("format", ""),
            "url": server.url(f"/book?path={_q(path)}"),
            "cover": self.folder_cover(path),
            "position": get_position(path),
        }

    def reader_open_next(self, path: str):
        """The next chapter folder after this one, for read-through."""
        path = os.path.abspath((path or "").strip())
        parent = os.path.dirname(path)
        siblings = books.chapter_folders(parent)
        if path not in siblings:
            return {"ok": False, "error": "No next chapter"}
        index = siblings.index(path)
        if index + 1 >= len(siblings):
            return {"ok": False, "error": "That was the last chapter"}
        return self.reader_open(siblings[index + 1])

    def reader_open_previous(self, path: str):
        path = os.path.abspath((path or "").strip())
        parent = os.path.dirname(path)
        siblings = books.chapter_folders(parent)
        if path not in siblings:
            return {"ok": False, "error": "No previous chapter"}
        index = siblings.index(path)
        if index <= 0:
            return {"ok": False, "error": "That was the first chapter"}
        return self.reader_open(siblings[index - 1])

    # -------------------------------------------------------------- position

    def reader_save_position(self, path: str, index: int = 0, fraction: float = 0.0,
                             total: int = 0, mode: str = "", title: str = ""):
        record = save_position(path, index, fraction, total, mode, title)
        return {"ok": True, "position": record}

    def reader_get_position(self, path: str):
        return {"ok": True, "position": get_position(path)}

    def reader_clear_position(self, path: str = None):
        return {"ok": True, "cleared": clear_positions(path)}

    # ----------------------------------------------------------- annotations

    def reader_annotations(self, path: str):
        return {"ok": True, "annotations": load_annotations(path)}

    def reader_add_bookmark(self, path: str, index: int = 0, fraction: float = 0.0,
                            label: str = ""):
        record = save_annotation(path, "bookmark", {
            "index": int(index or 0),
            "fraction": float(fraction or 0.0),
            "label": label or f"Page {int(index or 0) + 1}",
        })
        return {"ok": True, "bookmark": record}

    def reader_add_note(self, path: str, index: int = 0, text: str = "",
                        fraction: float = 0.0):
        record = save_annotation(path, "note", {
            "index": int(index or 0),
            "fraction": float(fraction or 0.0),
            "text": text or "",
        })
        return {"ok": True, "note": record}

    def reader_delete_annotation(self, path: str, kind: str, ident: str):
        return {"ok": True, "deleted": delete_annotation(path, kind, ident)}

    # -------------------------------------------------------------- chapters

    def reader_chapters(self, url: str = "", directory: str = ""):
        """Chapter folders for a library entry, for the in-reader chapter list."""
        if url:
            entry = library.get_entry(url) or {}
            directory = directory or entry.get("directory") or ""
        if not directory or not os.path.isdir(directory):
            return {"ok": True, "chapters": []}
        positions = load_positions()
        out = []
        for folder in books.chapter_folders(directory):
            info = books.describe(folder)
            info["label"] = os.path.basename(folder)
            pos = positions.get(_key(folder))
            if pos:
                info["position"] = pos
            out.append(info)
        return {"ok": True, "chapters": out}


def _q(value: str) -> str:
    from urllib.parse import quote
    return quote(value, safe="")
