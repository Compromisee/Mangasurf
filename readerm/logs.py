"""File logging and crash-resume journal for ReaderM.

- Rotating log file:  ~/.readerm/logs/readerm.log
- Job journals:       ~/.readerm/jobs/<id>.json  (one per interrupted job)
"""


if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm"

import json
import logging
import os
import re
import shutil
import threading
from logging.handlers import RotatingFileHandler

from .paths import ensure as _ensure_data_dir

#: Created on first use, and populated from a MangaDL install if one
#: exists -- see readerm.paths.migrate.
BASE_DIR = _ensure_data_dir()
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "readerm.log")
CRASH_FILE = os.path.join(LOG_DIR, "crash.log")
JOURNAL_PATH = os.path.join(BASE_DIR, "job.json")

_configured = False
_crash_fh = None


#: Trim crash.log once it passes this. A user-supplied log had 116 session
#: markers and exactly 2 real crashes in it -- the signal was buried under
#: 114 lines of "started, nothing happened".
CRASH_LOG_MAX_BYTES = 512 * 1024


def _trim_crash_log():
    """Keep the tail of crash.log, so real tracebacks stay findable.

    Rotating would be wrong here: faulthandler writes to a file descriptor
    it keeps for the life of the process, so moving the file out from under
    it loses the very crash we are trying to capture. Truncating on the way
    *in*, before the handle is opened, is safe.
    """
    try:
        if os.path.getsize(CRASH_FILE) <= CRASH_LOG_MAX_BYTES:
            return
    except OSError:
        return
    try:
        with open(CRASH_FILE, "rb") as fh:
            fh.seek(-CRASH_LOG_MAX_BYTES // 2, os.SEEK_END)
            tail = fh.read()
        # Start at a session boundary so the file never opens mid-traceback.
        marker = tail.find(b"\n--- session start")
        if marker != -1:
            tail = tail[marker:]
        with open(CRASH_FILE, "wb") as fh:
            fh.write(b"--- earlier entries trimmed ---\n")
            fh.write(tail)
    except OSError:
        pass


def enable_crash_dumps():
    """Write a Python traceback of every thread to crash.log on hard crashes
    (segfaults, stack overflow, fatal aborts) via faulthandler.

    The file is trimmed on the way in. A user-supplied crash.log carried
    116 session markers and exactly 2 real tracebacks -- the signal was
    buried under 114 lines of "started, nothing happened".
    """
    global _crash_fh
    if _crash_fh is not None:
        return CRASH_FILE
    try:
        import faulthandler
        os.makedirs(LOG_DIR, exist_ok=True)
        _trim_crash_log()
        _crash_fh = open(CRASH_FILE, "a", encoding="utf-8", errors="replace")
        # faulthandler.enable() calls fileno() immediately and then writes
        # to that descriptor directly from the signal handler, so there is
        # no way to defer the header until a crash actually happens --
        # verified: a wrapper's fileno() is invoked during enable().
        #
        # Instead the marker is made cheap and self-cleaning: it says what
        # it is, and _trim_crash_log() keeps the file from growing without
        # bound. A user-supplied log had 116 markers around 2 real crashes.
        _crash_fh.write(
            f"\n--- session {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}"
            f" pid {os.getpid()} (no crash below this line = clean run) ---\n")
        _crash_fh.flush()
        faulthandler.enable(file=_crash_fh, all_threads=True)
    except Exception:
        _crash_fh = None
    return CRASH_FILE





class _BridgeNoiseFilter(logging.Filter):
    """Drop pywebview .NET-bridge noise (harmless but extremely spammy).

    On Windows, Edge's accessibility/autofill layer enumerates the
    `window.native` object pywebview exposes, producing endless
    'Error while processing window.native...' / recursion errors.
    """

    _PATTERNS = (
        "Error while processing window.native",
        "maximum recursion depth exceeded",
        "CoreWebView2 can only be accessed from the UI thread",
        "CoreWebView2Controller members can only be accessed",
    )

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            return True
        return not any(p in message for p in self._PATTERNS)


def quiet_pywebview():
    """Attach the noise filter to pywebview's logger (idempotent)."""
    pw = logging.getLogger("pywebview")
    if not any(isinstance(f, _BridgeNoiseFilter) for f in pw.filters):
        pw.addFilter(_BridgeNoiseFilter())


def setup_logging(level=logging.INFO):
    """Attach a rotating file handler to the root logger (idempotent)."""
    global _configured
    if _configured:
        return LOG_FILE
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"))
        root = logging.getLogger()
        root.addHandler(handler)
        if root.level > level or root.level == logging.NOTSET:
            root.setLevel(level)
        _configured = True
    except OSError:
        pass
    return LOG_FILE


def log_info() -> dict:
    """Path and size of the current log file."""
    size = os.path.getsize(LOG_FILE) if os.path.isfile(LOG_FILE) else 0
    return {"path": LOG_FILE, "size": size, "exists": size > 0}


def export_log(dest_path: str) -> str:
    """Copy the log file (plus rotated parts, concatenated) to dest_path."""
    parts = [LOG_FILE + suffix for suffix in (".3", ".2", ".1", "")]
    parts = [p for p in parts if os.path.isfile(p)]
    if not parts:
        raise FileNotFoundError("No log file yet")
    if len(parts) == 1:
        shutil.copyfile(parts[0], dest_path)
    else:
        with open(dest_path, "wb") as out:
            for p in parts:
                with open(p, "rb") as f:
                    shutil.copyfileobj(f, out)
    return dest_path


# --------------------------------------------------------------- journal
#
# The journal records in-progress jobs so a crash -- or a power cut -- can
# offer to resume them.
#
# It used to be a single file, ``job.json``, holding one job. That was wrong
# the moment the GUI grew concurrent downloads: two running jobs meant the
# second overwrote the first (measured: after starting A then B, the journal
# held only B, and A could never be resumed), and whichever job finished
# first called clear_journal() and wiped the record of the one still running.
#
# Now each job owns a file under ``~/.readerm/jobs/<id>.json`` and clears only
# its own. The legacy single file is still read, once, and migrated.

JOBS_DIR = os.path.join(BASE_DIR, "jobs")

_journal_lock = threading.RLock()


def _job_path(job_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(job_id or "default"))[:80]
    return os.path.join(JOBS_DIR, f"{safe}.json")


def write_journal(options_dict: dict, extra: dict = None,
                  job_id: str = None) -> None:
    """Record an in-progress job so it can be resumed after a crash.

    Written atomically (temp file + ``os.replace``) and fsynced, so a crash
    mid-write cannot leave a truncated file that reads back as "no job".
    """
    try:
        with _journal_lock:
            os.makedirs(JOBS_DIR, exist_ok=True)
            data = {"options": options_dict, "job_id": job_id or "default"}
            if extra:
                data.update(extra)
            path = _job_path(job_id)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
    except OSError:
        logging.getLogger(__name__).warning("Could not write job journal")


def _migrate_legacy_journal():
    """Move a pre-1.4.19 ``job.json`` into the per-job directory."""
    if not os.path.exists(JOURNAL_PATH):
        return
    try:
        with open(JOURNAL_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("options"):
            data.setdefault("job_id", "legacy")
            os.makedirs(JOBS_DIR, exist_ok=True)
            path = _job_path("legacy")
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
    except (OSError, ValueError):
        pass
    try:
        os.remove(JOURNAL_PATH)
    except OSError:
        pass


def read_journals() -> list:
    """Every interrupted job, newest first."""
    with _journal_lock:
        _migrate_legacy_journal()
        jobs = []
        try:
            names = sorted(os.listdir(JOBS_DIR))
        except OSError:
            return []
        for name in names:
            if not name.endswith(".json"):
                continue
            path = os.path.join(JOBS_DIR, name)
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                # A truncated file is not a usable job; drop it rather than
                # letting it break every future read.
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            if isinstance(data, dict) and data.get("options"):
                data.setdefault("job_id", name[:-5])
                try:
                    data.setdefault("_mtime", os.path.getmtime(path))
                except OSError:
                    data.setdefault("_mtime", 0)
                jobs.append(data)
        jobs.sort(key=lambda j: j.get("_mtime", 0), reverse=True)
        return jobs


def read_journal() -> dict:
    """The most recent interrupted job, or ``None``.

    Kept for callers that only handle one job (the CLI's ``resume``).
    """
    jobs = read_journals()
    return jobs[0] if jobs else None


def clear_journal(job_id: str = None) -> None:
    """Forget one job, or every job when ``job_id`` is omitted."""
    with _journal_lock:
        if job_id is None:
            try:
                names = os.listdir(JOBS_DIR)
            except OSError:
                names = []
            for name in names:
                if name.endswith(".json"):
                    try:
                        os.remove(os.path.join(JOBS_DIR, name))
                    except OSError:
                        pass
            try:
                os.remove(JOURNAL_PATH)
            except OSError:
                pass
            return
        try:
            os.remove(_job_path(job_id))
        except OSError:
            pass
