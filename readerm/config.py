"""Application configuration, stored at ``~/.readerm/config.json``.

The file has two top-level sections::

    {
      "settings": { "theme": "midnight", "output_dir": "...", ... },
      "sources":  { "mangadex": {"enabled": true, "rank": 0, ...}, ... }
    }

``settings`` holds the app-wide preferences the GUI/TUI share. ``sources``
holds the per-source ranking and exclusion described below.

Both are read and written through one lock and one atomic write. Settings
used to live in a separate ``settings.json`` that was written with a plain
``open(...,"w")`` and no lock, which lost data two ways: an interrupted write
left truncated JSON that ``load`` silently replaced with defaults, and two
concurrent saves clobbered each other's read-modify-write. Measured on the
old code, four threads saving at once destroyed the theme, accent and output
directory in 5 out of 5 runs. An existing ``settings.json`` is migrated in
automatically on first read.

Per-source configuration
------------------------

Every source gets an entry:

    {
      "sources": {
        "mangadex":    {"enabled": true,  "rank": 0, "weight": 1.0, ...},
        "mangakatana": {"enabled": true,  "rank": 1, ...},
        "natomanga":   {"enabled": false, "rank": 2, ...}
      }
    }

``rank`` drives ordering in merged search results (lower = higher priority) and
is what the GUI's drag-and-drop list writes back. ``enabled: false`` removes a
site from searches entirely while still allowing a direct URL to be opened, so
you can exclude a site from discovery without losing the ability to use a link
someone sends you. ``search_enabled`` is the softer variant: keep the source
usable but leave it out of "all sources" searches.
"""
import sys

# Allow running this file directly (python readerm/config.py, or an IDE's
# "Run file"). Without this the relative imports below have no parent package
# and raise ImportError before the module can do anything.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"



import json
import os
import threading

from .sources import SOURCES

from .paths import ensure as _ensure_data_dir

#: Created on first use, and populated from a MangaDL install if one
#: exists -- see readerm.paths.migrate.
DIR = _ensure_data_dir()
CONFIG_PATH = os.path.join(DIR, "config.json")

_lock = threading.RLock()

# Defaults applied to any source that has no saved entry yet.
SOURCE_DEFAULTS = {
    "enabled": True,          # false = excluded everywhere except direct URLs
    "search_enabled": True,   # false = excluded from multi-source search only
    "rank": 100,              # lower sorts first in merged results
    "weight": 1.0,            # score multiplier when merging duplicates
    "limit": 0,               # per-source result cap, 0 = use the caller's
    "language": "",           # override translation language (MangaDex)
    "delay": 0.0,             # extra politeness delay, 0 = source default
    "note": "",               # free-text user note
}


#: App-wide preferences. The GUI owns the canonical defaults and passes them
#: in, so this module does not need to know every key the UI invents.
_SETTINGS_DEFAULTS = {}


def register_settings_defaults(defaults: dict) -> None:
    """Tell this module the full set of known settings keys."""
    _SETTINGS_DEFAULTS.clear()
    _SETTINGS_DEFAULTS.update(defaults or {})


#: Old standalone settings file, migrated on first read.
LEGACY_SETTINGS_PATH = os.path.join(DIR, "settings.json")


def _migrate_legacy_settings(data: dict) -> bool:
    """Fold a pre-1.4.11 settings.json into the config. True if it changed."""
    if data.get("settings"):
        return False
    try:
        with open(LEGACY_SETTINGS_PATH, encoding="utf-8") as f:
            legacy = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(legacy, dict) or not legacy:
        return False
    data["settings"] = legacy
    return True


def load_settings(defaults: dict = None) -> dict:
    """Every app setting, defaults backfilled."""
    base = dict(defaults if defaults is not None else _SETTINGS_DEFAULTS)
    with _lock:
        data = _load_raw()
        if _migrate_legacy_settings(data):
            _save_raw(data)
        stored = data.get("settings")
        if isinstance(stored, dict):
            base.update(stored)
        return base


def save_settings(settings: dict) -> dict:
    """Replace the settings section wholesale."""
    with _lock:
        data = _load_raw()
        _migrate_legacy_settings(data)
        data["settings"] = dict(settings or {})
        _save_raw(data)
        return data["settings"]


def update_settings(changes: dict, defaults: dict = None) -> dict:
    """Merge ``changes`` into the stored settings under one lock.

    Read-modify-write has to happen inside the lock or two callers racing --
    the Save button and an auto-save such as the download folder picker --
    each write a copy of the state they read, and whichever lands last wipes
    the other's change.
    """
    with _lock:
        current = load_settings(defaults)
        current.update(changes or {})
        return save_settings(current)


def _default_config() -> dict:
    return {
        "sources": {
            source_id: {**SOURCE_DEFAULTS, "rank": index}
            for index, source_id in enumerate(SOURCES)
        }
    }


def _load_raw() -> dict:
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_raw(data: dict) -> None:
    os.makedirs(DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def load_config() -> dict:
    """Full config, backfilled so every registered source has an entry.

    New sources added to the registry appear automatically, ranked last.
    """
    with _lock:
        data = _load_raw()
        sources = data.get("sources")
        if not isinstance(sources, dict):
            sources = {}

        highest = max((entry.get("rank", 0) for entry in sources.values()
                       if isinstance(entry, dict)), default=-1)

        for source_id in SOURCES:
            entry = sources.get(source_id)
            if not isinstance(entry, dict):
                highest += 1
                sources[source_id] = {**SOURCE_DEFAULTS, "rank": highest}
            else:
                sources[source_id] = {**SOURCE_DEFAULTS, **entry}

        # drop entries for sources that no longer exist
        for stale in [k for k in sources if k not in SOURCES]:
            del sources[stale]

        data["sources"] = sources
        return data


def save_config(data: dict) -> dict:
    with _lock:
        # Never drop the settings section: callers here only ever build the
        # "sources" half, and writing their dict verbatim would erase every
        # app preference.
        existing = _load_raw()
        if "settings" in existing and "settings" not in data:
            data = {**data, "settings": existing["settings"]}
        _save_raw(data)
        return data


def get_source_config(source_id: str) -> dict:
    return load_config()["sources"].get(source_id, dict(SOURCE_DEFAULTS))


def set_source_config(source_id: str, **changes) -> dict:
    """Update one source's settings."""
    with _lock:
        config = load_config()
        entry = config["sources"].setdefault(source_id, dict(SOURCE_DEFAULTS))
        for key, value in changes.items():
            if key in SOURCE_DEFAULTS:
                entry[key] = value
        save_config(config)
        return entry


def set_enabled(source_id: str, enabled: bool) -> dict:
    """Exclude a source entirely (direct URLs still work)."""
    return set_source_config(source_id, enabled=bool(enabled))


def set_search_enabled(source_id: str, enabled: bool) -> dict:
    """Keep the source usable but leave it out of multi-source search."""
    return set_source_config(source_id, search_enabled=bool(enabled))


def reorder(order) -> dict:
    """Apply a new ranking from an ordered list of source ids.

    This is what the GUI's drag-and-drop list calls after a drop.
    """
    with _lock:
        config = load_config()
        rank = 0
        for source_id in order:
            if source_id in config["sources"]:
                config["sources"][source_id]["rank"] = rank
                rank += 1
        # anything not mentioned keeps a stable position at the end
        for source_id, entry in config["sources"].items():
            if source_id not in order:
                entry["rank"] = rank
                rank += 1
        save_config(config)
        return config


def move(source_id: str, delta: int) -> dict:
    """Nudge a source up (-1) or down (+1) the ranking."""
    order = ranked_ids(include_disabled=True)
    if source_id not in order:
        return load_config()
    index = order.index(source_id)
    target = max(0, min(len(order) - 1, index + delta))
    if target != index:
        order.insert(target, order.pop(index))
    return reorder(order)


def reset_config() -> dict:
    with _lock:
        return save_config(_default_config())


# ------------------------------------------------------------------ queries


def ranked_ids(include_disabled: bool = False, for_search: bool = False) -> list:
    """Source ids in user-defined rank order."""
    sources = load_config()["sources"]
    items = []
    for source_id, entry in sources.items():
        if not include_disabled:
            if not entry.get("enabled", True):
                continue
            if for_search and not entry.get("search_enabled", True):
                continue
        items.append((entry.get("rank", 100), source_id))
    items.sort()
    return [source_id for _rank, source_id in items]


def search_ids() -> list:
    """Sources that take part in a multi-source search."""
    return ranked_ids(for_search=True)


def is_enabled(source_id: str) -> bool:
    return bool(get_source_config(source_id).get("enabled", True))


def rank_of(source_id: str) -> int:
    return int(get_source_config(source_id).get("rank", 100))


def weight_of(source_id: str) -> float:
    try:
        return float(get_source_config(source_id).get("weight", 1.0))
    except (TypeError, ValueError):
        return 1.0


def describe() -> list:
    """Source metadata merged with its config, in rank order (for the UI)."""
    from .sources import list_sources

    config = load_config()["sources"]
    metas = {meta["id"]: meta for meta in list_sources()}
    rows = []
    for source_id in ranked_ids(include_disabled=True):
        meta = metas.get(source_id, {})
        rows.append({**meta, **config.get(source_id, {}), "id": source_id})
    return rows
