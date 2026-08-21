"""A read-only description of this Mangasurf install, for other programs.

The point of this module is that another application -- a different reader, a
sync script, a shell one-liner, an AI agent -- should be able to find out
where everything is and what has been read *without* importing Mangasurf,
parsing its private JSON, or guessing at paths that differ per platform.

Design rules, each chosen deliberately:

*   **Read only.** Nothing here writes, deletes, downloads or starts a job.
    A caller cannot damage a library through this surface, so it can be
    exposed with far less worry than the full RPC bridge.

*   **Absolute paths, always.** A consumer runs in its own working
    directory. Relative paths would be worse than useless.

*   **Stable field names, versioned.** ``api_version`` is bumped when a field
    changes meaning. New fields may appear at any time, so a consumer must
    ignore ones it does not recognise.

*   **Locked shelves are respected.** A locked shelf's books do not appear.
    A privacy screen that any local script can walk around is not one.

*   **No secrets.** No lock salts, no hashes, no access tokens. ``paths()``
    names the files, which is enough to find them; reading them is the
    caller's business and the OS's decision.

The whole surface is documented for agents in MD/AGENT.md.
"""

if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm"

import json
import os
import platform
import time

from . import library, shelves, tracking
from .paths import ensure as _ensure_data_dir

#: Bumped when an existing field changes meaning. Additions do not bump it.
API_VERSION = 1

DIR = _ensure_data_dir()


def _stat(path):
    try:
        info = os.stat(path)
    except OSError:
        return {"exists": False, "bytes": 0, "modified": None}
    return {
        "exists": True,
        "bytes": info.st_size,
        "modified": time.strftime("%Y-%m-%dT%H:%M:%S",
                                  time.localtime(info.st_mtime)),
    }


def paths() -> dict:
    """Where everything lives on this machine.

    Every value is absolute. ``files`` carries a stat for each, so a consumer
    can tell "not created yet" from "empty" without opening anything.
    """
    files = {
        "library": os.path.join(DIR, "library.json"),
        "bookmarks": os.path.join(DIR, "bookmarks.json"),
        "bookmark_folders": os.path.join(DIR, "bookmark_folders.json"),
        "shelves": os.path.join(DIR, "shelves.json"),
        "reading": os.path.join(DIR, "reading.json"),
        "annotations": os.path.join(DIR, "annotations.json"),
        "tracking": os.path.join(DIR, "tracking.json"),
        "settings": os.path.join(DIR, "config.json"),
        "lock": os.path.join(DIR, "lock.json"),
    }
    return {
        "data_dir": DIR,
        "files": {name: {"path": path, **_stat(path)}
                  for name, path in files.items()},
        "download_dir": _download_dir(),
    }


def _download_dir() -> str:
    try:
        from .config import load_config
        cfg = load_config() or {}
        for key in ("output_dir", "download_dir", "output"):
            if cfg.get(key):
                return os.path.abspath(str(cfg[key]))
    except Exception:
        pass
    return ""


def _unlocked() -> set:
    """Shelves the user has opened in this process.

    Held on ``ReaderApi`` because that is where the desktop app and the RPC
    bridge both put it. Reading it here means "unlock a shelf in the app, and
    a local script can see it too" -- which is the behaviour a user expects
    from one running program. It is still in memory only, so it dies with the
    process.

    Imported lazily: localapi must stay usable in a bare
    ``python -c "from readerm import localapi"`` without dragging in the
    reader stack.
    """
    try:
        from .reader.api import ReaderApi
        return set(ReaderApi._unlocked_shelves)
    except Exception:
        return set()


def _hidden_keys() -> set:
    """Books on a locked shelf that has not been opened this session.

    ``shelves.locked_ids`` already includes descendants of a locked shelf.
    """
    locked = shelves.locked_ids() - _unlocked()
    if not locked:
        return set()
    keys = set()
    for shelf in shelves._load():
        if shelf.get("id") in locked:
            keys.update(shelf.get("books") or [])
    return keys


def books(include_chapters: bool = False) -> list:
    """Every series in the library, as absolute paths and counts.

    ``include_chapters`` adds the per-chapter list, which is large -- a
    900-chapter series is a lot of JSON to hand someone who only wanted to
    know where the folder is.
    """
    hidden = _hidden_keys()
    out = []
    for entry in library.load_library().values():
        key = library._key(entry.get("url") or "") or entry.get("directory") or ""
        if key in hidden:
            continue
        chapters = entry.get("chapters") or {}
        outputs = [os.path.abspath(p) for p in (entry.get("outputs") or []) if p]
        row = {
            "key": key,
            "title": entry.get("title") or "Untitled",
            "url": entry.get("url") or "",
            "source": entry.get("source") or "",
            "directory": os.path.abspath(entry["directory"])
                         if entry.get("directory") else "",
            "cover": os.path.abspath(entry["cover"])
                     if entry.get("cover") and os.path.isabs(str(entry["cover"]))
                     else (entry.get("cover") or ""),
            "chapter_count": len(chapters),
            "outputs": outputs,
            "added": entry.get("added") or "",
            "last_download": entry.get("last_download") or "",
            "shelf": shelves.shelf_of(key),
        }
        if include_chapters:
            row["chapters"] = [
                {"name": name, **({"pages": data.get("pages")}
                                  if isinstance(data, dict) else {})}
                for name, data in chapters.items()
            ]
        out.append(row)
    out.sort(key=lambda b: (b.get("last_download") or b.get("added") or ""),
             reverse=True)
    return out


def reading() -> list:
    """Reading positions: which page, how far, and when.

    Positions live per *file*, so a series with 90 chapters has up to 90
    entries. Entries for files that no longer exist are dropped rather than
    reported, because a consumer cannot do anything with them.
    """
    from .reader.api import load_positions

    hidden_dirs = _hidden_dirs()
    out = []
    for record in load_positions().values():
        path = record.get("path") or ""
        if not path or not os.path.exists(path):
            continue
        if _under(path, hidden_dirs):
            continue
        total = int(record.get("total") or 0)
        index = int(record.get("index") or 0)
        out.append({
            "path": os.path.abspath(path),
            "page": index + 1,
            "pages": total,
            "fraction": round(float(record.get("fraction") or 0.0), 4),
            "percent": round(float(record.get("fraction") or 0.0) * 100),
            "finished": bool(total and index >= total - 1),
            "mode": record.get("mode") or "",
            "title": record.get("title") or "",
            "at": record.get("at") or "",
        })
    out.sort(key=lambda r: r.get("at") or "", reverse=True)
    return out


def _hidden_dirs() -> list:
    keys = _hidden_keys()
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


def _under(path, roots) -> bool:
    if not roots:
        return False
    target = os.path.abspath(path)
    for root in roots:
        if target == root:
            return True
        try:
            if os.path.commonpath([target, root]) == root:
                return True
        except ValueError:
            continue
    return False


def covers() -> list:
    """Every cover this install knows about, as an absolute path.

    Handy for a launcher or a grid view that wants artwork without
    re-downloading any.
    """
    out = []
    for book in books():
        cover = book.get("cover") or ""
        if cover and os.path.isfile(cover):
            out.append({"key": book["key"], "title": book["title"],
                        "cover": cover})
            continue
        # Fall back to a cover sitting in the series folder.
        directory = book.get("directory")
        if not directory or not os.path.isdir(directory):
            continue
        from .covers import COVER_NAMES
        for name in COVER_NAMES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                out.append({"key": book["key"], "title": book["title"],
                            "cover": candidate})
                break
    return out


def sources() -> list:
    """The download sources this build ships.

    Reads the SOURCES registry directly. An earlier version called a
    non-existent ``all_sources()`` inside a bare ``except``, so it silently
    returned [] and looked like a build with no sources at all -- the reason
    this function no longer swallows exceptions.
    """
    from .sources import SOURCES

    out = []
    for source_id, cls in sorted(SOURCES.items()):
        out.append({
            "id": source_id,
            "name": getattr(cls, "name", source_id),
            "base_url": getattr(cls, "base_url", ""),
            "adult_only": bool(getattr(cls, "adult_only", False)),
            "needs_flaresolverr": bool(getattr(cls, "needs_flaresolverr", False)),
            "supports_language": bool(getattr(cls, "supports_language", False)),
        })
    return out


def shelf_tree() -> list:
    """Shelves as a nested tree. Locked shelves report no contents.

    Passes the *unfiltered* book list on purpose: shelves.tree does the
    hiding itself and needs the locked books present to report an honest
    "12 hidden" count. It still never returns their titles.
    """
    every = books()
    hidden = _hidden_keys()
    if hidden:
        # books() already dropped them, so put them back for counting only.
        for entry in library.load_library().values():
            key = library._key(entry.get("url") or "") or entry.get("directory") or ""
            if key in hidden:
                every.append({"key": key, "title": entry.get("title") or ""})
    return shelves.tree(every, unlocked=_unlocked())["shelves"]


def stats() -> dict:
    """Totals, for a dashboard that does not want to walk everything."""
    every = books()
    positions = reading()
    return {
        "series": len(every),
        "chapters": sum(b["chapter_count"] for b in every),
        "packaged_files": sum(len(b["outputs"]) for b in every),
        "in_progress": sum(1 for r in positions
                           if 0.01 < r["fraction"] < 0.99),
        "finished": sum(1 for r in positions if r["finished"]),
        "shelves": len(shelves.load_shelves()),
        "locked_shelves": len(shelves.locked_ids()),
    }


def info() -> dict:
    """One call that describes the whole install.

    Deliberately the first thing MD/AGENT.md tells a caller to fetch: it
    names every other endpoint, so a consumer discovers the API from the API
    rather than from a document that can go stale.
    """
    from . import __version__

    return {
        "ok": True,
        "app": "Mangasurf",
        "version": __version__,
        "api_version": API_VERSION,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "paths": paths(),
        "stats": stats(),
        "endpoints": {
            "info": "GET /local/info",
            "paths": "GET /local/paths",
            "books": "GET /local/books?chapters=1",
            "reading": "GET /local/reading",
            "covers": "GET /local/covers",
            "sources": "GET /local/sources",
            "shelves": "GET /local/shelves",
            "stats": "GET /local/stats",
            "page": "GET /stream/page?path=<absolute>",
            "book": "GET /stream/book?path=<absolute>",
        },
        "notes": [
            "Everything under /local is read-only.",
            "Books on a locked shelf are omitted from every endpoint.",
            "All paths are absolute.",
            "Unknown fields may be added; ignore what you do not recognise.",
        ],
    }


#: Endpoint name -> callable. The Flask layer and the CLI both drive this, so
#: there is exactly one definition of what the API offers.
ENDPOINTS = {
    "info": info,
    "paths": paths,
    "books": books,
    "reading": reading,
    "covers": covers,
    "sources": sources,
    "shelves": shelf_tree,
    "stats": stats,
}


def dump(name: str = "info", **kwargs) -> str:
    """JSON for one endpoint. Used by ``readerm api <name>``."""
    handler = ENDPOINTS.get(name)
    if handler is None:
        return json.dumps({"ok": False, "error": f"No endpoint {name!r}",
                           "endpoints": sorted(ENDPOINTS)}, indent=2)
    return json.dumps(handler(**kwargs), indent=2, default=str)
