"""Library shelves: folders for books, with tags and pins.

Stored at ``~/.mangasurf/shelves.json``. This is deliberately a *separate* file
from ``bookmark_folders.json``: those group bookmarked **series URLs** you have
not necessarily downloaded, while a shelf groups **books on disk** that the
reader can open. Merging the two would mean one record trying to describe both
a remote series and a local file, and either half would end up mostly empty.

Design notes, each of which is a decision that could reasonably have gone the
other way:

*   **A shelf stores book keys, not paths.** A library entry moves when the
    user relocates a download (``library.relocate_entry``), so a shelf keyed on
    the absolute path would empty itself the moment the files moved. The key is
    ``library._key(url)`` for a downloaded series and the absolute path only as
    a fallback for loose files that have no URL at all.

*   **Nesting is by parent id, not by containment.** ``parent`` on the child
    means renaming or moving a shelf is one write, and a cycle can only ever be
    introduced by ``set_parent``, which checks for it in one place.
"""

if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "mangasurf"

import json
import os
import re
import threading
import time

from .paths import ensure as _ensure_data_dir

DIR = _ensure_data_dir()
SHELVES_PATH = os.path.join(DIR, "shelves.json")

_lock = threading.RLock()

#: A shelf tree deeper than this is almost certainly an accident, and it keeps
#: the recursive walks below bounded no matter what is in the file.
MAX_DEPTH = 12

DEFAULT_COLOUR = ""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _slug(name) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return base or "shelf"


def _load() -> list:
    try:
        with open(SHELVES_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save(shelves: list) -> list:
    os.makedirs(DIR, exist_ok=True)
    tmp = SHELVES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(shelves, handle, indent=2)
    os.replace(tmp, SHELVES_PATH)
    try:                        # the file carries lock verifiers
        os.chmod(SHELVES_PATH, 0o600)
    except OSError:
        pass
    return shelves


def _public(shelf: dict) -> dict:
    """A shelf as the UI may see it, minus any private bookkeeping keys."""
    return {key: value for key, value in shelf.items()
            if key not in ("salt", "hash", "iterations", "pin_to_open")}


def _find(shelves, shelf_id):
    for shelf in shelves:
        if shelf.get("id") == shelf_id:
            return shelf
    return None


# ------------------------------------------------------------------ reading


def load_shelves() -> list:
    """Every shelf, without lock material."""
    with _lock:
        return [_public(s) for s in _load()]


def get(shelf_id) -> dict:
    with _lock:
        shelf = _find(_load(), shelf_id)
        return _public(shelf) if shelf else {}


def _depth(shelves, shelf_id) -> int:
    depth, seen = 0, set()
    current = _find(shelves, shelf_id)
    while current and current.get("parent") and depth < MAX_DEPTH:
        if current["id"] in seen:
            break
        seen.add(current["id"])
        current = _find(shelves, current["parent"])
        depth += 1
    return depth


def _descendants(shelves, shelf_id) -> set:
    """Every shelf below this one. Iterative, so a corrupt cycle in the file
    cannot recurse forever."""
    out, queue = set(), [shelf_id]
    while queue:
        current = queue.pop()
        for shelf in shelves:
            if shelf.get("parent") == current and shelf["id"] not in out:
                out.add(shelf["id"])
                queue.append(shelf["id"])
    return out


# ------------------------------------------------------------------ writing


def create(name, parent="", colour=None, tags=None, pinned=False) -> dict:
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "Shelf needs a name"}

    with _lock:
        shelves = _load()
        if parent and not _find(shelves, parent):
            return {"ok": False, "error": "No such parent shelf"}
        if parent and _depth(shelves, parent) + 1 >= MAX_DEPTH:
            return {"ok": False, "error": f"Shelves nest at most {MAX_DEPTH} deep"}

        siblings = [s for s in shelves if (s.get("parent") or "") == (parent or "")]
        if any(s["name"].lower() == name.lower() for s in siblings):
            return {"ok": False, "error": "A shelf with that name is already here"}

        base, taken = _slug(name), {s["id"] for s in shelves}
        shelf_id, n = base, 2
        while shelf_id in taken:
            shelf_id, n = f"{base}-{n}", n + 1

        record = {
            "id": shelf_id,
            "name": name,
            "parent": parent or "",
            "colour": colour or DEFAULT_COLOUR,
            "tags": _clean_tags(tags),
            "pinned": bool(pinned),
            "books": [],
            "created": _now(),
        }
        shelves.append(record)
        _save(shelves)
        return {"ok": True, "shelf": _public(record)}


def _clean_tags(tags) -> list:
    """Trimmed, de-duplicated, case-insensitively unique, order preserved."""
    if isinstance(tags, str):
        tags = [part for part in re.split(r"[,\n]", tags)]
    out, seen = [], set()
    for tag in tags or []:
        text = str(tag or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out


def rename(shelf_id, name) -> dict:
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "Shelf needs a name"}
    with _lock:
        shelves = _load()
        shelf = _find(shelves, shelf_id)
        if not shelf:
            return {"ok": False, "error": "No such shelf"}
        for other in shelves:
            if (other is not shelf
                    and (other.get("parent") or "") == (shelf.get("parent") or "")
                    and other["name"].lower() == name.lower()):
                return {"ok": False, "error": "A shelf with that name is already here"}
        shelf["name"] = name
        _save(shelves)
        return {"ok": True, "shelf": _public(shelf)}


def update(shelf_id, **changes) -> dict:
    """Change presentation (colour, tags, pinned, expanded)."""
    allowed = {"colour", "tags", "pinned", "expanded"}
    with _lock:
        shelves = _load()
        shelf = _find(shelves, shelf_id)
        if not shelf:
            return {"ok": False, "error": "No such shelf"}
        for key, value in changes.items():
            if key not in allowed:
                continue
            if key == "tags":
                shelf["tags"] = _clean_tags(value)
            elif key in ("pinned", "expanded"):
                shelf[key] = bool(value)
            else:
                shelf[key] = value
        _save(shelves)
        return {"ok": True, "shelf": _public(shelf)}


def set_parent(shelf_id, parent="") -> dict:
    """Move a shelf. Refuses to make a shelf its own ancestor."""
    with _lock:
        shelves = _load()
        shelf = _find(shelves, shelf_id)
        if not shelf:
            return {"ok": False, "error": "No such shelf"}
        parent = parent or ""
        if parent:
            if parent == shelf_id:
                return {"ok": False, "error": "A shelf cannot contain itself"}
            if not _find(shelves, parent):
                return {"ok": False, "error": "No such parent shelf"}
            # Dropping a shelf onto its own child would detach the whole
            # subtree from the root and make it unreachable in the tree view.
            if parent in _descendants(shelves, shelf_id):
                return {"ok": False, "error": "A shelf cannot move into itself"}
        shelf["parent"] = parent
        _save(shelves)
        return {"ok": True, "shelf": _public(shelf)}


def delete(shelf_id, recursive=False) -> dict:
    """Remove a shelf. Children are promoted to its parent unless *recursive*.

    Books are never deleted -- a shelf is a view onto the library, so removing
    one must not remove anything from disk.
    """
    with _lock:
        shelves = _load()
        shelf = _find(shelves, shelf_id)
        if not shelf:
            return {"ok": False, "error": "No such shelf"}
        doomed = {shelf_id}
        if recursive:
            doomed |= _descendants(shelves, shelf_id)
        else:
            for child in shelves:
                if child.get("parent") == shelf_id:
                    child["parent"] = shelf.get("parent") or ""
        remaining = [s for s in shelves if s["id"] not in doomed]
        _save(remaining)
        return {"ok": True, "removed": sorted(doomed)}


# -------------------------------------------------------------------- books


def add_book(shelf_id, key) -> dict:
    key = str(key or "").strip()
    if not key:
        return {"ok": False, "error": "No book given"}
    with _lock:
        shelves = _load()
        shelf = _find(shelves, shelf_id)
        if not shelf:
            return {"ok": False, "error": "No such shelf"}
        books = shelf.setdefault("books", [])
        if key not in books:
            books.append(key)
            _save(shelves)
        return {"ok": True, "shelf": _public(shelf)}


def remove_book(shelf_id, key) -> dict:
    with _lock:
        shelves = _load()
        shelf = _find(shelves, shelf_id)
        if not shelf:
            return {"ok": False, "error": "No such shelf"}
        books = shelf.setdefault("books", [])
        if key in books:
            books.remove(key)
            _save(shelves)
        return {"ok": True, "shelf": _public(shelf)}


def move_book(key, shelf_id) -> dict:
    """Put a book on exactly one shelf ("" = unfiled)."""
    with _lock:
        shelves = _load()
        if shelf_id and not _find(shelves, shelf_id):
            return {"ok": False, "error": "No such shelf"}
        for shelf in shelves:
            books = shelf.setdefault("books", [])
            if shelf["id"] == shelf_id:
                if key not in books:
                    books.append(key)
            elif key in books:
                books.remove(key)
        _save(shelves)
        return {"ok": True}


def shelf_of(key) -> str:
    with _lock:
        for shelf in _load():
            if key in (shelf.get("books") or []):
                return shelf["id"]
    return ""


# --------------------------------------------------------------------- tags


def all_tags() -> list:
    """Every tag in use, with how many shelves carry it."""
    counts = {}
    with _lock:
        for shelf in _load():
            for tag in shelf.get("tags") or []:
                counts[tag] = counts.get(tag, 0) + 1
    return [{"tag": tag, "count": count}
            for tag, count in sorted(counts.items(), key=lambda kv: kv[0].lower())]


def set_tags(shelf_id, tags) -> dict:
    return update(shelf_id, tags=tags)


# --------------------------------------------------------------------- tree


def tree(books=None, unlocked=()) -> dict:
    """The shelf tree for the sidebar.

    *books* is the reader's book list; each is placed on its shelf by key.
    *unlocked* is accepted for backward compatibility and ignored.

    Folders come back collapsed (``expanded: False``) unless the stored record
    says otherwise -- the user asked for "dont expand folders".
    """
    with _lock:
        shelves = _load()

    by_key = {}
    for book in books or []:
        key = book.get("key") or book.get("url") or book.get("directory") or ""
        if key:
            by_key.setdefault(key, []).append(book)

    filed = set()
    children_of = {}
    for shelf in shelves:
        children_of.setdefault(shelf.get("parent") or "", []).append(shelf)

    def build(parent, depth):
        rows = []
        if depth > MAX_DEPTH:
            return rows
        for shelf in sorted(children_of.get(parent, []),
                            key=lambda s: (not s.get("pinned"),
                                           s["name"].lower())):
            node = _public(shelf)
            node["depth"] = depth
            node["hidden"] = False
            # Collapsed by default: the user asked that folders not expand.
            node["expanded"] = bool(shelf.get("expanded"))
            mine = []
            for key in shelf.get("books") or []:
                filed.add(key)
                for book in by_key.get(key, []):
                    mine.append(book)
            node["books"] = mine
            node["book_count"] = len(mine)
            kids = build(shelf["id"], depth + 1)
            node["children"] = kids
            node["child_count"] = len(kids)
            rows.append(node)
        return rows

    roots = build("", 0)
    unfiled = [book for book in books or []
               if (book.get("key") or book.get("url")
                   or book.get("directory") or "") not in filed]
    return {"shelves": roots, "unfiled": unfiled, "tags": all_tags()}


def clear_all():
    """Testing/reset helper."""
    with _lock:
        _save([])
