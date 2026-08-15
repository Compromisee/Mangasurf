"""Persistent library and bookmarks stored as JSON in the user folder.

~/.readerm/library.json    - every downloaded chapter, per manga
~/.readerm/bookmarks.json  - bookmarked manga

The download engine records chapters here so any UI (GUI / TUI / CLI)
can highlight what has already been downloaded.
"""


if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm"

import json
import os
import re
import threading
import time

from .paths import ensure as _ensure_data_dir

#: Created on first use, and populated from a MangaDL install if one
#: exists -- see readerm.paths.migrate.
DIR = _ensure_data_dir()
LIBRARY_PATH = os.path.join(DIR, "library.json")
BOOKMARKS_PATH = os.path.join(DIR, "bookmarks.json")

_lock = threading.RLock()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _key(url: str) -> str:
    """Canonical library key for a manga URL.

    Previously this only stripped a trailing slash, so the same manga reached
    under a slightly different URL got its own entry and looked as though
    nothing had been downloaded. Measured: of seven realistic variants of one
    URL, five missed -- ``http://`` vs ``https://``, a ``www.`` prefix, a
    ``?query``, a ``#fragment`` and a different case.

    Scheme, ``www.`` and host case are normalised away, and the query and
    fragment are dropped. The path keeps its case because many sites use
    case-sensitive slugs.
    """
    url = (url or "").strip()
    if not url:
        return ""

    # strip fragment then query -- neither identifies the series
    url = url.split("#", 1)[0].split("?", 1)[0]

    match = re.match(r"^(?:https?://)?(?:www\.)?([^/]+)(/.*)?$", url, re.I)
    if not match:
        return url.rstrip("/")
    host, path = match.groups()
    return (host.lower() + (path or "")).rstrip("/")


def _chapter_key(name) -> str:
    """Identity for a chapter, tolerant of volatile labels.

    Chapter names are not stable: several sources append the release date to
    the label ("Chapter 02 21/02/2026"), so when a site edits that date the
    recorded name stops matching the listed one and a downloaded chapter
    silently shows as missing -- while still being counted in the total, so
    the pill and the highlighted rows disagreed.

    The chapter *number* is the stable part, so it is used when one can be
    parsed. Falls back to the normalised full name otherwise.
    """
    from .utils import chapter_number, format_chapter_number

    text = str(name or "").strip()
    if not text:
        return ""
    number = chapter_number(text)
    if number is not None and number >= 0:
        return "#" + format_chapter_number(number)
    return re.sub(r"\s+", " ", text).lower()


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save(path, data):
    os.makedirs(DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ------------------------------------------------------------------ library


def load_library() -> dict:
    with _lock:
        return _load(LIBRARY_PATH, {})


def get_entry(url):
    """One library entry, tolerating URL variants and legacy keys.

    Callers must not index ``load_library()`` with a raw URL: keys are
    normalised (scheme, ``www.``, query and fragment removed), so a raw URL
    can miss an entry that is definitely there.
    """
    with _lock:
        return _find_entry(_load(LIBRARY_PATH, {}), url)


def _find_entry(lib, url):
    """Look up a manga, tolerating keys written by older versions.

    Entries saved before the key was normalised still carry the raw URL, so a
    direct hit is tried first and a normalised comparison second. Without this
    every pre-existing library entry would look empty after the upgrade.
    """
    key = _key(url)
    entry = lib.get(key)
    if entry is not None:
        return entry
    raw = (url or "").strip().rstrip("/")
    entry = lib.get(raw)
    if entry is not None:
        return entry
    for existing, value in lib.items():
        if _key(existing) == key:
            return value
    return None


def record_chapter(url, title, chapter_name, pages=0, cover=None, directory=None,
                   source=None):
    """Remember that a chapter of a manga has been downloaded."""
    with _lock:
        lib = _load(LIBRARY_PATH, {})
        key = _key(url)
        existing = _find_entry(lib, url)
        if existing is not None:
            lib[key] = existing          # migrate to the canonical key
            for old_key in [k for k in list(lib) if k != key and _key(k) == key]:
                del lib[old_key]
        # The dict key is the normalised form, but the entry keeps the URL as
        # given: it is what the UI links to and what relocation reports, and
        # a normalised key has no scheme, so it would not open in a browser.
        entry = lib.setdefault(key, {
            "title": title, "url": (url or "").strip() or key,
            "cover": cover, "source": source,
            "directory": directory, "chapters": {}, "added": _now(),
        })
        if not entry.get("url"):
            entry["url"] = (url or "").strip() or key
        entry["title"] = title or entry.get("title")
        if cover:
            entry["cover"] = cover
        if source:
            entry["source"] = source
        if directory:
            entry["directory"] = directory
        entry["chapters"][chapter_name] = {"pages": pages, "date": _now()}
        entry["last_download"] = _now()
        _save(LIBRARY_PATH, lib)


def record_outputs(url, outputs):
    """Remember the packaged files produced for a manga."""
    with _lock:
        lib = _load(LIBRARY_PATH, {})
        entry = lib.get(_key(url))
        if entry is not None:
            existing = entry.setdefault("outputs", [])
            for out in outputs:
                if out not in existing:
                    existing.append(out)
            _save(LIBRARY_PATH, lib)


def downloaded_chapters(url) -> set:
    """Chapter names already downloaded for this manga."""
    with _lock:
        entry = _find_entry(_load(LIBRARY_PATH, {}), url)
        return set(entry["chapters"].keys()) if entry else set()


def downloaded_keys(url) -> set:
    """Stable identities of the downloaded chapters.

    Use this rather than :func:`downloaded_chapters` when matching against a
    freshly scraped chapter list: the recorded label may embed a release date
    the site has since edited.
    """
    with _lock:
        entry = _find_entry(_load(LIBRARY_PATH, {}), url)
        if not entry:
            return set()
        return {_chapter_key(name) for name in entry["chapters"]}


def match_downloaded(url, chapters) -> list:
    """Names from ``chapters`` that have already been downloaded.

    Matching is done on the chapter number so a changed date suffix does not
    make a downloaded chapter look missing. This is what the manga page uses,
    so the "N downloaded" pill and the highlighted rows always agree.
    """
    keys = downloaded_keys(url)
    if not keys:
        return []
    names = []
    for chapter in chapters or []:
        name = chapter.get("name") if isinstance(chapter, dict) else chapter
        if name and _chapter_key(name) in keys:
            names.append(name)
    return names


def remove_entry(url) -> bool:
    with _lock:
        lib = _load(LIBRARY_PATH, {})
        if _key(url) in lib:
            del lib[_key(url)]
            _save(LIBRARY_PATH, lib)
            return True
        return False


def clear_library():
    with _lock:
        _save(LIBRARY_PATH, {})


# ---------------------------------------------------------------- bookmarks


def load_bookmarks() -> list:
    with _lock:
        return _load(BOOKMARKS_PATH, [])


def is_bookmarked(url) -> bool:
    key = _key(url)
    return any(_key(b.get("url")) == key for b in load_bookmarks())


def toggle_bookmark(info: dict) -> bool:
    """Add or remove a bookmark. Returns True if now bookmarked."""
    with _lock:
        marks = _load(BOOKMARKS_PATH, [])
        key = _key(info.get("url"))
        kept = [b for b in marks if _key(b.get("url")) != key]
        if len(kept) == len(marks):
            kept.append({
                # Store the URL as given, not the normalised key: the key has
                # no scheme, so clicking the bookmark produced a dead link.
                "url": (info.get("url") or "").strip() or key,
                "key": key,
                "title": info.get("title", "Unknown"),
                "cover": info.get("cover"),
                "cover_mirrors": info.get("cover_mirrors") or [],
                "status": info.get("status"),
                "source": info.get("source"),
                "source_name": info.get("source_name"),
                "added": _now(),
            })
            _save(BOOKMARKS_PATH, kept)
            return True
        _save(BOOKMARKS_PATH, kept)
        return False


def clear_bookmarks():
    with _lock:
        _save(BOOKMARKS_PATH, [])


# ------------------------------------------------------- bookmark folders
#
# Folders are stored separately from the bookmarks themselves, and a bookmark
# points at one by id. Keeping the two apart means renaming or deleting a
# folder never has to rewrite every bookmark, and a bookmark whose folder has
# gone simply falls back to the unfiled root instead of disappearing.

FOLDERS_PATH = os.path.join(DIR, "bookmark_folders.json")


def _folder_id(name) -> str:
    """Stable id derived from the name, with a numeric suffix on collision."""
    base = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    return base or "folder"


def load_folders() -> list:
    with _lock:
        return _load(FOLDERS_PATH, [])


def create_folder(name, colour=None, locked=False, blurred=False) -> dict:
    """Create a bookmark folder. Returns the stored record."""
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "Folder needs a name"}

    with _lock:
        folders = _load(FOLDERS_PATH, [])
        if any(f["name"].lower() == name.lower() for f in folders):
            return {"ok": False, "error": "A folder with that name exists"}

        base = _folder_id(name)
        taken = {f["id"] for f in folders}
        folder_id, n = base, 2
        while folder_id in taken:
            folder_id, n = f"{base}-{n}", n + 1

        record = {
            "id": folder_id,
            "name": name,
            "colour": colour or "",
            "locked": bool(locked),
            "blurred": bool(blurred),
            "created": _now(),
        }
        folders.append(record)
        _save(FOLDERS_PATH, folders)
        return {"ok": True, "folder": record}


def update_folder(folder_id, **changes) -> dict:
    allowed = {"name", "colour", "locked", "blurred"}
    with _lock:
        folders = _load(FOLDERS_PATH, [])
        for folder in folders:
            if folder["id"] != folder_id:
                continue
            for key, value in changes.items():
                if key not in allowed:
                    continue
                if key in ("locked", "blurred"):
                    folder[key] = bool(value)
                elif key == "name":
                    text = str(value or "").strip()
                    if text:
                        folder["name"] = text
                else:
                    folder[key] = value
            _save(FOLDERS_PATH, folders)
            return {"ok": True, "folder": folder}
        return {"ok": False, "error": "No such folder"}


def delete_folder(folder_id, delete_bookmarks=False) -> dict:
    """Remove a folder. Its bookmarks move back to the root by default."""
    with _lock:
        folders = [f for f in _load(FOLDERS_PATH, []) if f["id"] != folder_id]
        _save(FOLDERS_PATH, folders)

        marks = _load(BOOKMARKS_PATH, [])
        if delete_bookmarks:
            marks = [b for b in marks if b.get("folder") != folder_id]
        else:
            for mark in marks:
                if mark.get("folder") == folder_id:
                    mark["folder"] = ""
        _save(BOOKMARKS_PATH, marks)
        return {"ok": True}


def set_bookmark_folder(url, folder_id) -> dict:
    """Move one bookmark into a folder ("" = the unfiled root)."""
    key = _key(url)
    with _lock:
        marks = _load(BOOKMARKS_PATH, [])
        for mark in marks:
            if _key(mark.get("url")) == key or mark.get("key") == key:
                mark["folder"] = folder_id or ""
                _save(BOOKMARKS_PATH, marks)
                return {"ok": True}
        return {"ok": False, "error": "Not bookmarked"}


def folders_with_contents() -> dict:
    """Folders plus their bookmarks, and everything still unfiled.

    A folder's cover is the first bookmark added to it, so a folder is
    recognisable without asking the user to pick artwork.
    """
    with _lock:
        folders = _load(FOLDERS_PATH, [])
        marks = _load(BOOKMARKS_PATH, [])

    known = {f["id"] for f in folders}
    grouped, unfiled = {f["id"]: [] for f in folders}, []
    for mark in marks:
        folder_id = mark.get("folder") or ""
        # A bookmark pointing at a deleted folder falls back to the root
        # rather than vanishing from the UI entirely.
        if folder_id and folder_id in known:
            grouped[folder_id].append(mark)
        else:
            unfiled.append(mark)

    rows = []
    for folder in folders:
        items = grouped.get(folder["id"], [])
        rows.append({
            **folder,
            "count": len(items),
            "cover": items[0].get("cover") if items else None,
            "cover_mirrors": (items[0].get("cover_mirrors") or []) if items else [],
            "cover_source": items[0].get("source") if items else None,
            "items": items,
        })
    return {"folders": rows, "unfiled": unfiled}


# ------------------------------------------------------- relocation

def _relocate_paths(entry, old_dir, new_dir):
    """Rewrite an entry's directory and output paths onto a new folder."""
    entry["directory"] = new_dir
    outputs = entry.get("outputs") or []
    moved = []
    for path in outputs:
        name = os.path.basename(path)
        candidate = os.path.join(new_dir, name)
        # only adopt the new location if the file is actually there
        moved.append(candidate if os.path.isfile(candidate) else path)
    if outputs:
        entry["outputs"] = moved
    entry["relocated"] = _now()
    return entry


def relocate_entry(url, new_dir) -> dict:
    """Point one library entry at a folder the user moved it to."""
    new_dir = os.path.abspath(os.path.expanduser(new_dir or ""))
    if not os.path.isdir(new_dir):
        return {"ok": False, "error": f"Not a folder: {new_dir}"}
    with _lock:
        lib = _load(LIBRARY_PATH, {})
        entry = lib.get(_key(url))
        if entry is None:
            return {"ok": False, "error": "Not in library"}
        old = entry.get("directory")
        _relocate_paths(entry, old, new_dir)
        _save(LIBRARY_PATH, lib)
        return {"ok": True, "old": old, "new": new_dir,
                "title": entry.get("title")}


def find_moved_entries(search_roots=None) -> list:
    """Look for library folders that were moved, by matching folder name.

    Returns proposals only -- nothing is written until :func:`relocate_entry`
    or :func:`apply_relocations` is called, so a wrong guess cannot silently
    rewrite the library.
    """
    roots = [os.path.abspath(os.path.expanduser(r))
             for r in (search_roots or []) if r]
    roots = [r for r in roots if os.path.isdir(r)]
    if not roots:
        return []

    # index candidate folders by name, one level deep (and the root itself)
    index = {}
    for root in roots:
        try:
            for name in os.listdir(root):
                path = os.path.join(root, name)
                if os.path.isdir(path):
                    index.setdefault(name, []).append(path)
        except OSError:
            continue

    proposals = []
    for entry in _load(LIBRARY_PATH, {}).values():
        directory = entry.get("directory")
        if not directory or os.path.isdir(directory):
            continue                      # still where we left it
        name = os.path.basename(directory.rstrip(os.sep))
        for candidate in index.get(name, []):
            if os.path.isdir(candidate):
                proposals.append({
                    "url": entry.get("url"),
                    "title": entry.get("title"),
                    "old": directory,
                    "new": candidate,
                })
                break
    return proposals


def apply_relocations(proposals) -> dict:
    """Apply a list of ``{url, new}`` relocation proposals."""
    applied, failed = [], []
    for item in proposals or []:
        result = relocate_entry(item.get("url"), item.get("new"))
        (applied if result.get("ok") else failed).append(result)
    return {"ok": True, "applied": len(applied), "failed": failed,
            "details": applied}


def verify_entries() -> dict:
    """Report which library entries still resolve on disk."""
    present, missing = [], []
    for entry in _load(LIBRARY_PATH, {}).values():
        directory = entry.get("directory")
        outputs = entry.get("outputs") or []
        gone = [o for o in outputs if not os.path.isfile(o)]
        row = {
            "url": entry.get("url"),
            "title": entry.get("title"),
            "directory": directory,
            "directory_ok": bool(directory and os.path.isdir(directory)),
            "missing_outputs": gone,
        }
        (missing if (not row["directory_ok"] or gone) else present).append(row)
    return {"ok": True, "present": present, "missing": missing}
