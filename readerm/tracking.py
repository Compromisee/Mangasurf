"""Reading progress, update checking, notes, ratings and duplicate scanning.

Stored under ``~/.readerm/``:

    progress.json   per-series reading position and per-chapter read flags
    watchlist.json  series watched for new chapters, with the last seen count
    notes.json      free-text notes and star ratings per series

Everything is plain JSON so it can be inspected, backed up or edited by hand.
"""


if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm"

import json
import os
import threading
import time

from .paths import ensure as _ensure_data_dir

#: Created on first use, and populated from a MangaDL install if one
#: exists -- see readerm.paths.migrate.
DIR = _ensure_data_dir()

PROGRESS_PATH = os.path.join(DIR, "progress.json")
WATCHLIST_PATH = os.path.join(DIR, "watchlist.json")
NOTES_PATH = os.path.join(DIR, "notes.json")

_lock = threading.RLock()


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _key(url):
    return (url or "").strip().rstrip("/")


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


# ========================================================= reading progress


def mark_read(url, chapter_name, read=True):
    """Mark one chapter read or unread."""
    with _lock:
        data = _load(PROGRESS_PATH, {})
        entry = data.setdefault(_key(url), {"chapters": {}, "updated": _now()})
        if read:
            entry["chapters"][chapter_name] = {"read": True, "date": _now()}
            entry["last_read"] = chapter_name
        else:
            entry["chapters"].pop(chapter_name, None)
        entry["updated"] = _now()
        _save(PROGRESS_PATH, data)
        return entry


def mark_many(url, chapter_names, read=True):
    with _lock:
        data = _load(PROGRESS_PATH, {})
        entry = data.setdefault(_key(url), {"chapters": {}, "updated": _now()})
        for name in chapter_names:
            if read:
                entry["chapters"][name] = {"read": True, "date": _now()}
            else:
                entry["chapters"].pop(name, None)
        if read and chapter_names:
            entry["last_read"] = chapter_names[-1]
        entry["updated"] = _now()
        _save(PROGRESS_PATH, data)
        return entry


def read_chapters(url) -> set:
    entry = _load(PROGRESS_PATH, {}).get(_key(url), {})
    return set(entry.get("chapters", {}))


def progress_for(url, chapters) -> dict:
    """Reading progress for a series against its chapter list."""
    read = read_chapters(url)
    total = len(chapters or [])
    done = sum(1 for c in (chapters or []) if c.get("name") in read)
    entry = _load(PROGRESS_PATH, {}).get(_key(url), {})
    return {
        "read": done,
        "total": total,
        "percent": round(done / total * 100, 1) if total else 0.0,
        "last_read": entry.get("last_read"),
        "unread": total - done,
    }


def next_unread(url, chapters):
    """The first chapter not yet marked read."""
    read = read_chapters(url)
    for chapter in chapters or []:
        if chapter.get("name") not in read:
            return chapter
    return None


def clear_progress(url=None):
    with _lock:
        if url is None:
            _save(PROGRESS_PATH, {})
            return {}
        data = _load(PROGRESS_PATH, {})
        data.pop(_key(url), None)
        _save(PROGRESS_PATH, data)
        return data


# =============================================================== watchlist


def watch(url, title, chapter_count, source=None, cover=None):
    """Track a series so new chapters can be detected later."""
    with _lock:
        data = _load(WATCHLIST_PATH, {})
        data[_key(url)] = {
            "url": _key(url),
            "title": title,
            "source": source,
            "cover": cover,
            "known_chapters": int(chapter_count or 0),
            "added": data.get(_key(url), {}).get("added", _now()),
            "checked": _now(),
            "new_chapters": 0,
        }
        _save(WATCHLIST_PATH, data)
        return data[_key(url)]


def unwatch(url):
    with _lock:
        data = _load(WATCHLIST_PATH, {})
        removed = data.pop(_key(url), None) is not None
        _save(WATCHLIST_PATH, data)
        return removed


def is_watched(url) -> bool:
    return _key(url) in _load(WATCHLIST_PATH, {})


def get_watchlist() -> list:
    return list(_load(WATCHLIST_PATH, {}).values())


def record_check(url, chapter_count):
    """Update a watched series after a check, returning how many are new."""
    with _lock:
        data = _load(WATCHLIST_PATH, {})
        entry = data.get(_key(url))
        if not entry:
            return 0
        known = int(entry.get("known_chapters", 0))
        new = max(0, int(chapter_count) - known)
        entry["new_chapters"] = new
        entry["latest_count"] = int(chapter_count)
        entry["checked"] = _now()
        _save(WATCHLIST_PATH, data)
        return new


def acknowledge(url):
    """Mark the new chapters of a series as seen."""
    with _lock:
        data = _load(WATCHLIST_PATH, {})
        entry = data.get(_key(url))
        if entry:
            entry["known_chapters"] = int(
                entry.get("latest_count", entry.get("known_chapters", 0)))
            entry["new_chapters"] = 0
            _save(WATCHLIST_PATH, data)
        return entry


def check_updates(workers=4, progress=None) -> list:
    """Re-check every watched series for new chapters.

    Returns a list of ``{title, url, new, total}`` for series that grew.
    Network failures are skipped rather than raising.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from .sources import source_for_url

    entries = get_watchlist()
    if not entries:
        return []

    updates = []

    def check(entry):
        source = source_for_url(entry["url"])
        try:
            chapters = source.get_chapters(entry["url"])
            return entry, len(chapters)
        finally:
            source.close()

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(entries)))) as pool:
        futures = {pool.submit(check, e): e for e in entries}
        for done, future in enumerate(as_completed(futures), 1):
            entry = futures[future]
            if progress:
                try:
                    progress(done, len(entries), entry.get("title", ""))
                except Exception:
                    pass
            try:
                entry, count = future.result()
            except Exception:
                continue
            new = record_check(entry["url"], count)
            if new > 0:
                updates.append({
                    "title": entry.get("title"),
                    "url": entry["url"],
                    "source": entry.get("source"),
                    "cover": entry.get("cover"),
                    "new": new,
                    "total": count,
                })
    updates.sort(key=lambda u: -u["new"])
    return updates


# =========================================================== notes/ratings


def set_note(url, text="", rating=0, tags=None):
    with _lock:
        data = _load(NOTES_PATH, {})
        entry = data.setdefault(_key(url), {"created": _now()})
        entry["note"] = text or ""
        entry["rating"] = max(0, min(5, int(rating or 0)))
        if tags is not None:
            entry["tags"] = list(tags)
        entry["updated"] = _now()
        _save(NOTES_PATH, data)
        return entry


def get_note(url) -> dict:
    return _load(NOTES_PATH, {}).get(_key(url), {"note": "", "rating": 0,
                                                 "tags": []})


def all_notes() -> dict:
    return _load(NOTES_PATH, {})


def rated(minimum=1) -> list:
    """Series rated at least ``minimum`` stars, best first."""
    items = [{"url": url, **meta} for url, meta in all_notes().items()
             if int(meta.get("rating", 0) or 0) >= minimum]
    items.sort(key=lambda item: -int(item.get("rating", 0) or 0))
    return items


# ======================================================== disk maintenance


def scan_duplicates(root):
    """Find byte-identical files under a directory, grouped by content hash.

    Useful after downloading the same series from two sources.
    """
    import hashlib
    from collections import defaultdict

    by_size = defaultdict(list)
    for base, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            try:
                by_size[os.path.getsize(path)].append(path)
            except OSError:
                continue

    groups = []
    for size, paths in by_size.items():
        if len(paths) < 2 or size == 0:
            continue
        by_hash = defaultdict(list)
        for path in paths:
            try:
                digest = hashlib.sha256()
                with open(path, "rb") as f:
                    for block in iter(lambda: f.read(1 << 20), b""):
                        digest.update(block)
                by_hash[digest.hexdigest()].append(path)
            except OSError:
                continue
        for digest, matches in by_hash.items():
            if len(matches) > 1:
                groups.append({"hash": digest, "size": size, "files": matches,
                               "wasted": size * (len(matches) - 1)})
    groups.sort(key=lambda g: -g["wasted"])
    return groups


def find_orphans():
    """Library entries whose files are gone from disk."""
    from . import library

    orphans = []
    for entry in library.load_library().values():
        directory = entry.get("directory")
        outputs = entry.get("outputs", []) or []
        missing = [o for o in outputs if not os.path.isfile(o)]
        if (directory and not os.path.isdir(directory)) or (outputs and missing):
            orphans.append({
                "title": entry.get("title"),
                "url": entry.get("url"),
                "directory": directory,
                "missing": missing,
                "directory_gone": bool(directory and not os.path.isdir(directory)),
            })
    return orphans


def disk_usage(root):
    """Per-series disk usage under a downloads directory, largest first."""
    rows = []
    if not os.path.isdir(root):
        return rows
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        total, files = 0, 0
        for base, _dirs, filenames in os.walk(path):
            for filename in filenames:
                try:
                    total += os.path.getsize(os.path.join(base, filename))
                    files += 1
                except OSError:
                    continue
        rows.append({"name": name, "path": path, "bytes": total, "files": files})
    rows.sort(key=lambda r: -r["bytes"])
    return rows
