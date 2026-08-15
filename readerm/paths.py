"""Data directory resolution and migration for Mangasurf.

Supports data storage at ``~/.mangasurf`` with seamless migration from ``~/.readerm``
and ``~/.mangadl``.
"""

if __package__ in (None, ""):
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm"

import logging
import os
import shutil

logger = logging.getLogger(__name__)

APP_NAME = "Mangasurf"
DIR_NAME = ".mangasurf"
LEGACY_DIR_NAMES = (".readerm", ".mangadl")

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
    return os.path.expanduser("~")


def data_dir() -> str:
    return os.path.join(home(), DIR_NAME)


def legacy_dirs() -> list:
    return [os.path.join(home(), d) for d in LEGACY_DIR_NAMES]


def migrate(force: bool = False) -> dict:
    """Copy state across from previous installs."""
    new = data_dir()
    result = {"migrated": False, "files": [], "reason": ""}

    if os.path.isdir(new) and not force:
        result["reason"] = "already set up"
        return result

    copied = []
    for old in legacy_dirs():
        if not os.path.isdir(old):
            continue
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
                shutil.copy2(source, target)
                copied.append(name)
        except OSError as exc:
            logger.warning("migration from %s failed: %s", old, exc)

    result["migrated"] = bool(copied)
    result["files"] = copied
    result["reason"] = f"copied {len(copied)} files" if copied else "nothing to copy"
    return result


def ensure() -> str:
    new = data_dir()
    if not os.path.isdir(new):
        migrate()
        os.makedirs(new, exist_ok=True)
    return new


DIR = data_dir()
