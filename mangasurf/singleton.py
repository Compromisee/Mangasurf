"""One Mangasurf at a time, and a way to poke the one already running.

Why this exists
---------------
Nothing stopped a second copy starting while the first sat in the system
tray. Reproduced by launching three times against one profile: **all three
stayed alive**, each with its own tray icon, its own download engine and its
own writes to the same ``library.json``, ``config.json`` and job journals.
Since the window is hidden, the obvious way to "reopen" Mangasurf -- run it
again -- is exactly what produced the duplicates.

How it works
------------
A small TCP server on the loopback interface, with its port written to
``~/.readerm/instance.json``:

* **The port file is the lock.** Binding a socket is atomic and the OS
  releases it when the process dies, so a killed instance never leaves a
  stale lock behind that needs cleaning up -- the classic failure of
  PID-file locking.
* **It doubles as the wake-up channel.** A second launch connects, sends
  ``show``, and exits. The running instance raises its window, which is what
  the user actually wanted.

Only loopback is bound, and a random token in the file must match before any
command is honoured, so another user on the same machine cannot drive the
window around.

``socket`` is used rather than a named mutex or ``fcntl`` because the same
code then works on Windows, macOS and Linux, and because a mutex cannot
carry the "show yourself" message.
"""


if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "readerm"

import json
import logging
import os
import secrets
import socket
import threading

logger = logging.getLogger(__name__)

from .paths import ensure as _ensure_data_dir

#: Created on first use, and populated from a MangaDL install if one
#: exists -- see mangasurf.paths.migrate.
BASE_DIR = _ensure_data_dir()
INSTANCE_FILE = os.path.join(BASE_DIR, "instance.json")

#: Loopback only. Never bind 0.0.0.0 for this.
HOST = "127.0.0.1"

#: How long to wait for the running instance to answer. Generous enough for
#: a busy machine, short enough that a dead port file does not hang startup.
CONNECT_TIMEOUT = 1.5


def _read_instance():
    try:
        with open(INSTANCE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        port = int(data.get("port") or 0)
        token = str(data.get("token") or "")
        if port and token:
            return port, token
    except Exception:
        pass
    return None, None


def _write_instance(port, token):
    os.makedirs(BASE_DIR, exist_ok=True)
    tmp = INSTANCE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"port": port, "token": token, "pid": os.getpid()}, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, INSTANCE_FILE)


def notify_existing(command="show"):
    """Ask an already-running Mangasurf to surface. True if one answered.

    A stale port file (the previous run was killed) simply fails to connect
    and returns False, so startup continues normally.
    """
    port, token = _read_instance()
    if not port:
        return False
    try:
        with socket.create_connection((HOST, port), CONNECT_TIMEOUT) as sock:
            sock.settimeout(CONNECT_TIMEOUT)
            sock.sendall(f"{token} {command}\n".encode("utf-8"))
            reply = sock.recv(32).decode("utf-8", "replace").strip()
        return reply == "ok"
    except OSError:
        logger.debug("no live instance on port %s", port, exc_info=True)
        return False


class InstanceServer:
    """Owns the port file and listens for wake-up requests."""

    def __init__(self, on_show=None):
        self.on_show = on_show
        self._sock = None
        self._thread = None
        self._stop = threading.Event()
        self.port = None

    def start(self):
        """Claim the single-instance slot. False means one already runs."""
        if notify_existing("show"):
            return False

        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Deliberately NOT SO_REUSEADDR: on some platforms that lets two
            # processes bind the same port, which would defeat the lock.
            self._sock.bind((HOST, 0))          # 0 = let the OS pick
            self._sock.listen(4)
            self.port = self._sock.getsockname()[1]
        except OSError:
            logger.warning("could not open the single-instance socket; "
                           "duplicate launches will not be prevented",
                           exc_info=True)
            self._sock = None
            return True          # never block startup over this

        self._token = secrets.token_hex(16)
        try:
            _write_instance(self.port, self._token)
        except Exception:
            logger.debug("could not write the instance file", exc_info=True)

        self._thread = threading.Thread(target=self._serve,
                                        name="readerm-instance", daemon=True)
        self._thread.start()
        return True

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return                      # socket closed by stop()
            with conn:
                try:
                    conn.settimeout(CONNECT_TIMEOUT)
                    line = conn.recv(128).decode("utf-8", "replace").strip()
                    token, _, command = line.partition(" ")
                    if token != self._token:
                        continue            # not ours; say nothing
                    conn.sendall(b"ok\n")
                    if command.strip() == "show" and self.on_show:
                        # Run the callback off the accept loop: raising a
                        # window can block, and a blocked loop would refuse
                        # the next launch and let a duplicate through.
                        threading.Thread(target=self._safe_show,
                                         name="readerm-show",
                                         daemon=True).start()
                except OSError:
                    continue

    def _safe_show(self):
        try:
            self.on_show()
        except Exception:
            logger.exception("could not surface the window")

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        # Only remove the file if it is still ours.
        try:
            with open(INSTANCE_FILE, encoding="utf-8") as fh:
                if json.load(fh).get("pid") == os.getpid():
                    os.remove(INSTANCE_FILE)
        except Exception:
            pass
