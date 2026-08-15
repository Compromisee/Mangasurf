"""Where ReaderM keeps its data, and the one-time move from ``~/.mangadl``.

Every module used to compute ``~/.mangadl`` for itself, which meant the rename
to ReaderM had eight independent places to get right and no single point to
hang a migration on. They all import ``DIR`` from here now.

Migration
---------
The app was called MangaDL until v3.2.0. An existing install has a library,
settings, bookmarks, reading positions and possibly a password in
``~/.mangadl``; launching a renamed build must not look like the data was
wiped. So on first run, if ``~/.readerm`` does not exist and ``~/.mangadl``
does, the JSON state is **copied** across -- copied, not moved, so the old
folder stays as a backup and downgrading still works.

Only ``.json`` files are copied. Logs, crash dumps, the singleton lock file
and any cache are per-install noise and are left behind deliberately.
"""

if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm"

import logging
import os
import shutil

logger = logging.getLogger(__name__)

APP_NAME = "ReaderM"
DIR_NAME = ".readerm"
LEGACY_DIR_NAME = ".mangadl"

#: State worth carrying over. Anything not listed is per-install noise:
#: ``instance.json`` is a live singleton handshake, and logs and crash dumps
#: describe a build that is no longer running.
MIGRATE_FILES = (
    "config.json",
    "settings.json",
    "library.json",
    "bookmarks.json",
    "bookmark_folders.json",
    "collections.json",
    "history.json",
    "filters.json",
    "notes.json",
    "progress.json",
    "watchlist.json",
    "queue.json",
    "stats.json",
    "snapshots.json",
    "lock.json",
    "reading.json",
    "annotations.json",
    "job.json",
)

SKIP_FILES = ("instance.json",)


def home() -> str:
    """Expanded home directory, read at call time.

    Not cached: the tests point HOME at a temporary directory, and a module
    level constant computed at import would ignore that.
    """
    return os.path.expanduser("~")


def data_dir() -> str:
    return os.path.join(home(), DIR_NAME)


def legacy_dir() -> str:
    return os.path.join(home(), LEGACY_DIR_NAME)


def migrate(force: bool = False) -> dict:
    """Copy MangaDL's state across, once.

    Returns ``{"migrated": bool, "files": [...], "reason": str}``. Safe to call
    repeatedly: it does nothing once the new directory exists, unless ``force``.
    """
    new = data_dir()
    old = legacy_dir()
    result = {"migrated": False, "files": [], "reason": ""}

    if not os.path.isdir(old):
        result["reason"] = "no previous install"
        return result
    if os.path.isdir(new) and not force:
        result["reason"] = "already set up"
        return result

    copied = []
    try:
        os.makedirs(new, exist_ok=True)
        for name in MIGRATE_FILES:
            if name in SKIP_FILES:
                continue
            source = os.path.join(old, name)
            target = os.path.join(new, name)
            if not os.path.isfile(source):
                continue
            if os.path.exists(target) and not force:
                continue
            shutil.copy2(source, target)      # copy2 keeps mtimes
            copied.append(name)
    except OSError as exc:
        # A failed migration must not stop the app starting: an empty library
        # is recoverable, a crash loop on launch is not.
        result["reason"] = f"copy failed: {exc}"
        logger.warning("migration from %s failed: %s", old, exc)
        return result

    result["migrated"] = bool(copied)
    result["files"] = copied
    result["reason"] = (f"copied {len(copied)} files from {LEGACY_DIR_NAME}"
                        if copied else "nothing to copy")
    if copied:
        logger.info("migrated %d files from %s to %s", len(copied), old, new)
    return result


def ensure() -> str:
    """The data directory, created and migrated if needed."""
    new = data_dir()
    if not os.path.isdir(new):
        migrate()
        os.makedirs(new, exist_ok=True)
    return new


#: Import-time convenience. Modules that need the path at call time should use
#: ``data_dir()`` instead, because HOME can change under tests.
DIR = data_dir()
