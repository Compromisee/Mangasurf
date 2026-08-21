"""pywebview GUI for Mangasurf.

A minimalist Material-style web UI served locally. The Python side exposes a
small JSON API to JavaScript; download progress is pushed back with
window.evaluate_js.
"""

import collections
import functools
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import traceback

from ..downloader import DownloadEngine, DownloadOptions
from ..sources import (AGGREGATE_PREFIXES, DEFAULT_SOURCE, SOURCES, browse_all, browse_multi,
                       detect_source, genres_all, get_source, list_sources,
                       resolve_member, search_all, split_genres,
                       source_for_url)
from .. import config as appconfig
from .. import features
from .. import library
from .. import logs as wclogs
from .. import passlock
from .. import tracking
from ..reader.api import READER_DEFAULTS, ReaderApi

logger = logging.getLogger(__name__)

#: Where settings actually live now. Kept as a name because other modules and
#: tests import it; it points at config.json, which holds both the app
#: settings and the per-source config.
SETTINGS_PATH = appconfig.CONFIG_PATH

#: Pre-1.4.11 location, read once and migrated. Never written again.
LEGACY_SETTINGS_PATH = appconfig.LEGACY_SETTINGS_PATH

DEFAULT_SETTINGS = {
    "output_dir": os.path.join(os.path.expanduser("~"), "Downloads", "Mangasurf"),
    "format": "cbz",
    "bundle": 0,
    "chapter_workers": 3,
    "image_workers": 6,
    "delay": 0.5,
    "retries": 5,
    "keep_images": False,
    "theme": "midnight",
    "corners": "rounded",       # "rounded" | "square"
    # A frameless window with the app's own titlebar, so the window controls
    # match the theme instead of sitting in an OS-coloured strip above it.
    # Off falls back to the native frame -- some Linux WMs handle frameless
    # windows badly, and there must be a way back without editing JSON.
    "custom_titlebar": True,
    "rail_expanded": False,     # side rail starts collapsed
    "accent": "blue",
    "animations": True,
    "matrix": True,
    "confirm_large": True,
    "large_threshold": 100,
    "sources": [],                  # legacy; per-source config lives in config.json
    "dedupe_results": True,         # collapse the same series across sources
    "interleave_results": False,    # round-robin sources instead of grouping
    "interleave_browse": True,      # trending feed mixes sources by default
    "max_concurrent_jobs": 2,       # manga downloading at the same time
    "minimize_to_tray": False,      # closing the window keeps downloads going
    "tray_notifications": True,     # notify when a download finishes
    "queue_log_advanced": False,    # verbose per-page queue log
    # ---- LAN server (server.py) --------------------------------------
    # The access token is a saved setting rather than a value regenerated
    # at every launch: a token that changes each time means re-typing it
    # on the phone each time, and a bookmarked link that silently stops
    # working. Empty means "generate one on first run and save it".
    "server_token": "",
    "server_port": 8577,
    "server_verbose": False,        # log every API call, not just startup
    # ---- OPDS catalog (opdsserve.py) ---------------------------------
    # A separate port from the app server so both can run at once: one
    # serves the UI to a browser, the other serves files to a reader.
    "opds_port": 8578,
    "opds_autostart": False,        # start the catalog with the GUI
    "opds_cover_root": "",          # folder the cover tool defaults to
    # What to do with search results you already have:
    #   "show"   leave them exactly as they are
    #   "darken" dim them, and reveal a fill + percent on hover
    #   "hide"   drop them from the results entirely
    "downloaded_results": "darken",
    "columns": 0,                   # result grid columns, 0 = fit the window
    "advanced_info": False,         # extra metadata on the manga page
    "confirm_delete": True,
    "auto_snapshot": False,
    "default_source": DEFAULT_SOURCE,
    "language": "en",               # MangaDex translation language
    "scanlator": "",                # preferred MangaDex scanlation group
    "data_saver": False,            # MangaDex compressed pages
    "library_search_roots": [],     # extra folders to look in when files move
    "reader_path": "",              # e.g. path to Readest executable
    "open_folder_when_done": False,
    "name_single": "{title} - Chapters {chapters}",
    "name_chapter": "{title} - Chapter {chapter}",
    "name_range": "{title} - Chapters {chapters}",
}

#: Reading preferences live with the reader but are stored in the same
#: config file, so one settings load returns everything the UI needs.
DEFAULT_SETTINGS.update(READER_DEFAULTS)


#: Naming templates that predate {chapters}. Anyone still carrying one of
#: these saved from an older version is migrated forward, otherwise their
#: stored value would keep overriding the improved default.
_LEGACY_NAME_TEMPLATES = {
    "name_single": ({"{title}"}, "{title} - Chapters {chapters}"),
    "name_range": ({"{title} - Chapters {start}-{end}"},
                   "{title} - Chapters {chapters}"),
}


# Settings live in config.json alongside the per-source config, behind that
# module's lock and atomic write. The old settings.json was written with a
# bare open()/json.dump: an interrupted write left truncated JSON that
# load_settings() silently swallowed and replaced with defaults, and two
# concurrent saves each wrote the state they had read, so the later one
# erased the earlier one's change. Measured on the old code, four threads
# saving at once destroyed the theme, accent and output directory in 5 out
# of 5 runs -- which is what "a lot of settings broke" looked like.
appconfig.register_settings_defaults(DEFAULT_SETTINGS)


def load_settings() -> dict:
    settings = appconfig.load_settings(DEFAULT_SETTINGS)
    for key, (legacy, replacement) in _LEGACY_NAME_TEMPLATES.items():
        if (settings.get(key) or "").strip() in legacy:
            settings[key] = replacement
    return settings


def save_settings(settings: dict) -> None:
    appconfig.save_settings(settings)


def update_settings(changes: dict) -> dict:
    """Merge changes under the config lock, so racing saves cannot clobber."""
    return appconfig.update_settings(changes, DEFAULT_SETTINGS)


def _dialog_types():
    """Dialog type constants across pywebview versions (6.x moved them)."""
    import webview
    fd = getattr(webview, "FileDialog", None)
    if fd is not None:  # pywebview >= 5.1 style
        return fd.FOLDER, fd.OPEN, fd.SAVE
    return webview.FOLDER_DIALOG, webview.OPEN_DIALOG, webview.SAVE_DIALOG


def _format_uptime(seconds: float) -> str:
    """Format seconds into human-readable uptime string."""
    if seconds <= 0:
        return "0s"
    secs = int(seconds)
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    rem_secs = secs % 60
    if mins < 60:
        return f"{mins}m {rem_secs}s"
    hrs = mins // 60
    rem_mins = mins % 60
    if hrs < 24:
        return f"{hrs}h {rem_mins}m"
    days = hrs // 24
    rem_hrs = hrs % 24
    return f"{days}d {rem_hrs}h"


def _narrow_by_type(results, wanted):
    """Keep only results whose series type matches.

    Only one source (Weeb Central) accepts a type parameter, so every other
    site silently ignored it -- searching "Manhwa" for "one piece" returned
    62 results, all of them manga. The type is now classified from the
    origin language and tags instead.

    Items whose type cannot be determined are kept: a source that reports no
    type would otherwise disappear entirely from a filtered search, which is
    a worse failure than showing an extra row.
    """
    wanted = str(wanted or "").strip()
    if not wanted or wanted.lower() in ("any", "all"):
        return results

    from ..sources.base import classify_type

    target = wanted.lower()
    kept = []
    for item in results:
        kind = (item.get("series_type") or item.get("type")
                or classify_type(item.get("original_language"),
                                 item.get("tags"),
                                 item.get("demographic")))
        if not kind:
            # Fall back to what the whole site hosts, for sources whose
            # search rows carry no per-title metadata at all.
            source_cls = SOURCES.get(item.get("source"))
            kind = getattr(source_cls, "default_series_type", None)
        if not kind or str(kind).lower() == target:
            kept.append(item)
    return kept


def _narrow_by_genres(results, extra_genres, match="all"):
    """Filter search hits by additional genres using their tags.

    Only applies to results that actually carry tags. A source that does not
    report them would otherwise vanish entirely from a multi-genre search.
    """
    wanted = [g.strip().lower() for g in extra_genres if g and g.strip()]
    if not wanted:
        return results
    need_all = str(match).lower() != "any"

    kept = []
    for item in results:
        tags = {str(t).strip().lower() for t in (item.get("tags") or [])}
        if not tags or tags == {"adult"}:
            kept.append(item)          # unknown or default tag, not disqualified
            continue
        hits = [g for g in wanted if g in tags or any(g in t for t in tags)]
        if (len(hits) == len(wanted)) if need_all else bool(hits):
            kept.append(item)
    return kept


def _safe_endpoint(func):
    """Wrap a bridge method so it can never raise into pywebview.

    Every public method here is called from JavaScript. pywebview marshals an
    exception across the native bridge, which on WebView2 surfaces as a
    rejected promise at best and can tear the view down at worst -- and the
    JS side has no way to distinguish "endpoint blew up" from "endpoint
    returned nothing". Of 102 public methods only 15 guarded themselves.

    Failures now come back as ``{"ok": False, "error": ...}``, which is the
    shape callApi() on the JS side already understands.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:                      # noqa: BLE001 - deliberate
            logger.exception("API call %s failed", func.__name__)
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    wrapper.__wrapped__ = func
    return wrapper


class _SafeApiMeta(type):
    """Apply :func:`_safe_endpoint` to every public method of the class.

    Done with a metaclass rather than by hand so a method added later is
    protected automatically -- the previous state of the file, where 87 of
    102 endpoints were unguarded, is exactly what hand-wrapping decays into.
    """

    def __new__(mcls, name, bases, namespace):
        for key, value in list(namespace.items()):
            if key.startswith("_") or not callable(value):
                continue
            if isinstance(value, (staticmethod, classmethod, property)):
                continue
            namespace[key] = _safe_endpoint(value)
        return super().__new__(mcls, name, bases, namespace)


class Api(ReaderApi, metaclass=_SafeApiMeta):
    """Methods callable from JavaScript via window.pywebview.api.*

    Reader endpoints come from ``ReaderApi``; everything else -- sources,
    downloads, queue, library, settings -- stays here, because the CLI, TUI,
    phone server and OPDS catalog all call into this same object.
    """

    def __init__(self):
        self.window = None
        self.engine = None          # most recent job, kept for back-compat
        self._thread = None
        self._sources = {}
        self._push_lock = threading.Lock()
        self._pending_events = []
        self._pending_progress = {}
        self._flush_timer = None
        # ---- multi-job download manager ----------------------------------
        # Several manga can download at once. Every job gets an id, and every
        # engine event is stamped with it, because chapter names are NOT
        # unique across manga -- two series both having "Chapter 01" was
        # enough to make one overwrite the other's progress.
        self._jobs = {}             # job id -> job record
        self._jobs_lock = threading.RLock()
        self._queue_paused = False  # tray/UI can hold the queue
        self._smart_thread = None   # background smart-cover scan
        self._smart_stop = False
        self._tray = None           # TrayController, when one is running
        self._job_seq = 0
        self._cart = []             # queued jobs waiting for a free slot
        # ---- server & opds controllers -----------------------------------
        self._server_thread = None
        self._server_instance = None
        self._server_port = None
        self._server_start_time = 0.0
        self._server_log = None
        self._opds_thread = None
        self._opds_instance = None
        self._opds_port = None
        self._opds_start_time = 0.0
        self._opds_log = None

    # ----------------------------------------------------------- sources

    def _source(self, source_id=None, url=None):
        """Get (and cache) a source instance by id, or detect it from a URL."""
        settings = load_settings()
        if not source_id and url:
            source_id = detect_source(url)
        source_id = source_id or settings.get("default_source") or DEFAULT_SOURCE

        # Aggregate members ("madara.toonily") are real sources but are not
        # in the registry -- only their parent is. This used to be handled
        # here and ONLY here, which is why browsing a Madara site worked but
        # downloading from one died with "Unknown source": the engine builds
        # its source through sources.get_source(), not through this method.
        # The resolution now lives in the registry so every caller gets it.
        if source_id not in SOURCES:
            member = resolve_member(source_id)
            if member is not None:
                return member
            raise ValueError(f"Unknown source: {source_id}")

        key = (source_id, settings.get("language", "en"),
               settings.get("scanlator", ""), bool(settings.get("data_saver")))
        if key not in self._sources:
            self._sources[key] = get_source(
                source_id,
                language=settings.get("language", "en"),
                scanlator=settings.get("scanlator") or None,
                data_saver=bool(settings.get("data_saver")),
            )
        return self._sources[key]

    # ------------------------------------------------------------ passlock

    # ------------------------------------------------------ window controls
    #
    # A frameless window has no OS titlebar, so minimise/maximise/close have
    # to come back through the bridge. Each one is guarded: in the LAN server
    # and the test harness there is no native window at all, and a phone
    # pressing "close" must not take down the host's app.

    def window_state(self):
        """Enough for the titlebar to draw itself correctly on load."""
        window = self.window
        if window is None:
            return {"ok": False, "error": "No native window", "available": False}
        state = ""
        try:
            state = str(getattr(window, "state", "") or "")
        except Exception:
            pass
        return {
            "ok": True,
            "available": True,
            "maximized": "maximize" in state.lower(),
            "title": getattr(window, "title", "Mangasurf"),
            "custom_titlebar": bool(load_settings().get("custom_titlebar", True)),
        }

    def window_minimize(self):
        return self._window_do("minimize")

    def window_maximize(self):
        """Toggle: the same button restores, which is what the icon implies."""
        window = self.window
        if window is None:
            return {"ok": False, "error": "No native window"}
        try:
            state = str(getattr(window, "state", "") or "").lower()
            if "maximize" in state:
                window.restore()
                return {"ok": True, "maximized": False}
            window.maximize()
            return {"ok": True, "maximized": True}
        except Exception as exc:
            logger.exception("window_maximize failed")
            return {"ok": False, "error": str(exc)}

    def window_restore(self):
        return self._window_do("restore")

    def window_fullscreen(self):
        return self._window_do("toggle_fullscreen")

    def window_close(self):
        """Close, honouring "minimise to tray" exactly as the OS button did.

        Hiding rather than destroying is the whole point of that setting: a
        300-chapter download must survive the window being closed.
        """
        window = self.window
        if window is None:
            return {"ok": False, "error": "No native window"}
        try:
            if load_settings().get("minimize_to_tray") and getattr(self, "_tray", None):
                window.hide()
                return {"ok": True, "hidden": True}
            window.destroy()
            return {"ok": True, "closed": True}
        except Exception as exc:
            logger.exception("window_close failed")
            return {"ok": False, "error": str(exc)}

    def _window_do(self, action: str):
        window = self.window
        if window is None:
            return {"ok": False, "error": "No native window"}
        try:
            getattr(window, action)()
            return {"ok": True}
        except Exception as exc:
            logger.exception("window %s failed", action)
            return {"ok": False, "error": str(exc)}

    def lock_status(self):
        return {"ok": True, **passlock.status()}

    def lock_verify(self, passcode: str):
        result = passlock.verify(passcode)
        if result.get("ok"):
            self._unlocked_at = time.time()
        return result

    def lock_set(self, passcode: str, hint: str = "", auto_lock_minutes: int = 0,
                 lock_on_start: bool = True, blur_covers: bool = True):
        return passlock.set_passcode(passcode, hint, auto_lock_minutes,
                                     lock_on_start, blur_covers)

    def lock_change(self, current: str, new: str):
        return passlock.change_passcode(current, new)

    def lock_disable(self, passcode: str):
        return passlock.disable(passcode)

    def lock_recover(self, recovery_key: str, new_passcode: str):
        return passlock.recover(recovery_key, new_passcode)

    def lock_options(self, options: dict):
        return {"ok": True, **passlock.update_options(**(options or {}))}

    def lock_should_lock(self):
        """Whether the UI should show the lock screen right now."""
        status = passlock.status()
        if not status["enabled"]:
            return {"ok": True, "locked": False}
        idle_minutes = status["auto_lock_minutes"]
        if getattr(self, "_unlocked_at", 0) and idle_minutes:
            idle = (time.time() - self._unlocked_at) / 60.0
            return {"ok": True, "locked": idle >= idle_minutes}
        return {"ok": True, "locked": not getattr(self, "_unlocked_at", 0)}

    # -------------------------------------------------- source config

    def get_source_config(self):
        """Sources with their rank/enabled state, for the drag-and-drop list."""
        return {"ok": True, "sources": appconfig.describe()}

    def set_source_config(self, source_id: str, changes: dict):
        return {"ok": True, "entry": appconfig.set_source_config(
            source_id, **(changes or {}))}

    def reorder_sources(self, order: list):
        """Persist a new ranking after a drag-and-drop reorder."""
        appconfig.reorder(list(order or []))
        return {"ok": True, "sources": appconfig.describe()}

    def move_source(self, source_id: str, delta: int):
        appconfig.move(source_id, int(delta))
        return {"ok": True, "sources": appconfig.describe()}

    def toggle_source(self, source_id: str, enabled: bool):
        appconfig.set_enabled(source_id, bool(enabled))
        return {"ok": True, "sources": appconfig.describe()}

    def toggle_source_search(self, source_id: str, enabled: bool):
        appconfig.set_search_enabled(source_id, bool(enabled))
        return {"ok": True, "sources": appconfig.describe()}

    def reset_source_config(self):
        appconfig.reset_config()
        return {"ok": True, "sources": appconfig.describe()}

    # ------------------------------------------------------- features

    def get_history(self, limit: int = 30):
        return {"ok": True, "items": features.get_history(limit)}

    def suggest_query(self, prefix: str):
        from ..database import get_search_suggestions
        from ..config import load_settings
        s = load_settings()
        include_sfw = s.get("db_sfw_enabled", True)
        include_nsfw = not s.get("safe_mode", False) and s.get("db_nsfw_enabled", True)
        suggestions = get_search_suggestions(prefix, include_sfw=include_sfw, include_nsfw=include_nsfw, limit=8)
        history_items = features.suggest(prefix)
        return {"ok": True, "items": history_items, "suggestions": suggestions}

    def search_database(self, query: str, limit: int = 25):
        from ..database import search_database as db_search
        from ..config import load_settings
        s = load_settings()
        include_sfw = s.get("db_sfw_enabled", True)
        include_nsfw = not s.get("safe_mode", False) and s.get("db_nsfw_enabled", True)
        results = db_search(query, include_sfw=include_sfw, include_nsfw=include_nsfw, limit=limit)
        return {"ok": True, "results": results}

    def clear_history(self):
        features.clear_history()
        return {"ok": True}

    def remove_history(self, query: str):
        return {"ok": True, "items": features.remove_history(query)}

    def get_filters(self):
        return {"ok": True, "filters": features.get_filters()}

    def set_filters(self, changes: dict):
        return {"ok": True, "filters": features.set_filters(**(changes or {}))}

    def get_stats(self):
        return {"ok": True, "stats": features.get_stats()}

    def reset_stats(self):
        features.reset_stats()
        return {"ok": True}

    def get_insights(self):
        return {"ok": True, "insights": features.library_insights()}

    def get_calendar(self, weeks: int = None):
        """Contribution-graph data: one entry per day, with its sources.

        Source display names travel with it so the UI does not have to keep
        its own copy of the registry -- an id like ``madara.toonily`` is not
        something to put in a tooltip.
        """
        try:
            data = features.stat_calendar(
                weeks or features.CALENDAR_WEEKS)
            names = {}
            for source_id in data.get("sources", {}):
                try:
                    names[source_id] = self._source_name(source_id)
                except Exception:
                    names[source_id] = source_id
            data["names"] = names
            return {"ok": True, "calendar": data}
        except Exception as e:
            logger.debug("calendar failed", exc_info=True)
            return {"ok": False, "error": str(e), "calendar": None}

    def _source_name(self, source_id: str) -> str:
        """Human label for a source id, including aggregate members.

        Aggregate members carry a namespaced id ("madara.toonily") and are
        not in the registry -- only their parent is. MEMBERS is a tuple of
        source *classes*, so it is searched by id rather than indexed.
        """
        if not source_id or source_id == "?":
            return "Unknown"
        cls = SOURCES.get(source_id)
        if cls is not None:
            return getattr(cls, "name", source_id)

        if "." in source_id:
            parent_id, member_id = source_id.split(".", 1)
            if parent_id == "madara":
                parent_id = "madaranet"
            parent = SOURCES.get(parent_id)
            for member in (getattr(parent, "MEMBERS", None) or ()):
                if getattr(member, "id", None) == source_id:
                    return getattr(member, "name", source_id)
            return member_id.replace("-", " ").replace("_", " ").title()
        return source_id

    def get_collections(self):
        return {"ok": True, "collections": features.get_collections()}

    def add_to_collection(self, name: str, item: dict):
        return {"ok": True, "collections": features.add_to_collection(name, item)}

    def remove_from_collection(self, name: str, url: str):
        return {"ok": True,
                "collections": features.remove_from_collection(name, url)}

    def delete_collection(self, name: str):
        return {"ok": True, "collections": features.delete_collection(name)}

    def get_queue(self):
        """Everything currently downloading, queued, or in the job cart."""
        with self._jobs_lock:
            items = []
            for j in self._jobs.values():
                status = j.get("status", "running")
                if status == "done":
                    continue
                eng = j.get("engine")
                prog = getattr(eng, "progress", None)
                snap = prog.snapshot(sample=True) if prog else {}
                fraction = getattr(prog, "fraction", 0.0) if prog else 0.0
                chapter_text = str(getattr(prog, "chapter", "")) if prog else ""

                items.append({
                    "id": j.get("id"),
                    "title": j.get("title") or j.get("url"),
                    "url": j.get("url"),
                    "source": j.get("source", ""),
                    "cover": j.get("cover", ""),
                    "status": status,
                    "progress": fraction,
                    "chapter": chapter_text,
                    "speed_text": snap.get("speed_text", "0 KB/s"),
                    "eta_text": snap.get("eta_text", "--"),
                    "downloaded_text": snap.get("downloaded_text", "0 B"),
                    "history": snap.get("history", []),
                    "chapters_done": snap.get("chapters_done", 0),
                    "chapters_total": snap.get("chapters_total", 0),
                    "pages_done": snap.get("pages_done", 0),
                    "pages_total": snap.get("pages_total", 0),
                })
            for q in self._cart:
                items.append({
                    "title": q.get("title") or q.get("options", {}).get("url") or "Queued Manga",
                    "url": q.get("options", {}).get("url", ""),
                    "cover": q.get("cover", ""),
                    "status": "queued",
                    "progress": 0.0,
                    "chapter": "Waiting in queue…",
                    "speed_text": "0 KB/s",
                    "eta_text": "--",
                    "downloaded_text": "0 B",
                    "history": [],
                })
        return {"ok": True, "items": items, "queue": items}

    def queue_add(self, options: dict):
        return self.add_to_cart(options or {})

    def queue_remove(self, job_id: str):
        with self._jobs_lock:
            if job_id in self._jobs:
                self.stop_download(job_id)
            self._cart = [q for q in self._cart if q.get("id") != job_id]
        return self.get_queue()

    def queue_move(self, job_id: str, delta: int):
        return {"ok": True, "items": self.get_queue().get("items", [])}

    def queue_clear(self, status: str = None):
        with self._jobs_lock:
            self._cart = []
            self.stop_download()
            features.queue_clear(status)
        self._flush()
        return {"ok": True, "items": [], "queue": []}

    def export_library(self, fmt: str = "json"):
        try:
            _, _, save_t = _dialog_types()
            ext = {"json": "json", "csv": "csv", "md": "md"}.get(fmt, "json")
            dest = self.window.create_file_dialog(
                save_t, save_filename=f"readerm-library.{ext}")
            if not dest:
                return {"ok": False, "cancelled": True}
            if isinstance(dest, (list, tuple)):
                dest = dest[0]
            features.export_library(dest, fmt)
            return {"ok": True, "path": dest}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def import_library(self):
        try:
            _, open_t, _ = _dialog_types()
            chosen = self.window.create_file_dialog(open_t)
            if not chosen:
                return {"ok": False, "cancelled": True}
            if isinstance(chosen, (list, tuple)):
                chosen = chosen[0]
            return {"ok": True, **features.import_library(chosen)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def snapshot(self, label: str = ""):
        return {"ok": True, "snapshot": features.snapshot(label)}

    def list_snapshots(self):
        return {"ok": True, "items": features.list_snapshots()}

    def restore_snapshot(self, snapshot_id: str):
        return {"ok": features.restore_snapshot(snapshot_id)}

    def open_url(self, url: str):
        """Open a link in the user's real browser."""
        try:
            import webbrowser
            webbrowser.open(url)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------- tracking

    def mark_read(self, url: str, chapter_name: str, read: bool = True):
        tracking.mark_read(url, chapter_name, read)
        return {"ok": True}

    def mark_many_read(self, url: str, names: list, read: bool = True):
        tracking.mark_many(url, list(names or []), read)
        return {"ok": True}

    def get_progress(self, url: str, chapters: list = None):
        return {"ok": True,
                "progress": tracking.progress_for(url, chapters or []),
                "read": sorted(tracking.read_chapters(url))}

    def clear_progress(self, url: str = None):
        tracking.clear_progress(url)
        return {"ok": True}

    def watch(self, url: str, title: str, chapter_count: int,
              source: str = None, cover: str = None):
        return {"ok": True,
                "entry": tracking.watch(url, title, chapter_count, source, cover)}

    def unwatch(self, url: str):
        return {"ok": tracking.unwatch(url)}

    def is_watched(self, url: str):
        return {"ok": True, "watched": tracking.is_watched(url)}

    def get_watchlist(self):
        return {"ok": True, "items": tracking.get_watchlist()}

    def check_updates(self):
        try:
            return {"ok": True, "updates": tracking.check_updates()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def acknowledge_updates(self, url: str):
        tracking.acknowledge(url)
        return {"ok": True}

    def set_note(self, url: str, note: str = "", rating: int = 0,
                 tags: list = None):
        return {"ok": True, "entry": tracking.set_note(url, note, rating, tags)}

    def get_note(self, url: str):
        return {"ok": True, "note": tracking.get_note(url)}

    def get_rated(self, minimum: int = 1):
        return {"ok": True, "items": tracking.rated(minimum)}

    # --------------------------------------------------- disk tools

    def disk_usage(self, root: str = None):
        root = root or load_settings().get("output_dir")
        return {"ok": True, "rows": tracking.disk_usage(root),
                "root": root}

    def scan_duplicates(self, root: str = None):
        root = root or load_settings().get("output_dir")
        groups = tracking.scan_duplicates(root)
        return {"ok": True, "groups": groups,
                "wasted": sum(g["wasted"] for g in groups)}

    # ------------------------------------------------- cover rebuilder

    def scan_covers(self, root: str = None, overwrite: bool = False):
        """Find CBZ folders that need a cover. Read-only."""
        from .. import covers

        root = root or load_settings().get("output_dir")
        groups = covers.plan(root, overwrite=bool(overwrite))
        return {"ok": True, "root": root, "groups": [
            {
                "key": g["key"],
                "title": g["title"],
                "directory": g["directory"],
                "target_dir": g["target_dir"],
                "archives": g["archives"],
                "count": len(g["archives"]),
                "needs_move": g["needs_move"],
                "has_cover": g["has_cover"],
            }
            for g in groups
        ]}

    def organise_covers(self, root: str = None):
        """Split a flat folder of loose archives into one folder per series.

        Answers the "I have 300 CBZs in one directory" case without needing a
        cover for each: every archive is moved into a folder named after its
        series, and covers can then be fetched (or not) at leisure.

        Archives already alone with their own series are left untouched.
        """
        from .. import covers

        root = root or load_settings().get("output_dir")
        moved = folders = 0
        failed = []
        for group in covers.scan(root):
            if not group.get("needs_move"):
                continue
            try:
                covers.isolate(group)
                folders += 1
                moved += len(group["archives"])
            except OSError as e:
                failed.append({"title": group["title"], "error": str(e)})
        return {"ok": True, "root": root, "moved": moved,
                "folders": folders, "failed": failed}

    def smart_covers(self, root: str = None, overwrite: bool = False,
                     organise: bool = True):
        """One button: scan, choose and apply covers for a whole folder.

        For each series it searches every enabled source and takes the best
        candidate by the rules in :func:`readerm.covers.auto_pick` -- exact
        title first, then the source order from Settings, then resolution to
        avoid picking a list thumbnail.

        Runs in the background and reports progress through the normal event
        stream, because a large library means one search per series and that
        is far too slow to block the UI on.
        """
        from .. import covers

        root = root or load_settings().get("output_dir")
        if getattr(self, "_smart_thread", None) is not None \
                and self._smart_thread.is_alive():
            return {"ok": False, "error": "A smart scan is already running"}

        self._smart_stop = False

        def run():
            done = failed = moved = 0
            try:
                groups = covers.plan(root, overwrite=bool(overwrite))
                self._push({"type": "smart_start", "total": len(groups),
                            "root": root})
                for index, group in enumerate(groups, 1):
                    if self._smart_stop:
                        break
                    self._push({"type": "smart_progress", "done": index - 1,
                                "total": len(groups),
                                "title": group["title"]})
                    directory = group["directory"]
                    try:
                        if organise and group.get("needs_move"):
                            directory = covers.isolate(group)
                            moved += len(group["archives"])
                        elif group.get("needs_move"):
                            # Not organising: the archives share a folder, so
                            # a cover here would be wrong for the others.
                            failed += 1
                            self._push({"type": "smart_item", "ok": False,
                                        "title": group["title"],
                                        "error": "shares a folder"})
                            continue
                        result = covers.auto_cover(group["title"], directory)
                    except Exception as e:
                        logger.exception("smart cover failed")
                        result = {"ok": False, "error": str(e)}

                    if result.get("ok"):
                        done += 1
                        chosen = result.get("chosen") or {}
                        self._push({
                            "type": "smart_item", "ok": True,
                            "title": group["title"],
                            "source": chosen.get("source_name")
                            or chosen.get("source"),
                            "width": result.get("width"),
                            "height": result.get("height"),
                            "directory": directory,
                        })
                    else:
                        failed += 1
                        self._push({"type": "smart_item", "ok": False,
                                    "title": group["title"],
                                    "error": result.get("error")})
            finally:
                self._push({"type": "smart_done", "done": done,
                            "failed": failed, "moved": moved,
                            "stopped": bool(self._smart_stop)})
                self._flush()

        self._smart_thread = threading.Thread(
            target=run, daemon=True, name="readerm-smart-covers")
        self._smart_thread.start()
        return {"ok": True, "started": True}

    def stop_smart_covers(self):
        """Ask a running smart scan to stop after the current series."""
        self._smart_stop = True
        return {"ok": True}

    def cover_candidates(self, title: str, limit: int = 6):
        """Ranked cover options for one title, for the user to choose from."""
        from .. import covers

        rows = covers.candidates(title, limit=int(limit or 6))
        for row in rows:
            # Proxy anything whose CDN refuses hotlinks, so the picker can
            # actually render the thumbnail.
            row["preview"] = self._cover_preview(row)
        return {"ok": True, "title": title, "candidates": rows}

    def _cover_preview(self, row):
        """A data URI the web view can display for a candidate.

        Every preview is proxied, not just the Referer-gated ones. Measured
        in the picker: three of twelve thumbnails rendered blank with
        ERR_BLOCKED_BY_RESPONSE.NotSameOrigin -- the images fetch fine from
        Python (all 200) but the embedded browser refuses them cross-origin.
        Picking a cover you cannot see is not a choice, so the bytes come
        through Python and the browser only ever sees a data: URI.
        """
        try:
            proxied = self.proxy_cover(row["cover"], row.get("source"))
            if isinstance(proxied, dict) and proxied.get("data"):
                return proxied["data"]
        except Exception:
            logger.debug("cover preview failed", exc_info=True)
        # Fall back to the direct URL: a blank tile beats no tile, and some
        # CDNs do serve cross-origin happily.
        return row.get("cover")

    def apply_cover(self, group: dict, candidate: dict):
        """Write the chosen cover into the group's own folder.

        Archives sharing a directory with other series are moved into a
        folder of their own first, so the cover sits beside its CBZ rather
        than in a parent shared with unrelated series.
        """
        from .. import covers

        group = group or {}
        candidate = candidate or {}
        url = (candidate.get("cover") or "").strip()
        if not url:
            return {"ok": False, "error": "No cover chosen"}
        if not group.get("directory"):
            return {"ok": False, "error": "No folder for this series"}

        try:
            directory = covers.isolate({
                "directory": group["directory"],
                "target_dir": group.get("target_dir") or group["directory"],
                "archives": group.get("archives") or [],
                "needs_move": bool(group.get("needs_move")),
            })
        except OSError as e:
            return {"ok": False, "error": f"Could not move archives: {e}"}

        saved = covers.save_cover(url, directory,
                                  source_id=candidate.get("source"),
                                  referer=candidate.get("url"))
        if not saved:
            return {"ok": False,
                    "error": "The cover could not be downloaded"}
        return {"ok": True, "cover": saved, "directory": directory,
                "moved": bool(group.get("needs_move"))}

    def find_orphans(self):
        return {"ok": True, "orphans": tracking.find_orphans()}

    def delete_files(self, paths: list):
        """Delete chosen files (used by the duplicate cleaner)."""
        removed, failed = [], []
        for path in paths or []:
            try:
                os.remove(path)
                removed.append(path)
            except OSError as e:
                failed.append({"path": path, "error": str(e)})
        return {"ok": True, "removed": removed, "failed": failed}

    # ---------------------------------------------- moved folders

    def verify_library(self):
        """Which library entries still resolve on disk."""
        return library.verify_entries()

    def relocate_entry(self, url: str, new_dir: str = None):
        """Point one entry at a folder the user moved it to."""
        if not new_dir:
            new_dir = self.choose_folder()
            if not new_dir:
                return {"ok": False, "cancelled": True}
        return library.relocate_entry(url, new_dir)

    def find_moved_entries(self, roots: list = None):
        """Propose relocations by matching folder names under given roots.

        Nothing is written: the UI shows the proposals and the user confirms.
        """
        if not roots:
            settings = load_settings()
            roots = [settings.get("output_dir")]
            extra = settings.get("library_search_roots") or []
            roots += [r for r in extra if r]
        return {"ok": True, "proposals": library.find_moved_entries(roots)}

    def apply_relocations(self, proposals: list):
        return library.apply_relocations(proposals or [])

    def rescan_output_dir(self, root: str = None):
        """Adopt a new downloads folder and relocate everything under it."""
        root = root or self.choose_folder()
        if not root:
            return {"ok": False, "cancelled": True}
        if not os.path.isdir(root):
            return {"ok": False, "error": f"Not a folder: {root}"}

        # remember it as the download location going forward
        update_settings({"output_dir": root})

        proposals = library.find_moved_entries([root])
        result = library.apply_relocations(proposals)
        return {"ok": True, "output_dir": root,
                "relocated": result.get("applied", 0),
                "still_missing": len(library.verify_entries()["missing"])}

    def get_health(self):
        """Circuit-breaker state and cache hit rates, for the Tools tab."""
        try:
            from ..robust import health_report
            return {"ok": True, "report": health_report()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # Covers whose CDN refuses hotlinks cannot be loaded by an <img> tag:
    # the GUI sends "no-referrer" globally because MangaDex swaps in a
    # placeholder otherwise, and Webtoons' pstatic.net answers 403 to any
    # request that does not carry a webtoons.com Referer. The two demands
    # are mutually exclusive in one document, so those covers are fetched
    # here -- with the right Referer -- and handed back as a data URI.
    # Bounded by BYTES, not entry count. A proxied cover is a base64 data URI
    # -- measured 116 KB for one Webtoons cover -- so the old 240-entry cap
    # held ~28 MB of RSS, and a source with larger art scaled that without
    # any ceiling. An OrderedDict gives proper LRU eviction instead of the
    # previous clear(), which threw away every cover the moment it filled.
    _COVER_CACHE = collections.OrderedDict()
    _COVER_CACHE_MAX_BYTES = 24 * 1024 * 1024
    #: Refuse to cache anything absurd; still returned, just not retained.
    _COVER_MAX_ITEM_BYTES = 4 * 1024 * 1024
    _COVER_LOCK = threading.Lock()

    @classmethod
    def _cache_cover(cls, url, data):
        """Store a cover, evicting least-recently-used entries by size."""
        if len(data) > cls._COVER_MAX_ITEM_BYTES:
            return
        with cls._COVER_LOCK:
            cls._COVER_CACHE.pop(url, None)
            cls._COVER_CACHE[url] = data
            total = sum(len(v) for v in cls._COVER_CACHE.values())
            while total > cls._COVER_CACHE_MAX_BYTES and len(cls._COVER_CACHE) > 1:
                _key, dropped = cls._COVER_CACHE.popitem(last=False)
                total -= len(dropped)

    def proxy_cover(self, url: str, source_id: str = None):
        """Fetch a hotlink-protected cover and return it as a data URI."""
        import base64

        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "unsupported url"}

        with self._COVER_LOCK:
            cached = self._COVER_CACHE.get(url)
            if cached is not None:
                self._COVER_CACHE.move_to_end(url)   # keep it warm
        if cached:
            return {"ok": True, "data": cached, "cached": True}

        try:
            source = None
            if source_id:
                source = self._source(source_id)
            if source is None:
                try:
                    source = source_for_url(url)
                except Exception:
                    source = None

            if source is not None:
                response = source.fetch(url, max_retries=2)
                blob = response.content
                mime = (response.headers.get("Content-Type") or "").split(";")[0].strip()
            else:
                import requests
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                if "shadowabyss" in url:
                    headers["Referer"] = "https://kuramanga.com/"
                elif "r2d2storage" in url or "hiperdex" in url:
                    headers["Referer"] = "https://hiperdex.com/"
                    headers["x-cfg-auth"] = "yceqt7qgu004"
                elif "resmk" in url or "qvzre" in url or "mangak" in url:
                    headers["Referer"] = "https://mangak.io/"
                response = requests.get(url, headers=headers, timeout=8)
                blob = response.content if response.status_code == 200 else b""
                mime = (response.headers.get("Content-Type") or "").split(";")[0].strip()

            if not blob:
                return {"ok": False, "error": "empty response"}

            if not mime.startswith("image/"):
                mime = "image/jpeg"
            data = f"data:{mime};base64," + base64.b64encode(blob).decode("ascii")

            self._cache_cover(url, data)
            return {"ok": True, "data": data}
        except Exception as e:
            logger.warning("Cover proxy failed for %s: %s", url, e)
            return {"ok": False, "error": str(e)}

    def get_sources(self):
        """Every supported site, for the source picker."""
        return {"ok": True, "sources": list_sources(),
                "default": load_settings().get("default_source") or DEFAULT_SOURCE}

    # ------------------------------------------------------------- push

    # Progress events fire once per downloaded image. A 700-chapter job at
    # ~60 pages each is >43,000 evaluate_js calls, every one of them a JSON
    # dump interpolated into a JS string and marshalled across the native
    # bridge. That is what pins a CPU core and takes WebView2 down with
    # 0xCFFFFFFF. High-frequency events are therefore coalesced and flushed
    # on a timer as a single batch; lifecycle events still go out at once.
    _FLUSH_INTERVAL = 0.12          # seconds between batches
    _COALESCE = {"chapter_progress"}

    def _push(self, event: dict):
        """Queue an engine event for delivery to the web UI."""
        if self.window is None:
            return

        etype = event.get("type")
        with self._push_lock:
            if etype in self._COALESCE:
                # Keep only the newest progress per chapter -- but key on
                # (job, chapter). Keying on the chapter name alone meant two
                # manga downloading at once both reporting "Chapter 01"
                # collapsed into a single event, so one series' progress
                # silently replaced the other's.
                key = (event.get("job"), event.get("chapter"))
                self._pending_progress[key] = event
            else:
                self._pending_events.append(event)

            if self._flush_timer is None:
                self._flush_timer = threading.Timer(self._FLUSH_INTERVAL,
                                                    self._flush)
                self._flush_timer.daemon = True
                self._flush_timer.start()

        # deliver terminal events immediately so the UI never lags at the end
        if etype in ("finished", "done", "stopped", "error"):
            self._flush()

    def _flush(self):
        """Send everything queued as one batched call."""
        with self._push_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
            batch = self._pending_events
            batch += list(self._pending_progress.values())
            self._pending_events = []
            self._pending_progress = {}

        if not batch or self.window is None:
            return
        try:
            payload = json.dumps(batch)
            self.window.evaluate_js(f"window.onEngineEvents({payload})")
        except Exception:
            logger.debug("Failed to push events to the UI", exc_info=True)

    # ------------------------------------------------------------ pages

    def search(self, query: str, filters: dict = None):
        """Omnibar search, direct URL lookup, or trending browse."""
        try:
            if isinstance(filters, str):
                filters = {"source": filters}
            elif filters is not None and not isinstance(filters, dict):
                filters = {}
            f = filters or {}
            source_id = (f.get("source") or "").strip()
            genres = split_genres(f.get("genres") or f.get("genre"))
            genre = genres[0] if genres else ""
            match = (f.get("genre_match") or "all").lower()
            query = (query or "").strip()

            # Omnibar prefix handling: @source <query> or source: <query>
            prefix_match = re.match(r"^@([a-zA-Z0-9._-]+)\s+(.+)$", query)
            if not prefix_match:
                prefix_match = re.match(r"^([a-zA-Z0-9._-]+):\s*(.+)$", query)
            if prefix_match:
                candidate_src = prefix_match.group(1).lower()
                candidate_query = prefix_match.group(2).strip()
                if candidate_src in SOURCES or candidate_src in AGGREGATE_PREFIXES or any(s.startswith(candidate_src) for s in SOURCES):
                    matched_src = next((s for s in SOURCES if s == candidate_src or s.startswith(candidate_src)), candidate_src)
                    source_id = matched_src
                    query = candidate_query

            # Omnibar genre tags: #action #comedy
            if "#" in query:
                tag_matches = re.findall(r"#([a-zA-Z0-9_-]+)", query)
                if tag_matches:
                    for tag in tag_matches:
                        tag_clean = tag.replace("-", " ")
                        if tag_clean.lower() not in [g.lower() for g in genres]:
                            genres.append(tag_clean)
                    query = re.sub(r"#[a-zA-Z0-9_-]+", "", query).strip()

            # Check for curated list / collection URLs (e.g. https://chikari.moe/lists/461-my-manhwa-list)
            if query and ("chikari.moe/list" in query or "/lists/" in query):
                try:
                    src = self._source("chikari")
                    if hasattr(src, "get_list_series"):
                        list_data = src.get_list_series(query)
                        if list_data and list_data.get("series"):
                            return {
                                "ok": True,
                                "is_list": True,
                                "list": list_data,
                                "results": list_data["series"],
                                "source": "chikari",
                            }
                except Exception as e:
                    logger.debug("Chikari list parsing failed: %s", e)

            # Pasting a URL jumps straight to that manga
            if query and (query.startswith(("http://", "https://")) or "/" in query):
                detected = detect_source(query)
                if detected:
                    return {"ok": True, "results": [], "url": query, "source": detected}

            if not query:
                return self.browse({
                    "source": source_id,
                    "genres": genres,
                    "genre_match": match,
                    "sort": f.get("browse_sort") or "Trending",
                    "page": f.get("page", 1),
                    "status": f.get("status"),
                })

            kwargs = dict(
                sort=f.get("sort") or None,
                status=f.get("status"),
                series_type=f.get("type"),
                order=f.get("order", "Ascending"),
                official=f.get("official", "Any"),
                genre=genre or None,
                page=max(1, int(f.get("page", 1) or 1)),
            )
            kwargs = {k: v for k, v in kwargs.items() if v not in (None, "", "Any")}

            settings = load_settings()
            limit = max(12, int(f.get("limit", 24) or 24))
            if source_id in ("", "all"):
                results = search_all(
                    query, limit=limit,
                    interleave=bool(settings.get("interleave_results")),
                    **kwargs)
            else:
                results = self._source(source_id).search(query, limit=limit, **kwargs)

            if len(genres) > 1:
                results = _narrow_by_genres(results, genres[1:], match)
            results = _narrow_by_type(results, f.get("type"))

            results = features.apply_filters(results)
            if settings.get("dedupe_results", True) and source_id in ("", "all"):
                ranks = {row["id"]: row.get("rank", 100)
                         for row in appconfig.describe()}
                results = features.dedupe(results, ranks)

            features.add_history(query, source_id or "all", len(results))
            return {"ok": True, "results": results, "source": source_id}
        except Exception as e:
            logger.exception("Search failed")
            return {"ok": False, "error": str(e)}

    def browse(self, options: dict = None):
        """Trending / genre discovery, merged across the enabled sources."""
        try:
            o = options or {}
            source_id = (o.get("source") or "").strip()
            # A genre may now be a list, or a comma separated string.
            genres = split_genres(o.get("genres") or o.get("genre"))
            genre = genres[0] if genres else None
            match = (o.get("genre_match") or "all").lower()
            sort = o.get("sort") or "Trending"
            page = max(1, int(o.get("page", 1) or 1))
            settings = load_settings()

            extra = {}
            if o.get("status") and o["status"] != "Any":
                extra["status"] = o["status"]

            if source_id in ("", "all"):
                if len(genres) > 1:
                    results = browse_multi(
                        genres, sort=sort, page=page, limit=24, match=match,
                        interleave=bool(settings.get("interleave_browse", True)),
                        **extra)
                else:
                    results = browse_all(
                        sort=sort, genre=genre, page=page, limit=12,
                        interleave=bool(settings.get("interleave_browse", True)),
                        **extra)
            else:
                source = self._source(source_id)
                if not getattr(source, "supports_browse", False):
                    return {"ok": True, "results": [], "browse": True,
                            "message": f"{source.name} cannot list trending titles"}
                if len(genres) > 1:
                    results = browse_multi(
                        genres, sort=sort, page=page, limit=32, match=match,
                        source_ids=[source_id], use_config=False,
                        interleave=False, **extra)
                else:
                    # a per-source genre id may differ from the shared label
                    results = source.browse(sort=sort, genre=genre, page=page,
                                            limit=32, **extra)

            results = features.apply_filters(results)
            if settings.get("dedupe_results", True) and source_id in ("", "all"):
                ranks = {row["id"]: row.get("rank", 100)
                         for row in appconfig.describe()}
                results = features.dedupe(results, ranks)

            return {"ok": True, "results": results, "browse": True,
                    "genre": genre, "genres": genres, "genre_match": match,
                    "sort": sort, "page": page}
        except Exception as e:
            logger.exception("Browse failed")
            return {"ok": False, "error": str(e)}

    def get_genres(self, source_id: str = None):
        """Genres for one source, or the union across enabled sources."""
        try:
            if source_id and source_id != "all":
                source = self._source(source_id)
                return {"ok": True, "genres": source.genres() or []}
            return {"ok": True, "genres": genres_all()}
        except Exception as e:
            return {"ok": False, "error": str(e), "genres": []}

    def get_manga(self, url: str, source_id: str = None):
        try:
            source = self._source(source_id, url=url)
            info = source.get_manga_info(url)
            chapters = source.get_chapters(url)
            return {
                "ok": True,
                "info": info,
                "chapters": chapters,
                "source": source.id,
                "source_name": source.name,
                # Match on chapter number, not the raw label: several
                # sources append a release date that the site later edits,
                # which made downloaded chapters show as missing while still
                # counting toward the total.
                "downloaded": sorted(library.match_downloaded(url, chapters)),
                "bookmarked": library.is_bookmarked(url),
                "watched": tracking.is_watched(url),
                "read": sorted(tracking.read_chapters(url)),
                "progress": tracking.progress_for(url, chapters),
                "note": tracking.get_note(url),
            }
        except Exception as e:
            logger.exception("get_manga failed")
            return {"ok": False, "error": str(e)}

    def get_covers(self, url: str, source_id: str = None):
        """Alternative covers (MangaDex volume art), if the source has any."""
        try:
            source = self._source(source_id, url=url)
            if not hasattr(source, "get_covers"):
                return {"ok": True, "covers": []}
            return {"ok": True, "covers": source.get_covers(url)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---------------------------------------------- library and bookmarks

    def get_library(self):
        lib = library.load_library()
        items = []
        for entry in lib.values():
            outputs = entry.get("outputs", [])
            parts = []
            for out in outputs:
                parts.append({
                    "path": out,
                    "name": os.path.basename(out),
                    "exists": os.path.isfile(out),
                    "size": os.path.getsize(out) if os.path.isfile(out) else 0,
                })
            items.append({
                "url": entry.get("url"),
                "title": entry.get("title"),
                "cover": entry.get("cover"),
                "directory": entry.get("directory"),
                "chapter_count": len(entry.get("chapters", {})),
                "pages": sum(c.get("pages", 0) for c in entry.get("chapters", {}).values()),
                "outputs": outputs,
                "parts": parts,
                "last_download": entry.get("last_download"),
            })
        items.sort(key=lambda x: x.get("last_download") or "", reverse=True)
        return {"ok": True, "items": items, "path": library.LIBRARY_PATH}

    def downloaded_status(self, items: list = None):
        """Download status for a batch of search results.

        Returns ``{url: {chapters, total, percent, complete, title}}`` for
        the entries that are in the library at all -- callers only need the
        hits, so a page of 40 unknown results costs one small reply.

        ``total`` is the series' own chapter count as the *source* reported
        it, which is frequently unknown: a site that never states one gives
        ``total: 0``, and then ``percent`` is None rather than a fabricated
        number. "Downloaded 12 chapters, out of we-don't-know" is honest;
        inventing 100% because 12 of the 12 we know about are present is
        not, and would mark an ongoing series as finished.

        Batched deliberately. Doing this per card meant one bridge call per
        result, and the library file was re-read and re-parsed every time.
        """
        rows = [i for i in (items or []) if isinstance(i, dict) and i.get("url")]
        if not rows:
            return {"ok": True, "status": {}}

        # Read the library once for the whole batch.
        lib = library.load_library()
        out = {}
        for item in rows:
            url = item.get("url")
            entry = library._find_entry(lib, url)
            if not entry:
                continue
            done = len(entry.get("chapters", {}) or {})
            if not done:
                continue
            total = features._chapter_count(item) or 0
            total = int(total) if total and total > 0 else 0
            percent = None
            if total:
                percent = max(0, min(100, round(done / total * 100)))
            out[url] = {
                "chapters": done,
                "total": total,
                "percent": percent,
                "complete": bool(total and done >= total),
                "title": entry.get("title") or item.get("title") or "",
                "directory": entry.get("directory") or "",
                "last_download": entry.get("last_download") or "",
            }
        return {"ok": True, "status": out}

    def get_library_entry(self, url: str):
        # Must go through the tolerant lookup: library keys are normalised,
        # so a raw URL (or one carrying ?query) can miss a real entry.
        entry = library.get_entry(url)
        if not entry:
            return {"ok": False, "error": "Not in library"}
        chapters = [
            {"name": name, **meta}
            for name, meta in sorted(entry.get("chapters", {}).items())
        ]
        return {"ok": True, "entry": {**entry, "chapters": chapters}}

    def remove_library_entry(self, url: str):
        return {"ok": library.remove_entry(url)}

    def get_bookmarks(self):
        return {"ok": True, "items": library.load_bookmarks()}

    def toggle_bookmark(self, info: dict):
        try:
            return {"ok": True, "bookmarked": library.toggle_bookmark(info)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def clear_library(self):
        library.clear_library()
        return {"ok": True}

    def clear_bookmarks(self):
        library.clear_bookmarks()
        return {"ok": True}

    # ------------------------------------------------- bookmark folders

    def get_bookmark_folders(self):
        try:
            return {"ok": True, **library.folders_with_contents()}
        except Exception as e:
            logger.exception("Folder listing failed")
            return {"ok": False, "error": str(e), "folders": [], "unfiled": []}

    def create_bookmark_folder(self, name: str, options: dict = None):
        o = options or {}
        return library.create_folder(name, colour=o.get("colour"),
                                     locked=o.get("locked"),
                                     blurred=o.get("blurred"))

    def update_bookmark_folder(self, folder_id: str, changes: dict = None):
        return library.update_folder(folder_id, **(changes or {}))

    def delete_bookmark_folder(self, folder_id: str, delete_bookmarks: bool = False):
        return library.delete_folder(folder_id, bool(delete_bookmarks))

    def move_bookmark(self, url: str, folder_id: str = ""):
        return library.set_bookmark_folder(url, folder_id or "")

    def bookmark_into(self, info: dict, folder_id: str = ""):
        """Bookmark a manga and file it in one step."""
        try:
            added = library.toggle_bookmark(info or {})
            if added and folder_id:
                library.set_bookmark_folder((info or {}).get("url"), folder_id)
            return {"ok": True, "bookmarked": added}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------- logs and recovery

    def get_log_info(self):
        return {"ok": True, **wclogs.log_info()}

    def export_log(self):
        """Save-as dialog, then export the combined log there."""
        try:
            _, _, save_t = _dialog_types()
            dest = self.window.create_file_dialog(
                save_t,
                save_filename=f"readerm-{time.strftime('%Y%m%d-%H%M%S')}.log",
            )
            if not dest:
                return {"ok": False, "cancelled": True}
            if isinstance(dest, (list, tuple)):
                dest = dest[0]
            wclogs.export_log(dest)
            return {"ok": True, "path": dest}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def clear_log(self):
        try:
            for suffix in ("", ".1", ".2", ".3"):
                path = wclogs.LOG_FILE + suffix
                if os.path.isfile(path):
                    open(path, "w").close() if suffix == "" else os.remove(path)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_pending_job(self):
        """Crashed/interrupted jobs that can be resumed.

        Reports every journaled job, not just one: with concurrent downloads
        a crash can strand several, and before v1.4.19 the journal was a
        single file so all but the last were lost outright.
        """
        jobs = wclogs.read_journals()
        if not jobs:
            return {"ok": True, "pending": None, "pending_all": []}

        def describe(job):
            return {
                "job_id": job.get("job_id"),
                "title": job.get("title") or "Unknown manga",
                "started": job.get("started"),
                "url": job.get("options", {}).get("url"),
                "selection": job.get("options", {}).get("selection"),
            }

        return {"ok": True,
                "pending": describe(jobs[0]),       # back-compat
                "pending_all": [describe(j) for j in jobs]}

    def resume_pending_job(self, job_id: str = None):
        """Restart journaled job(s); completed chapters are skipped."""
        jobs = wclogs.read_journals()
        if not jobs:
            return {"ok": False, "error": "Nothing to resume"}
        if job_id:
            jobs = [j for j in jobs if j.get("job_id") == job_id] or jobs[:1]
        results = [self.add_to_cart(dict(j["options"], title=j.get("title", "")))
                   for j in jobs]
        return {"ok": True, "resumed": len(results)}

    def discard_pending_job(self, job_id: str = None):
        wclogs.clear_journal(job_id)
        return {"ok": True}

    # --------------------------------------------------------- settings

    def get_settings(self):
        return load_settings()

    def set_settings(self, settings: dict):
        # Locked read-modify-write. Doing this in two steps let a concurrent
        # save (the folder picker, a theme click) overwrite the other's keys.
        return update_settings(settings or {})

    def choose_folder(self):
        try:
            folder_t, _, _ = _dialog_types()
            result = self.window.create_file_dialog(folder_t)
            if result:
                return result[0] if isinstance(result, (list, tuple)) else result
        except Exception as e:
            logger.error("Folder dialog failed: %s", e)
        return None

    def choose_file(self):
        """Pick a file (used for the reader executable)."""
        try:
            _, open_t, _ = _dialog_types()
            result = self.window.create_file_dialog(open_t)
            if result:
                return result[0] if isinstance(result, (list, tuple)) else result
        except Exception as e:
            logger.error("File dialog failed: %s", e)
        return None

    def open_in_reader(self, path: str):
        """Open a book file in the configured reader (e.g. Readest)."""
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "File not found"}
        reader = (load_settings().get("reader_path") or "").strip()
        try:
            if reader:
                if not os.path.isfile(reader):
                    return {"ok": False, "error": "Reader executable not found - check Settings"}
                if sys.platform == "darwin" and reader.endswith(".app"):
                    subprocess.Popen(["open", "-a", reader, path])
                else:
                    subprocess.Popen([reader, path])
            else:
                # fall back to system default handler
                if sys.platform == "win32":
                    os.startfile(path)  # noqa: S606
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_folder(self, path: str):
        if not path or not os.path.isdir(path):
            return False
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception:
            return False

    # --------------------------------------------------------- download

    @staticmethod
    def _as_int(value, default, low=None, high=None):
        """Coerce a UI value to int, clamping. Never raises.

        Values arrive from JavaScript, where a cleared field is "" and a
        stale handler can send a string. int("abc") used to escape all the
        way out of _spawn() and kill the worker thread.
        """
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            number = int(default)
        if low is not None:
            number = max(low, number)
        if high is not None:
            number = min(high, number)
        return number

    @staticmethod
    def _as_float(value, default, low=None, high=None):
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float(default)
        if low is not None:
            number = max(low, number)
        if high is not None:
            number = min(high, number)
        return number

    def _build_options(self, options: dict):
        """Turn a raw options dict from JS into validated DownloadOptions."""
        settings = load_settings()
        selection = options.get("selection")
        if not selection and options.get("chapters"):
            selection = options.get("chapters")
        if not selection:
            selection = "all"

        fmt = options.get("format") or settings.get("format", "cbz")
        output_dir = options.get("output_dir") or settings.get("output_dir") or DEFAULT_SETTINGS["output_dir"]

        opt = DownloadOptions(
            url=options.get("url", ""),
            selection=selection,
            output_dir=output_dir,
            format=fmt,
            bundle=self._as_int(options.get("bundle"), 0, 0),
            chapter_workers=self._as_int(options.get("chapter_workers"), 3, 1, 8),
            image_workers=self._as_int(options.get("image_workers"), 6, 1, 10),
            delay=self._as_float(options.get("delay"), 0.5, 0.0, 60.0),
            retries=self._as_int(options.get("retries"), 5, 1, 10),
            keep_images=bool(options.get("keep_images", False)),
            extra_formats=list(options.get("extra_formats", []) or []),
            name_single=options.get("name_single") or DEFAULT_SETTINGS["name_single"],
            name_chapter=options.get("name_chapter") or DEFAULT_SETTINGS["name_chapter"],
            name_range=options.get("name_range") or DEFAULT_SETTINGS["name_range"],
            source=options.get("source") or "",
            language=options.get("language") or settings.get("language", "en"),
            scanlator=options.get("scanlator") or settings.get("scanlator", ""),
            data_saver=bool(options.get("data_saver",
                                        settings.get("data_saver", False))),
        )
        if opt.format == "images":
            opt.keep_images = True
        return opt

    def max_concurrent_jobs(self):
        """How many manga may download at the same time."""
        try:
            value = int(load_settings().get("max_concurrent_jobs", 2) or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, min(5, value))

    def _active_jobs(self):
        return [j for j in self._jobs.values() if j["status"] == "running"]

    def _job_event(self, job_id):
        """An on_event callback that stamps every event with its job id.

        Without this the UI cannot tell two concurrent downloads apart:
        chapter names are not unique across manga, so "Chapter 01" from one
        series was overwriting "Chapter 01" from another.
        """
        def emit(event):
            record = self._jobs.get(job_id)
            event = dict(event)
            event["job"] = job_id
            if record:
                event.setdefault("job_title", record.get("title") or "")
            self._push(event)
        return emit

    def _run_job(self, job_id):
        """Body of a download thread."""
        record = self._jobs.get(job_id)
        if record is None:
            return
        engine = record["engine"]
        push = self._job_event(job_id)
        try:
            result = engine.run()
            with self._jobs_lock:
                # A user-requested stop is not a failure -- reporting it as
                # one made a deliberate cancel look like a broken download.
                if result.get("stopped"):
                    record["status"] = "stopped"
                elif result.get("ok"):
                    record["status"] = "done"
                else:
                    record["status"] = "failed"
                record["result"] = result
                if result.get("title"):
                    record["title"] = result["title"]
            push({"type": "finished", "result": result})
            self._notify_finished(record, result)
        except Exception as e:
            logger.exception("Download crashed")
            with self._jobs_lock:
                record["status"] = "failed"
                record["result"] = {"ok": False, "error": str(e)}
            push({"type": "error", "message": str(e)})
            push({"type": "finished", "result": {"ok": False, "error": str(e)}})
        finally:
            self._start_queued()

    def _notify_finished(self, record, result):
        """Desktop notification when a download ends, if the tray is up."""
        tray = getattr(self, "_tray", None)
        if tray is None:
            return
        try:
            if not load_settings().get("tray_notifications", True):
                return
            title = record.get("title") or "Download"
            if result.get("stopped"):
                return                      # the user asked for it; stay quiet
            if result.get("ok"):
                count = result.get("downloaded", 0)
                tray.notify(f"{title} - {count} chapter"
                            f"{'s' if count != 1 else ''} downloaded")
            else:
                tray.notify(f"{title} - download failed")
        except Exception:
            logger.debug("tray notification failed", exc_info=True)

    def _spawn(self, entry):
        """Start one queued cart entry immediately. Caller holds the lock."""
        self._job_seq += 1
        job_id = f"job{self._job_seq}"
        opt = self._build_options(entry["options"])

        # Share the job id so readerm.progress tracks each concurrent job
        # separately, and so the crash journal writes one file per job.
        engine = DownloadEngine(opt, on_event=self._job_event(job_id),
                                job_id=job_id)
        from ..progress import REGISTRY
        REGISTRY.job(job_id, entry.get("title") or opt.url)
        record = {
            "id": job_id,
            "title": entry.get("title") or opt.url,
            "url": opt.url,
            "source": opt.source or "",
            "cover": entry.get("cover") or "",
            "selection": opt.selection,
            "status": "running",
            "engine": engine,
            "result": None,
            "started": time.time(),
        }
        self._jobs[job_id] = record
        self.engine = engine          # back-compat for stop_download()

        thread = threading.Thread(target=self._run_job, args=(job_id,),
                                  daemon=True, name=f"readerm-{job_id}")
        record["thread"] = thread
        self._thread = thread
        thread.start()

        self._push({"type": "job_started", "job": job_id,
                    "title": record["title"], "url": record["url"],
                    "cover": record["cover"], "source": record["source"]})
        return record

    def _start_queued(self):
        """Promote cart entries into running jobs while slots are free.

        A malformed entry is dropped with an error event rather than allowed
        to raise: this runs in the finally of a finished job's thread, so an
        escaping exception killed that thread and stalled the whole queue.
        """
        started = []
        with self._jobs_lock:
            if getattr(self, "_queue_paused", False):
                return started
            limit = self.max_concurrent_jobs()
            while self._cart and len(self._active_jobs()) < limit:
                entry = self._cart.pop(0)
                try:
                    started.append(self._spawn(entry))
                except Exception as e:
                    logger.exception("Could not start a queued download")
                    title = entry.get("title") or (
                        entry.get("options") or {}).get("url") or "download"
                    self._push({"type": "error",
                                "message": f"Could not start {title}: {e}"})
        if started:
            self._flush()
        self._sync_progress_queue()
        return started

    def _sync_progress_queue(self):
        """Publish the waiting-job count for the tray menu."""
        try:
            from ..progress import REGISTRY
            REGISTRY.set_queued(len(self._cart))
        except Exception:
            logger.debug("could not publish queue depth", exc_info=True)

    # ------------------------------------------------------------- cart

    def add_to_cart(self, options: dict):
        """Queue a manga for download. Starts at once if a slot is free."""
        options = options or {}
        url = (options.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "No manga URL"}

        entry = {
            "options": options,
            "title": options.get("title") or "",
            "cover": options.get("cover") or "",
        }
        with self._jobs_lock:
            # Refuse an exact duplicate that is already queued or running.
            for job in self._jobs.values():
                if job.get("url") == url and job.get("status") in ("running", "queued"):
                    return {"ok": False, "error": "Already downloading",
                            "job": job.get("id")}
            for queued in self._cart:
                if (queued.get("options", {}).get("url") or "").strip() == url:
                    return {"ok": False, "error": "Already in the cart"}
            self._cart.append(entry)

        self._start_queued()
        return {"ok": True, "queued": len(self._cart),
                "active": len(self._active_jobs())}

    # -------------------------------------------------------- tray api

    def get_progress(self):
        """Live throughput for the tray menu and the downloads panel.

        Speed, ETA and queue depth were not measured anywhere before v1.4.19
        -- the engine only totalled bytes after a job finished.
        """
        from ..progress import REGISTRY
        self._sync_progress_queue()
        summary = REGISTRY.summary()
        summary["paused"] = bool(getattr(self, "_queue_paused", False))
        return {"ok": True, **summary}

    def set_queue_paused(self, paused: bool = None):
        """Pause or resume starting new jobs.

        Deliberately does not interrupt a running download -- stopping one
        mid-chapter would throw away partial work that resume could reuse.
        """
        with self._jobs_lock:
            if paused is None:
                paused = not getattr(self, "_queue_paused", False)
            self._queue_paused = bool(paused)
        if not self._queue_paused:
            self._start_queued()
        return {"ok": True, "paused": self._queue_paused}

    # ------------------------------------------------- FlareSolverr

    def flaresolverr_test(self, url: str = None):
        """Test connection to FlareSolverr server."""
        import requests
        from ..config import load_settings
        target_url = (url or load_settings().get("flaresolverr_url") or "http://localhost:8191/v1").strip()
        try:
            resp = requests.post(target_url, json={"cmd": "sessions.list"}, timeout=4.0)
            if resp.status_code == 200:
                data = resp.json()
                return {"ok": True, "status": "connected", "url": target_url, "version": data.get("version", "v3"), "message": "Connected to FlareSolverr successfully."}
            return {"ok": False, "status": "error", "message": f"FlareSolverr returned status {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "status": "offline", "message": f"Could not connect to FlareSolverr: {e}"}

    def flaresolverr_status(self):
        """Get FlareSolverr configuration and connectivity state."""
        from ..config import load_settings
        url = load_settings().get("flaresolverr_url") or "http://localhost:8191/v1"
        test_res = self.flaresolverr_test(url)
        return {"ok": True, "url": url, "connected": bool(test_res.get("ok")), "status": test_res.get("status", "offline"), "message": test_res.get("message", "")}

    def set_flaresolverr_config(self, url: str = None, enabled: bool = None):
        """Save FlareSolverr settings."""
        from ..config import update_settings
        changes = {}
        if url is not None:
            changes["flaresolverr_url"] = str(url).strip()
        if enabled is not None:
            changes["flaresolverr_enabled"] = bool(enabled)
        if changes:
            update_settings(changes)
        return self.flaresolverr_status()

    # ------------------------------------------------- LAN Web Server

    def get_server_config(self):
        """Token, port, link, status, and connected devices for LAN Web Server."""
        from ..servercfg import MIN_TOKEN_LENGTH, load_server_settings

        cfg = load_server_settings()
        settings = load_settings()
        port = int(self._server_port or cfg['port'])
        try:
            from .. import server as server_module
            host_ip = server_module.local_ip()
            ts_ip = server_module.tailscale_ip()
        except Exception:
            host_ip = "127.0.0.1"
            ts_ip = None

        url = f"http://{host_ip}:{port}/?token={cfg['token']}"
        local_url = f"http://localhost:{port}/?token={cfg['token']}"
        ts_url = f"http://{ts_ip}:{port}/?token={cfg['token']}" if ts_ip else ""

        is_running = bool(self._server_thread and self._server_thread.is_alive())
        now = time.time()
        uptime_sec = int(now - self._server_start_time) if (is_running and self._server_start_time > 0) else 0

        from ..devices import tracker
        active_devs = tracker.active_count(service="web")
        total_devs = tracker.total_count(service="web")
        dev_list = tracker.get_devices(service="web")

        return {
            "ok": True,
            "min_length": MIN_TOKEN_LENGTH,
            "running": is_running,
            "port": port,
            "url": url,
            "local_url": local_url,
            "tailscale_ip": ts_ip or "",
            "tailscale_url": ts_url,
            "host_ip": host_ip,
            "uptime": _format_uptime(uptime_sec),
            "uptime_seconds": uptime_sec,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._server_start_time)) if self._server_start_time > 0 else "",
            "autostart": bool(settings.get("server_autostart")),
            "active_devices_count": active_devs,
            "total_devices_count": total_devs,
            "devices": dev_list,
            "token": cfg.get("token", ""),
            "verbose": cfg.get("verbose", False),
        }

    def set_server_config(self, token: str = None, port=None, verbose=None, autostart=None):
        """Validated through the same helper the server window uses."""
        from ..servercfg import save_server_settings

        ok, message, cfg = save_server_settings(token=token, port=port,
                                                verbose=verbose)
        if autostart is not None:
            update_settings({"server_autostart": bool(autostart)})
        result = self.get_server_config() if ok else {}
        return {"ok": ok, "message": message, **(result or {})}

    def generate_server_token(self):
        from ..servercfg import generate_token, save_server_settings

        token = generate_token()
        save_server_settings(token=token)
        return {"ok": True, "token": token, **self.get_server_config()}

    def start_server(self, port=None, token=None, no_auth=False):
        """Start the LAN Web Server on a background thread."""
        if self._server_thread and self._server_thread.is_alive():
            return {"ok": True, "already": True, **self.get_server_config()}

        from .. import server as server_module
        from ..servercfg import load_server_settings

        cfg = load_server_settings()
        p = int(port or cfg["port"])
        t = (token or cfg["token"]) if not no_auth else None

        self._server_port = p
        self._server_log = server_module.ServerLog(verbose=bool(cfg.get("verbose")))
        self._server_instance = {}
        self._server_start_time = time.time()

        def run():
            try:
                server_module.serve(
                    host="0.0.0.0",
                    port=p,
                    token=t,
                    no_auth=no_auth,
                    log=self._server_log,
                    server_instance_holder=self._server_instance,
                )
            except Exception:
                logger.exception("LAN server stopped unexpectedly")
            finally:
                self._server_thread = None
                self._server_instance = None
                self._server_port = None
                self._server_start_time = 0.0

        thread = threading.Thread(target=run, name="readerm-lan-server", daemon=True)
        self._server_thread = thread
        thread.start()
        logger.info("LAN server starting on port %s", p)
        time.sleep(0.15)
        return {"ok": True, **self.get_server_config()}

    def stop_server(self):
        """Stop the LAN Web Server gracefully."""
        if not (self._server_thread and self._server_thread.is_alive()):
            self._server_thread = None
            self._server_instance = None
            self._server_port = None
            self._server_start_time = 0.0
            return {"ok": True, "stopped": True, **self.get_server_config()}

        try:
            if self._server_instance and self._server_instance.get("server"):
                srv = self._server_instance["server"]
                srv.shutdown()
                if hasattr(srv, "server_close"):
                    srv.server_close()
        except Exception:
            logger.exception("Error during LAN server shutdown")

        if self._server_thread:
            self._server_thread.join(timeout=1.5)
            self._server_thread = None

        self._server_instance = None
        self._server_port = None
        self._server_start_time = 0.0
        logger.info("LAN server stopped")
        return {"ok": True, "stopped": True, **self.get_server_config()}

    def restart_server(self, port=None, token=None, no_auth=False):
        """Restart the LAN Web Server."""
        self.stop_server()
        time.sleep(0.2)
        return self.start_server(port=port, token=token, no_auth=no_auth)

    # ------------------------------------------------- OPDS catalog

    def get_opds_config(self):
        """Catalog settings and its URL, for the Settings panel."""
        from ..opdsserve import build_url, opds_port
        from ..servercfg import load_server_settings

        settings = load_settings()
        cfg = load_server_settings()
        port = int(self._opds_port or opds_port())

        try:
            from .. import server as server_module
            host_ip = server_module.local_ip()
            ts_ip = server_module.tailscale_ip()
        except Exception:
            host_ip = "127.0.0.1"
            ts_ip = None

        is_running = bool(self._opds_thread and self._opds_thread.is_alive())
        now = time.time()
        uptime_sec = int(now - self._opds_start_time) if (is_running and self._opds_start_time > 0) else 0

        from .. import opds
        try:
            titles_count = len(opds.library_rows())
        except Exception:
            titles_count = 0

        from ..devices import tracker
        active_devs = tracker.active_count(service="opds")
        total_devs = tracker.total_count(service="opds")
        dev_list = tracker.get_devices(service="opds")

        url = build_url(host_ip, port)
        local_url = f"http://localhost:{port}/opds"
        ts_url = f"http://{ts_ip}:{port}/opds" if ts_ip else ""

        return {
            "ok": True,
            "port": port,
            "autostart": bool(settings.get("opds_autostart")),
            "cover_root": settings.get("opds_cover_root") or "",
            "token": cfg["token"],
            "running": is_running,
            "url": url,
            "local_url": local_url,
            "tailscale_ip": ts_ip or "",
            "tailscale_url": ts_url,
            "host_ip": host_ip,
            "titles_count": titles_count,
            "uptime": _format_uptime(uptime_sec),
            "uptime_seconds": uptime_sec,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._opds_start_time)) if self._opds_start_time > 0 else "",
            "active_devices_count": active_devs,
            "total_devices_count": total_devs,
            "devices": dev_list,
        }

    def set_opds_config(self, port=None, autostart=None, cover_root=None):
        changes = {}
        if port is not None:
            try:
                value = int(port)
            except (TypeError, ValueError):
                return {"ok": False, "message": "Port must be a number."}
            if not (1024 <= value <= 65535):
                return {"ok": False,
                        "message": "Use 1024-65535; lower ports need admin "
                                   "rights."}
            changes["opds_port"] = value
        if autostart is not None:
            changes["opds_autostart"] = bool(autostart)
        if cover_root is not None:
            changes["opds_cover_root"] = str(cover_root)
        if changes:
            update_settings(changes)
        return {"ok": True, "message": "Saved.", **self.get_opds_config()}

    def start_opds(self, port=None):
        """Start the OPDS catalog on a background thread."""
        if self._opds_thread and self._opds_thread.is_alive():
            return {"ok": True, "already": True, **self.get_opds_config()}

        from ..opdsserve import OpdsLog, opds_port, serve
        from ..servercfg import load_server_settings

        p = int(port or opds_port())
        log = OpdsLog(verbose=bool(load_settings().get("server_verbose")))
        self._opds_log = log
        self._opds_port = p
        token = load_server_settings()["token"]
        self._opds_instance = {}
        self._opds_start_time = time.time()

        def run():
            try:
                serve(
                    host="0.0.0.0",
                    port=p,
                    token=token,
                    log=log,
                    server_instance_holder=self._opds_instance,
                )
            except Exception:
                logger.exception("OPDS catalog stopped unexpectedly")
            finally:
                self._opds_thread = None
                self._opds_instance = None
                self._opds_port = None
                self._opds_start_time = 0.0

        thread = threading.Thread(target=run, name="readerm-opds", daemon=True)
        self._opds_thread = thread
        thread.start()
        logger.info("OPDS catalog starting on port %s", p)
        time.sleep(0.15)
        return {"ok": True, **self.get_opds_config()}

    def stop_opds(self):
        """Stop the OPDS catalog gracefully."""
        if not (self._opds_thread and self._opds_thread.is_alive()):
            self._opds_thread = None
            self._opds_instance = None
            self._opds_port = None
            self._opds_start_time = 0.0
            return {"ok": True, "stopped": True, **self.get_opds_config()}

        try:
            if self._opds_instance and self._opds_instance.get("server"):
                srv = self._opds_instance["server"]
                srv.shutdown()
                if hasattr(srv, "server_close"):
                    srv.server_close()
        except Exception:
            logger.exception("Error during OPDS catalog shutdown")

        if self._opds_thread:
            self._opds_thread.join(timeout=1.5)
            self._opds_thread = None

        self._opds_instance = None
        self._opds_port = None
        self._opds_start_time = 0.0
        logger.info("OPDS catalog stopped")
        return {"ok": True, "stopped": True, **self.get_opds_config()}

    def restart_opds(self, port=None):
        """Restart the OPDS catalog."""
        self.stop_opds()
        time.sleep(0.2)
        return self.start_opds(port=port)

    # ------------------------------------------------- Combined Server & Device APIs

    def get_servers_status(self):
        """Get comprehensive live status of both LAN Server and OPDS Catalog,

        including connected devices, uptime, URLs, and active reader counts.
        """
        from ..devices import tracker
        from .. import server as server_module
        try:
            host_ip = server_module.local_ip()
            ts_ip = server_module.tailscale_ip()
        except Exception:
            host_ip = "127.0.0.1"
            ts_ip = None

        server_status = self.get_server_config()
        opds_status = self.get_opds_config()
        all_devices = tracker.get_devices()
        active_count = tracker.active_count()
        total_count = tracker.total_count()

        return {
            "ok": True,
            "host_ip": host_ip,
            "tailscale_ip": ts_ip or "",
            "server": server_status,
            "opds": opds_status,
            "any_running": bool(server_status.get("running") or opds_status.get("running")),
            "both_running": bool(server_status.get("running") and opds_status.get("running")),
            "devices": all_devices,
            "total_active_devices": active_count,
            "total_devices": total_count,
        }

    def get_server_devices(self, service: str = None, active_only: bool = False):
        """Return list of registered client devices accessing LAN server or OPDS."""
        from ..devices import tracker
        devs = tracker.get_devices(service=service, active_only=bool(active_only))
        return {
            "ok": True,
            "devices": devs,
            "active_count": tracker.active_count(service=service),
            "total_count": tracker.total_count(service=service),
        }

    def clear_server_devices(self, inactive_only: bool = True):
        """Clear disconnected or all client devices from tracker registry."""
        from ..devices import tracker
        if inactive_only:
            removed = tracker.clear_inactive(max_idle=180.0)
        else:
            tracker.clear_all()
            removed = 0
        return {"ok": True, "removed": removed, **self.get_server_devices()}

    def get_server_logs(self, service: str = "all", since: int = 0):
        """Retrieve recent server and OPDS log lines for GUI display."""
        try:
            since = int(since)
        except (TypeError, ValueError):
            since = 0

        lines = []
        s_cursor = 0
        o_cursor = 0

        if service in ("all", "server"):
            s_log = getattr(self, "_server_log", None)
            if not s_log:
                from ..server import GLOBAL_SERVER_LOG
                s_log = GLOBAL_SERVER_LOG
            if s_log:
                s_cursor, s_lines = s_log.since(since)
                for l in s_lines:
                    lines.append({**l, "service": "Web Server"})

        if service in ("all", "opds"):
            o_log = getattr(self, "_opds_log", None)
            if not o_log:
                from ..opdsserve import GLOBAL_OPDS_LOG
                o_log = GLOBAL_OPDS_LOG
            if o_log:
                o_cursor, o_lines = o_log.since(since)
                for l in o_lines:
                    lines.append({**l, "service": "OPDS"})

        lines.sort(key=lambda x: x.get("seq", 0))
        max_cursor = max(s_cursor, o_cursor, since)
        return {"ok": True, "cursor": max_cursor, "lines": lines}

    def preview_opds_covers(self, root: str = None, overwrite: bool = False):
        from .. import covers as covers_mod

        root = root or load_settings().get("opds_cover_root") \
            or load_settings().get("output_dir") or ""
        rows = covers_mod.scan_image_folders(root, overwrite=bool(overwrite))
        return {"ok": True, "root": root, "count": len(rows),
                "folders": [{"directory": r["directory"],
                             "images": r["count"]} for r in rows[:200]]}

    def apply_opds_covers(self, root: str = None, overwrite: bool = False,
                          source: str = "first"):
        from .. import covers as covers_mod

        root = root or load_settings().get("opds_cover_root") \
            or load_settings().get("output_dir") or ""
        result = covers_mod.propagate_covers(root, overwrite=bool(overwrite),
                                             source=source)
        return {"ok": True, "root": root,
                "created": len(result["created"]),
                "failed": len(result["failed"])}

    def set_folder_cover(self, directory: str, image_path: str):
        from .. import covers as covers_mod

        return covers_mod.set_cover(directory, image_path)

    def get_tray_state(self):
        from ..tray import tray_available

        return {"ok": True,
                "available": tray_available(),
                "enabled": bool(load_settings().get("minimize_to_tray")),
                "running": getattr(self, "_tray", None) is not None}

    def get_cart(self):
        """Everything queued or running, for the downloads panel."""
        with self._jobs_lock:
            jobs = [{
                "id": j["id"], "title": j["title"], "url": j["url"],
                "source": j["source"], "cover": j["cover"],
                "selection": j["selection"], "status": j["status"],
            } for j in self._jobs.values()]
            queued = [{
                "title": q.get("title") or q["options"].get("url"),
                "url": q["options"].get("url"),
                "cover": q.get("cover", ""),
                "selection": q["options"].get("selection", "all"),
                "status": "queued",
            } for q in self._cart]
        return {"ok": True, "jobs": jobs, "queued": queued,
                "limit": self.max_concurrent_jobs()}

    def remove_from_cart(self, url: str, selection: str = None):
        """Drop a not-yet-started entry from the queue."""
        with self._jobs_lock:
            before = len(self._cart)
            self._cart = [
                q for q in self._cart
                if not (q["options"].get("url") == url
                        and (selection is None
                             or q["options"].get("selection", "all") == selection))
            ]
            removed = before - len(self._cart)
        return {"ok": True, "removed": removed}

    def clear_cart(self):
        with self._jobs_lock:
            count = len(self._cart)
            self._cart = []
        return {"ok": True, "removed": count}

    def download_list(self, list_url: str, format: str = None, output_dir: str = None):
        """Bulk enqueue and download all chapters from every manga in a curated list."""
        if not list_url:
            return {"ok": False, "error": "No list URL provided"}

        src = self._source("chikari")
        if not hasattr(src, "get_list_series"):
            return {"ok": False, "error": "List downloading not supported for this source"}

        list_data = src.get_list_series(list_url)
        series_items = list_data.get("series") or []
        if not series_items:
            return {"ok": False, "error": "No series found in list"}

        enqueued = 0
        settings = load_settings()
        chosen_format = format or settings.get("format") or "cbz"
        out = output_dir or settings.get("output_dir")

        for s in series_items:
            res = self.add_to_cart({
                "url": s["url"],
                "title": s["title"],
                "cover": s.get("cover") or "",
                "source": s.get("source") or "chikari",
                "format": chosen_format,
                "output_dir": out,
                "selection": "all",
            })
            if res.get("ok"):
                enqueued += 1

        self.set_queue_paused(False)
        return {
            "ok": True,
            "title": list_data.get("title"),
            "total_series": len(series_items),
            "enqueued": enqueued,
        }

    # --------------------------------------------------------- download

    def start_download(self, options: dict):
        """Start a download.

        Kept as the single-job entry point the UI has always used. It now
        routes through the cart so several manga can run at once, and
        returns the job id so the caller can track this one specifically.
        """
        options = options or {}
        url = (options.get("url") or "").strip()
        if not url:
            return {"ok": False, "error": "No manga URL"}

        with self._jobs_lock:
            # Check if this URL is already actively running or queued to prevent duplicate downloads
            for job in self._jobs.values():
                if job.get("url") == url and job.get("status") in ("running", "queued"):
                    logger.info("Download for %s is already running (%s)", url, job.get("id"))
                    return {"ok": False, "error": "Already downloading", "job": job.get("id")}
            for q in self._cart:
                if (q.get("options", {}).get("url") or "").strip() == url:
                    logger.info("Download for %s is already in queue", url)
                    return {"ok": False, "error": "Already in the queue"}

            if len(self._active_jobs()) >= self.max_concurrent_jobs():
                self._cart.append({
                    "options": options,
                    "title": options.get("title") or "",
                    "cover": options.get("cover") or "",
                })
                return {"ok": True, "queued": True,
                        "position": len(self._cart)}
            record = self._spawn({
                "options": options,
                "title": options.get("title") or "",
                "cover": options.get("cover") or "",
            })
        return {"ok": True, "job": record["id"]}

    def stop_download(self, job_id: str = None):
        """Stop one job, or every running job when no id is given."""
        with self._jobs_lock:
            if job_id:
                targets = [self._jobs[job_id]] if job_id in self._jobs else []
            else:
                targets = self._active_jobs()
                # a blanket stop should also empty the queue
                self._cart = []
            for job in targets:
                job["status"] = "stopping"

        for job in targets:
            try:
                job["engine"].stop()
            except Exception:
                logger.debug("Could not stop %s", job["id"], exc_info=True)

        self._flush()          # deliver whatever is queued before stopping
        return {"ok": True, "stopped": [j["id"] for j in targets]}

    def shutdown(self):
        """Cancel the pending flush timer so it cannot outlive the window."""
        with self._push_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
        for source in list(self._sources.values()):
            try:
                source.close()
            except Exception:
                pass
        self._sources.clear()
        return {"ok": True}


def _web_asset_path():
    """Locate the reader's index.html in source and in a PyInstaller bundle.

    The old hand-rolled front-end under ``gui/web`` was replaced in v3.0.0 by
    the Foliate-based reader in ``readerm/reader/app``; this resolves to that.
    """
    from ..reader.assets import ASSET_ROOT
    return os.path.join(ASSET_ROOT, "app", "index.html")


def _show_fatal(message: str):
    """Last-resort error reporting: console + native message box on Windows."""
    print("\n[Mangasurf] GUI failed to start:\n" + message, file=sys.stderr)
    print(f"\nLog file: {wclogs.LOG_FILE}\nCrash dumps: {wclogs.CRASH_FILE}",
          file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                message + f"\n\nDetails were written to:\n{wclogs.LOG_FILE}",
                "Mangasurf - startup error",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass


def _start_opds_server(api):
    """Run the OPDS catalog on a daemon thread inside the GUI process."""
    try:
        api.start_opds()
        return True
    except Exception:
        logger.exception("OPDS server start failed")
        return False


def _start_lan_server(api):
    """Run the LAN Web Server on a daemon thread inside the GUI process."""
    try:
        api.start_server()
        return True
    except Exception:
        logger.exception("LAN server start failed")
        return False


def _install_tray(api, window):
    """Start the tray icon when the setting is on and a tray exists.

    Returns the controller, or ``None`` -- in which case the window keeps its
    ordinary "close quits the app" behaviour. Never raises: a missing tray
    must not stop the GUI from starting.
    """
    try:
        if not load_settings().get("minimize_to_tray"):
            return None
        from ..tray import TrayController, tray_available
        if not tray_available():
            logger.info("Minimise-to-tray is on but no system tray is "
                        "available here; the window will close normally.")
            return None
    except Exception:
        logger.debug("tray setup skipped", exc_info=True)
        return None

    def show_window():
        try:
            if hasattr(window, "show"):
                window.show()
        except Exception:
            logger.debug("could not show the window", exc_info=True)
        try:
            if hasattr(window, "restore") and getattr(window, "minimized", False):
                window.restore()
        except Exception:
            logger.debug("could not restore the window", exc_info=True)
        # The window is back, so hiding it again is worth announcing once
        # more. Done here as well as on the "shown" event because not every
        # pywebview backend fires that event.
        api._hidden_to_tray = False
        try:
            controller.reset_notifications()
        except Exception:
            logger.debug("could not reset notification state", exc_info=True)

    def quit_app():
        api._really_quitting = True
        try:
            api.shutdown()
        except Exception:
            pass
        try:
            window.destroy()
        except Exception:
            logger.debug("window.destroy failed", exc_info=True)

    controller = TrayController(callbacks={
        "show_window": show_window,
        "quit_app": quit_app,
        "toggle_pause": lambda: api.set_queue_paused(),
        "is_paused": lambda: bool(getattr(api, "_queue_paused", False)),
        "summary": lambda: api.get_progress(),
    })

    if not controller.start():
        logger.warning("The system tray could not be started; the window "
                       "will close normally.")
        return None

    api._tray = controller

    # Hide instead of close, so downloads survive the window going away.
    def _on_closing():
        if getattr(api, "_really_quitting", False):
            return True                      # let it close for real
        # The toggle takes effect immediately: turning "minimise to tray"
        # off and closing the window used to still hide it, because this
        # handler captured the setting once at startup.
        try:
            if not load_settings().get("minimize_to_tray"):
                api._really_quitting = True
                return True
        except Exception:
            logger.debug("could not re-read the tray setting", exc_info=True)

        # Already hidden? Then this is a repeat of an event we have already
        # handled -- veto it and say nothing. Window managers deliver the
        # close event more than once (minimise/restore, a taskbar "Close
        # window", the backend-retry path below which closes the window once
        # per attempt), and this handler used to notify unconditionally
        # every time: measured, 20 close events produced 20 balloons in
        # 0.4s. That is the reported notification loop.
        if getattr(api, "_hidden_to_tray", False):
            return False

        try:
            window.hide()
        except Exception:
            # Hiding failed, so the window is about to close for real. Let
            # it -- but mark the app as quitting first, otherwise the main
            # thread would sit in wait_for_quit() holding an invisible
            # process open with no window and no way to reach it.
            logger.debug("window.hide failed", exc_info=True)
            api._really_quitting = True
            controller.stop()
            return True

        api._hidden_to_tray = True

        # Only claim downloads are continuing when some actually are.
        # Saying "Still downloading in the background" with an empty queue
        # is simply untrue, and it was the text shown every time.
        try:
            progress = api.get_progress() or {}
            busy = int(progress.get("active") or 0) + \
                int(progress.get("queued") or 0)
        except Exception:
            busy = 0
        message = ("Still downloading in the background."
                   if busy else "Mangasurf is still running in the tray.")
        # once=True: this is only news the first time the window is hidden.
        controller.notify(message, once=True)
        return False                         # veto the close

    def _on_shown():
        """The window is visible again, so a later hide is news once more."""
        api._hidden_to_tray = False
        try:
            controller.reset_notifications()
        except Exception:
            logger.debug("could not reset notification state", exc_info=True)

    try:
        window.events.closing += _on_closing
    except Exception:
        logger.debug("closing event unavailable; tray hide disabled",
                     exc_info=True)

    # Not every backend fires "shown", so show_window() clears the flag too
    # (see above); this is belt and braces for the ones that do.
    try:
        window.events.shown += _on_shown
    except Exception:
        logger.debug("shown event unavailable", exc_info=True)
    return controller


def _hold_for_tray(api, tray):
    """Keep the process alive after the window closes, while the tray lives.

    Only called once ``webview.start()`` has returned. Returns immediately
    unless a tray is actually running and the user has not quit, so the
    no-tray path is unchanged.
    """
    if tray is None:
        return
    if getattr(api, "_really_quitting", False) or tray.quit_requested():
        return

    def keep_holding():
        """Whether to keep the process alive.

        Only two things end the wait: **Quit**, or the tray icon dying. In
        particular an idle queue does NOT, and that was a real bug.

        v1.4.24 ended the wait as soon as nothing was downloading, reasoning
        that a tray which failed to draw an icon must not strand an
        invisible process. That conflated two different things -- "no
        downloads running" is not "nobody wants this app". Reproduced:
        closing to the tray with an empty queue tore the process down 0.74s
        later, and clicking *Open Mangasurf* showed the window for about a
        second before the shutdown that was already in flight killed it.
        That is the reported "opens for a quick second then disappears".

        The original worry is handled properly instead: ``_install_tray``
        only returns a controller when the icon actually started, so if we
        are here there IS a way to reach the app. If the icon later dies,
        ``wait_for_quit`` notices and returns on its own.
        """
        return not getattr(api, "_really_quitting", False)

    logger.info("Window closed; Mangasurf is still running in the system tray.")
    try:
        tray.wait_for_quit(still_working=keep_holding)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            api.shutdown()
        except Exception:
            logger.debug("shutdown after tray wait failed", exc_info=True)
        tray.stop()


def run_gui():
    wclogs.setup_logging()
    wclogs.quiet_pywebview()
    wclogs.enable_crash_dumps()

    # ------------------------------------------------- single instance
    # Claimed BEFORE pywebview is imported. Two reasons:
    #
    #  1. Nothing used to stop a second copy launching while the first sat
    #     hidden in the tray, and running it again is the obvious way to
    #     "reopen" it. Measured: three launches left three processes alive,
    #     three tray icons, and three download engines writing the same
    #     library and config files.
    #  2. Importing webview loads the .NET CLR on Windows, and doing that a
    #     second time in a process that already has a tray message loop is
    #     what the crash log shows dying:
    #         Windows fatal exception: access violation
    #           clr_loader/types.py __call__  ->  webview/platforms/winforms
    #     Refusing early means the duplicate never reaches that import.
    from ..singleton import InstanceServer

    instance = InstanceServer()
    if not instance.start():
        # Another Mangasurf answered; it has raised its own window.
        logger.info("Mangasurf is already running; asked it to come forward.")
        print("[Mangasurf] Already running - bringing the existing window to "
              "the front.")
        return 0

    try:
        import webview
    except ImportError:
        instance.stop()
        _show_fatal("pywebview is not installed. Run: pip install pywebview")
        return 1

    html_path = _web_asset_path()
    if not os.path.isfile(html_path):
        instance.stop()
        _show_fatal(f"Reader assets not found at:\n{html_path}\n\n"
                    "If this is a packaged exe, rebuild it with the provided "
                    "Mangasurf.spec so the reader is bundled.")
        return 1

    api = Api()

    # The reader is built out of ES modules, and browsers refuse those over
    # file:// -- measured in Chromium:
    #   "Access to script at 'file:///...' from origin 'null' has been blocked
    #    by CORS policy: Cross origin requests are only supported for protocol
    #    schemes: chrome, chrome-untrusted, data, http, https."
    # So the window is pointed at a loopback server instead of a path on disk.
    # It is bound to 127.0.0.1 and gated on a per-process token.
    try:
        target = api.reader_info()["url"]
    except Exception:
        instance.stop()
        logger.exception("reader asset server failed to start")
        _show_fatal("Could not start the local reader server:\n"
                    + traceback.format_exc(limit=3))
        return 1

    # A frameless window lets the app draw its own titlebar, so the window
    # controls follow the theme instead of sitting in an OS-coloured strip
    # above it. It is a setting rather than a decision: some Linux window
    # managers handle frameless badly, and there has to be a way back that
    # does not involve editing JSON by hand.
    chrome = bool(load_settings().get("custom_titlebar", True))
    try:
        window = webview.create_window(
            "Mangasurf",
            target,
            js_api=api,
            width=1180,
            height=780,
            min_size=(920, 620),
            background_color="#16161e",
            frameless=chrome,
            # Without this a frameless window cannot be moved at all: there
            # is no OS titlebar left to grab. The front-end marks the drag
            # region with `-webkit-app-region`, and easy_drag is the fallback
            # for backends that ignore it.
            easy_drag=chrome,
        )
    except Exception:
        instance.stop()
        logger.exception("create_window failed")
        _show_fatal("Could not create the application window:\n"
                    + traceback.format_exc(limit=3))
        return 1
    api.window = window

    def _on_loaded():
        # Remove the .NET bridge object pywebview injects on Windows.
        # We never use window.native, and Edge's accessibility/autofill
        # layer walks it recursively, which can flood the console and, in
        # the worst case, overflow the native stack and crash the process.
        try:
            window.evaluate_js(
                "try { delete window.native; window.native = undefined; } catch(e) {}"
            )
        except Exception:
            pass

    try:
        window.events.loaded += _on_loaded
    except Exception:
        pass

    # ------------------------------------------------------------- tray
    # With "minimize to tray" on, closing the window hides it and downloads
    # keep running; the app only exits from the tray's Quit item.
    #
    # DEFERRED until the GUI toolkit is up. The tray icon runs a Win32
    # message loop of its own, and the crash log shows what happens when
    # that loop already exists while pywebview loads the .NET CLR:
    #
    #     Windows fatal exception: access violation
    #       Thread ...: pystray/_win32.py _mainloop      <- tray already up
    #       Thread ...: readerm/tray.py loop
    #       Current  : clr_loader/types.py __call__      <- CLR loading
    #                  webview/platforms/winforms.py <module>
    #
    # That is a hard crash, not a catchable exception. Starting the tray
    # after the toolkit has initialised keeps the two message loops from
    # racing during CLR startup.
    tray = None

    def _start_tray_once():
        """Install the tray after the window is up. Idempotent."""
        nonlocal tray
        if tray is not None or getattr(api, "_tray_attempted", False):
            return
        api._tray_attempted = True
        tray = _install_tray(api, window)

    def _maybe_start_servers():
        """Start servers with the app if the user enabled autostart."""
        try:
            settings = load_settings()
            if settings.get("server_autostart"):
                _start_lan_server(api)
            if settings.get("opds_autostart"):
                _start_opds_server(api)
        except Exception:
            logger.debug("Server autostart failed", exc_info=True)

    try:
        # "shown" fires once the native window exists, which on Windows is
        # after the CLR is fully loaded.
        window.events.shown += _start_tray_once
        window.events.shown += _maybe_start_servers
    except Exception:
        logger.debug("shown event unavailable", exc_info=True)

    # Not every backend fires "shown". Without a fallback, "minimise to
    # tray" would silently do nothing on those -- closing the window would
    # quit the app with no icon left behind. A short timer is enough: it
    # only has to land after the toolkit has initialised, and by then the
    # window is either up or the whole start attempt has failed.
    def _tray_fallback():
        if getattr(api, "_tray_attempted", False):
            return
        logger.debug("no 'shown' event; starting the tray on the timer")
        _start_tray_once()

    threading.Timer(4.0, _tray_fallback).start()

    # If the window closes before either of those has fired -- a very fast
    # close, or a backend that fires neither event -- install it right then,
    # synchronously. By this point the toolkit is fully up, which is the
    # only ordering the CLR crash cares about, and it means "minimise to
    # tray" cannot be lost to a race with the user's own click.
    def _on_closing_pre():
        try:
            if load_settings().get("minimize_to_tray"):
                _start_tray_once()
        except Exception:
            logger.debug("late tray install failed", exc_info=True)
        return True          # never veto here; _install_tray's handler does

    try:
        window.events.closing += _on_closing_pre
    except Exception:
        logger.debug("closing event unavailable for the late tray install",
                     exc_info=True)

    # Launching Mangasurf again is the natural way to "reopen" a window that
    # is hidden in the tray, so make that gesture do exactly that instead of
    # starting a second copy.
    def _surface():
        try:
            if hasattr(window, "show"):
                window.show()
        except Exception:
            logger.debug("could not surface the window", exc_info=True)
        try:
            if hasattr(window, "restore") and getattr(window, "minimized", False):
                window.restore()
        except Exception:
            pass
        api._hidden_to_tray = False
        if tray is not None:
            try:
                tray.reset_notifications()
            except Exception:
                pass

    instance.on_show = _surface

    # Release the flush timer, cached sessions and sockets on close, so a
    # closing window cannot leave background threads alive.
    def _on_closed():
        """Release background resources when the window closes.

        pywebview collects handler return values into a *set*, so a handler
        that returns a dict raises "unhashable type: 'dict'". This wrapper
        swallows the return value; api.shutdown() stays dict-returning for
        the JS bridge, which expects one.
        """
        # When the tray is holding the app open, the window closing is not
        # the app closing -- tearing down sessions here would break the
        # downloads the tray exists to keep running.
        if tray is not None and not getattr(api, "_really_quitting", False):
            return
        try:
            api.shutdown()
        except Exception:
            logger.debug("shutdown handler failed", exc_info=True)
        if tray is not None:
            tray.stop()

    try:
        window.events.closed += _on_closed
    except Exception:
        pass

    # Try the default backend first; on failure retry with alternatives so a
    # broken/outdated runtime (e.g. WebView2) doesn't kill the app outright.
    if sys.platform == "win32":
        backends = [None, "edgechromium", "mshtml"]
    elif sys.platform == "darwin":
        backends = [None, "cocoa"]
    else:
        backends = [None, "gtk", "qt"]

    last_error = None
    for backend in backends:
        try:
            if backend is None:
                webview.start(debug=False)
            else:
                logger.warning("Retrying GUI with '%s' backend", backend)
                webview.start(debug=False, gui=backend)
            # webview.start() has returned: the GUI loop is over. If the tray
            # is meant to be holding the app open, this is where the process
            # would otherwise die -- every worker thread, and the tray icon
            # thread itself, is a daemon. Measured before this: the process
            # exited 0.06s after the loop returned, taking the downloads with
            # it, which is what "closing to tray still ends the process"
            # looked like. Block the main thread until Quit instead.
            _hold_for_tray(api, tray)
            instance.stop()
            return 0
        except Exception as e:
            last_error = e
            logger.exception("webview.start failed (backend=%s)", backend)
            # Only the FIRST backend attempt may import a fresh GUI toolkit.
            # On Windows the crash log shows the .NET CLR being loaded a
            # second time inside a process that already has a tray message
            # loop, and that is an access violation -- a hard crash, not an
            # exception we could catch:
            #     clr_loader/types.py __call__
            #     webview/platforms/winforms.py <module>
            # Retrying another backend after a failed import is what walks
            # into it, so on Windows we stop after the first failure.
            if sys.platform == "win32":
                break

    instance.stop()
    _show_fatal(
        "The embedded browser engine could not start.\n\n"
        f"Last error: {last_error}\n\n"
        "On Windows this usually means the Microsoft Edge WebView2 Runtime "
        "is missing or outdated - install it from:\n"
        "https://developer.microsoft.com/microsoft-edge/webview2/\n"
        "then restart the app."
    )
    return 1
