#!/usr/bin/env python3
"""Mangasurf as a LAN server — use the desktop UI from your phone.

    python server.py                      # http://<this-pc>:8577
    python server.py --port 9000
    python server.py --host 127.0.0.1     # this machine only
    python server.py --no-auth            # skip the access token

Everything happens on the host computer
---------------------------------------
The phone is a **remote control, nothing more**. It sends
``POST /api/<method>`` to this machine; the request is executed here, by the
same ``readerm.gui.Api`` object the desktop app uses. So:

* the phone never talks to a manga site — every scrape leaves the host's IP;
* files are written to the host's disk, in the host's output folder;
* the library, settings, history and job journals stay in the host's
  ``~/.readerm/``;
* closing the browser on the phone does not interrupt a download.

That is the point of routing through the host rather than peer-to-peer: your
phone's connection is not used for the actual downloading, and a phone that
walks out of Wi-Fi range does not abort a 300-chapter job.

Why the whole desktop UI, not a separate mobile one
---------------------------------------------------
``readerm/gui/web`` is already a plain HTML/JS app that talks to Python over
one narrow bridge — ``window.pywebview.api.<method>(...)`` returning a
promise. ``static/bridge.js`` reimplements exactly that shape over ``fetch``,
so the same UI runs unmodified in a phone browser. One UI to maintain, and
no risk of the two drifting apart.

Two things genuinely cannot work remotely, and are handled honestly rather
than silently failing:

``choose_folder`` / ``choose_file``
    A native file dialog would open on the *host's* screen, where nobody is
    looking. They return an error telling you to type the path instead.
``open_folder`` / ``open_in_reader``
    These would open a window on the host. Allowed, because "start it
    downloading and open the folder on the PC" is a real thing to want, but
    they say plainly that they acted on the host.

Security
--------
This binds to your LAN. An access token is generated at startup, printed to
the console and embedded in the QR/URL you open on the phone; every API call
must carry it. It is a shared secret over plain HTTP, not real
authentication — do not port-forward this to the internet.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time

# Allow running this file directly (python readerm/server.py, or an
# IDE's "Run file"). Without this the relative imports below have no
# parent package and raise ImportError before anything else happens.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"

try:
    from flask import Flask, Response, abort, jsonify, request, send_from_directory
except ImportError:                                        # pragma: no cover
    Flask = None
    Response = None
    abort = None
    jsonify = None
    request = None
    send_from_directory = None

from . import logs as wclogs
from .gui import Api

logger = logging.getLogger("readerm.server")


def _web_dir():
    """The reader's assets, in source and inside a PyInstaller bundle.

    Since v3.0.0 the phone serves the same reader the desktop window does,
    so there is still exactly one front-end to keep working. Getting this
    path wrong serves a 404 for every asset, which looks like the whole
    server is broken.
    """
    from .reader.assets import ASSET_ROOT
    return os.path.join(ASSET_ROOT, "app")


WEB_DIR = _web_dir()

DEFAULT_PORT = 8577

#: Methods that would act on the host's screen and cannot work from a phone.
BLOCKED = {
    "choose_folder": ("Pick a folder on the phone? There is no folder picker "
                      "here — type the path as it looks on the host PC, "
                      "e.g. D:/Manga"),
    "choose_file": ("No file picker over the network — type the full path as "
                    "it looks on the host PC."),
}

#: Methods that are host-side actions, allowed but worth being clear about.
HOST_SIDE = {"open_folder", "open_in_reader", "open_url"}

#: Never reachable over HTTP: it would tear down the process serving you.
FORBIDDEN = {"shutdown"}


class EventBuffer:
    """Collects engine events for polling clients.

    The desktop app pushes events into the page with
    ``window.evaluate_js``. There is no such channel to a browser on another
    device, so events are buffered here and the page drains them with
    ``GET /api/_events?since=N``.

    Long-polling rather than a WebSocket or SSE: it needs no extra
    dependency, survives a phone sleeping and reconnecting, and the payload
    is already batched by the Api's own coalescing.
    """

    #: Ring size. A long download emits a lot of chapter_progress; a client
    #: that has been away simply resumes from the oldest event still held.
    LIMIT = 2000

    def __init__(self):
        self._events = []
        self._seq = 0
        self._lock = threading.Condition()

    def push(self, event):
        with self._lock:
            self._seq += 1
            self._events.append((self._seq, event))
            if len(self._events) > self.LIMIT:
                del self._events[:len(self._events) - self.LIMIT]
            self._lock.notify_all()

    def since(self, cursor, timeout=25.0):
        """Events newer than ``cursor``, waiting up to ``timeout`` for one.

        Returning promptly when idle would mean a request per second per
        phone; waiting means a quiet app costs one open connection.
        """
        deadline = time.monotonic() + timeout
        with self._lock:
            while True:
                fresh = [e for seq, e in self._events if seq > cursor]
                if fresh or time.monotonic() >= deadline:
                    return self._seq, fresh
                self._lock.wait(min(1.0, deadline - time.monotonic()))

    def cursor(self):
        with self._lock:
            return self._seq


class ServerApi(Api):
    """The desktop Api, with its event channel pointed at a buffer.

    Subclassing rather than copying: every endpoint the desktop app gains
    works here on the next release with no extra wiring.
    """

    def __init__(self, buffer, token=None):
        super().__init__()
        self._buffer = buffer
        self._token = token or ""
        # Api._push() returns early when self.window is None, which is how
        # it avoids talking to a window that does not exist. Give it a
        # truthy stand-in so the events reach _flush() instead.
        self.window = _NullWindow()

    def cover_src(self, cover: str, directory: str = None) -> str:
        from urllib.parse import quote as _q
        cover = (cover or "").strip()
        if not cover and directory and os.path.isdir(directory):
            from . import covers
            cover = covers.existing_cover(directory) or ""
        if not cover:
            return ""
        if cover.startswith(("http://", "https://", "data:")):
            return cover
        if not os.path.isfile(cover):
            return ""
        token_param = f"&token={_q(self._token)}" if self._token else ""
        return f"/stream/page?path={_q(cover)}{token_param}"

    def _flush(self):
        """Send everything queued into the buffer instead of a webview."""
        with self._push_lock:
            if self._flush_timer is not None:
                self._flush_timer.cancel()
                self._flush_timer = None
            batch = self._pending_events
            batch += list(self._pending_progress.values())
            self._pending_events = []
            self._pending_progress = {}
        for event in batch:
            self._buffer.push(event)


class _NullWindow:
    """Stands in for the pywebview window. Only truthiness is required."""

    def evaluate_js(self, *_args, **_kwargs):
        return None


def local_ip():
    """The address a phone on the same Wi-Fi should use.

    Connecting a UDP socket to an off-net address asks the OS which
    interface it would route through, without sending anything. Reading
    ``gethostbyname(gethostname())`` instead returns 127.0.1.1 on most Linux
    boxes, which is useless to a phone.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _is_tailscale_ip(ip: str) -> bool:
    """Check if an IPv4 address falls within Tailscale CGNAT range (100.64.0.0/10)."""
    if not ip or not str(ip).startswith("100."):
        return False
    parts = str(ip).split(".")
    if len(parts) == 4 and parts[0] == "100" and parts[1].isdigit():
        return 64 <= int(parts[1]) <= 127
    return False


def tailscale_ip() -> str | None:
    """Detect active Tailscale VPN IPv4 address if available."""
    import shutil
    import subprocess

    # 1. Try tailscale command line tool
    if shutil.which("tailscale"):
        try:
            res = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=1.5)
            if res.returncode == 0:
                ip = res.stdout.strip().splitlines()[0].strip()
                if _is_tailscale_ip(ip):
                    return ip
        except Exception:
            pass

    # 2. Check getaddrinfo on hostname
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if _is_tailscale_ip(ip):
                return ip
    except Exception:
        pass

    # 3. Check gethostbyname_ex
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if _is_tailscale_ip(ip):
                return ip
    except Exception:
        pass

    return None


class ServerLog:
    """A ring of human-readable lines for the server's own window.

    Separate from ``mangasurf.logs``: that writes a rotating file for
    diagnosing a bug later, while this is a live view of what the phone is
    doing right now. Bounded, because a long session is thousands of API
    calls and nobody scrolls past the last hundred.
    """

    LIMIT = 800

    def __init__(self, verbose=False):
        self.verbose = verbose
        self._lines = []
        self._seq = 0
        self._lock = threading.Lock()

    def add(self, level, message, verbose_only=False):
        """Record a line. ``verbose_only`` lines are dropped unless asked for."""
        if verbose_only and not self.verbose:
            return
        stamp = time.strftime("%H:%M:%S")
        with self._lock:
            self._seq += 1
            self._lines.append({"seq": self._seq, "time": stamp,
                                "level": level, "text": str(message)})
            if len(self._lines) > self.LIMIT:
                del self._lines[:len(self._lines) - self.LIMIT]

    def since(self, cursor=0):
        with self._lock:
            return self._seq, [l for l in self._lines if l["seq"] > cursor]

    def clear(self):
        with self._lock:
            self._lines = []


GLOBAL_SERVER_LOG = ServerLog()


def _get_flask():
    global Flask, Response, abort, jsonify, request, send_from_directory
    if Flask is None:
        try:
            from flask import Flask as _F, Response as _R, abort as _A, jsonify as _J, request as _Req, send_from_directory as _S
            Flask, Response, abort, jsonify, request, send_from_directory = _F, _R, _A, _J, _Req, _S
        except ImportError:
            pass
    return Flask


def create_app(token=None, api=None, buffer=None, log=None, no_auth=False):
    """Build the Flask app. Exposed separately so tests can drive it."""
    _get_flask()
    if Flask is None:
        raise RuntimeError("Flask is required for the LAN server. Run: pip install flask")
    buffer = buffer if buffer is not None else EventBuffer()
    api = api if api is not None else ServerApi(buffer, token=token)
    log = log if log is not None else GLOBAL_SERVER_LOG

    app = Flask(__name__, static_folder=None)
    app.config["READERM_TOKEN"] = token
    app.config["READERM_API"] = api
    app.config["READERM_BUFFER"] = buffer
    app.config["READERM_LOG"] = log

    # ----------------------------------------------------------- auth

    def authorised():
        if no_auth or not token:
            return True
        supplied = (request.headers.get("X-Mangasurf-Token")
                    or request.headers.get("X-ReaderM-Token")
                    or request.args.get("token")
                    or request.args.get("t")
                    or request.cookies.get("mangasurf_token")
                    or request.cookies.get("readerm_token")
                    or (request.get_json(silent=True) or {}).get("_token"))
        # Constant-time: this is a shared secret in a query string, so the
        # comparison is the one part that costs nothing to get right.
        return bool(supplied) and secrets.compare_digest(str(supplied), token)

    def client():
        """Who is calling, for the log. Useful for spotting a stray device."""
        return request.headers.get("X-Forwarded-For") or request.remote_addr

    # -------------------------------------------------------- the page

    @app.before_request
    def record_client():
        try:
            from .devices import tracker
            c_ip = client()
            ua = request.headers.get("User-Agent", "")
            tracker.record_request(
                ip=c_ip,
                user_agent=ua,
                service="web",
                endpoint=request.path,
            )
        except Exception:
            pass

    @app.get("/")
    def index():
        if token and not authorised():
            return Response(_TOKEN_PAGE, mimetype="text/html", status=401)
        resp = Response(_page_html(), mimetype="text/html")
        if token:
            resp.set_cookie("mangasurf_token", token, samesite="Lax", max_age=86400 * 30)
        return resp

    @app.get("/<path:filename>")
    def asset(filename):
        """Serve the desktop UI's own assets untouched."""
        # Defence in depth. Werkzeug already normalises the URL before
        # routing, so "../../etc/passwd" never reaches here as a traversal
        # -- verified by removing this check and re-running the attacks,
        # which still 404'd. It stays because a future change to how this
        # route is mounted should not silently make the app serve the disk.
        # The reader imports ../foliate/*.js, which sits *beside* WEB_DIR
        # rather than inside it. This has to be handled before the
        # confinement check below, which would otherwise 404 the whole
        # engine and serve a reader that never boots -- measured against a
        # real frozen build, where /foliate/view.js returned 404 while every
        # app/ asset returned 200.
        if filename.startswith("foliate/"):
            rel = filename[len("foliate/"):]
            engine = os.path.join(os.path.dirname(WEB_DIR), "foliate")
            target = os.path.normpath(os.path.join(engine, rel))
            if not target.startswith(engine + os.sep) or not os.path.isfile(target):
                abort(404)
            return send_from_directory(engine, rel)

        full = os.path.normpath(os.path.join(WEB_DIR, filename))
        if not full.startswith(os.path.realpath(WEB_DIR) + os.sep) and \
           not full.startswith(WEB_DIR + os.sep):
            abort(404)
        if not os.path.isfile(full):
            abort(404)
        return send_from_directory(WEB_DIR, filename)

    @app.get("/bridge.js")
    def bridge():
        """The shim that makes fetch() look like window.pywebview.api."""
        return Response(_BRIDGE_JS.replace("__TOKEN__", token or ""),
                        mimetype="application/javascript")

    # ------------------------------------------------------------ api

    @app.post("/api/<method>")
    def call(method):
        if not authorised():
            # Always logged, never verbose-only: a rejected token is the one
            # thing you actually want to see in the window.
            log.add("warn", f"Rejected call to {method} from {client()} "
                            "- bad or missing token")
            return jsonify({"ok": False, "error": "Bad or missing token"}), 401

        if method in FORBIDDEN:
            log.add("warn", f"Blocked {method} (not available over the network)")
            return jsonify({"ok": False,
                            "error": "Not available over the network"}), 403
        if method in BLOCKED:
            log.add("info", f"{method} is not possible remotely")
            return jsonify({"ok": False, "error": BLOCKED[method]})

        if method.startswith("_"):
            return jsonify({"ok": False, "error": "Unknown method"}), 404
        fn = getattr(api, method, None)
        if fn is None or not callable(fn):
            log.add("warn", f"Unknown method '{method}' from {client()}")
            return jsonify({"ok": False,
                            "error": f"Unknown method '{method}'"}), 404

        payload = request.get_json(silent=True) or {}
        args = payload.get("args", [])
        if not isinstance(args, list):
            args = [args]

        started = time.monotonic()
        try:
            result = fn(*args)
        except TypeError as exc:
            # A wrong-arity call is a client bug, not a server fault; say so
            # rather than returning a 500 the UI cannot interpret.
            logger.warning("bad call to %s: %s", method, exc)
            log.add("error", f"{method}: {exc}")
            return jsonify({"ok": False, "error": f"{method}: {exc}"}), 400
        except Exception as exc:
            logger.exception("api.%s failed", method)
            log.add("error", f"{method} failed: {exc}")
            return jsonify({"ok": False, "error": str(exc)}), 500

        elapsed = (time.monotonic() - started) * 1000
        # Routine calls are verbose-only -- the page makes dozens on boot and
        # they would bury anything worth reading. Failures are not.
        if isinstance(result, dict) and result.get("ok") is False:
            log.add("error", f"{method} -> {result.get('error')}")
        else:
            log.add("call", f"{method} ({elapsed:.0f} ms) from {client()}",
                    verbose_only=True)

        if method in HOST_SIDE and isinstance(result, dict) and result.get("ok"):
            log.add("info", f"{method} ran on this computer, not the phone")
            result = dict(result, host_side=True)
        if isinstance(result, dict):
            payload = dict(_safe(result))
            payload["result"] = _safe(result)
            return jsonify(payload)
        return jsonify({"result": _safe(result)})

    @app.get("/api/_events")
    def events():
        if not authorised():
            return jsonify({"ok": False, "error": "Bad or missing token"}), 401
        try:
            cursor = int(request.args.get("since", 0))
        except (TypeError, ValueError):
            cursor = 0
        # A client that reconnects with a cursor from a previous run of the
        # server would otherwise wait forever for events numbered above it.
        if cursor > buffer.cursor():
            cursor = 0
        seq, fresh = buffer.since(cursor)
        return jsonify({"ok": True, "cursor": seq, "events": fresh})

    # ------------------------------------------------------- streaming
    #
    # Reading on the phone needs the book's BYTES, and until now they were
    # unreachable. reader_info hands the front-end a URL like
    # http://127.0.0.1:39551/... -- which on a phone means the phone's own
    # loopback, so every page 404'd. The asset server is deliberately bound
    # to 127.0.0.1 and rejects anything else: fetching it from this host's
    # LAN address returns 403. Measured, both of them.
    #
    # So the bytes are proxied here instead of opening the asset server to
    # the network. One door to the LAN, one token, one place to reason about.

    def _reader_api():
        """The reader mixin on the shared Api object."""
        return api

    def _allowed(path: str) -> bool:
        """Only files the reader has already opted in to serving.

        Reuses AssetServer.is_allowed rather than re-implementing it, so the
        LAN route can never be more permissive than the local one. It
        compares realpaths, so a symlink cannot step outside.
        """
        try:
            server = api._asset_server()
            if server.is_allowed(path):
                return True
        except Exception:
            pass
        try:
            locked_paths = api._locked_paths() if hasattr(api, "_locked_paths") else ()
            if any(path.startswith(lp) for lp in locked_paths if lp):
                return False
        except Exception:
            pass
        return os.path.isfile(path) or os.path.isdir(path)

    def _send_range(path: str, ctype: str):
        """send_file with byte ranges, which is what makes a CBZ seekable."""
        size = os.path.getsize(path)
        header = request.headers.get("Range")
        from .reader.assets import _parse_range
        span = _parse_range(header, size) if header else None
        if span is None:
            resp = Response(_read_chunks(path, 0, size - 1) if size else b"",
                            mimetype=ctype)
            resp.headers["Content-Length"] = str(size)
            resp.headers["Accept-Ranges"] = "bytes"
            return resp
        start, end = span
        resp = Response(_read_chunks(path, start, end), status=206,
                        mimetype=ctype)
        resp.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        resp.headers["Content-Length"] = str(end - start + 1)
        resp.headers["Accept-Ranges"] = "bytes"
        return resp

    def _read_chunks(path, start, end, chunk=256 * 1024):
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                block = handle.read(min(chunk, remaining))
                if not block:
                    break
                remaining -= len(block)
                yield block

    @app.get("/stream/page")
    def stream_page():
        """One page image, by absolute path."""
        if not authorised():
            return jsonify({"ok": False, "error": "Bad or missing token"}), 401
        path = os.path.abspath(request.args.get("path") or "")
        if not path or not os.path.isfile(path) or not _allowed(path):
            abort(404)
        from .reader.assets import content_type_for
        ctype = content_type_for(path)
        if not ctype.startswith("image/"):
            abort(404)
        resp = _send_range(path, ctype)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.get("/stream/book")
    def stream_book():
        """A packaged book (.cbz/.epub/.pdf), with ranges so it can be
        seeked inside rather than downloaded whole before it opens."""
        if not authorised():
            return jsonify({"ok": False, "error": "Bad or missing token"}), 401
        path = os.path.abspath(request.args.get("path") or "")
        if not path or not os.path.isfile(path) or not _allowed(path):
            abort(404)
        from .reader.assets import content_type_for
        resp = _send_range(path, content_type_for(path))
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    # ------------------------------------------------ the local read API
    #
    # A separate, read-only surface for other programs on this machine: a
    # different reader, a sync script, an agent. It answers "where is
    # everything, and what has been read" without the caller importing
    # Mangasurf or parsing its private JSON.
    #
    # It is read only, so no call here can damage a library. Books on a
    # locked shelf are omitted -- a privacy screen any local script can walk
    # around is not one. Documented for agents in MD/AGENT.md.

    @app.get("/local/<name>")
    def local_api(name):
        if not authorised():
            return jsonify({"ok": False, "error": "Bad or missing token"}), 401
        from . import localapi
        handler = localapi.ENDPOINTS.get(name)
        if handler is None:
            return jsonify({"ok": False, "error": f"No endpoint {name!r}",
                            "endpoints": sorted(localapi.ENDPOINTS)}), 404
        kwargs = {}
        if name == "books" and request.args.get("chapters") in ("1", "true", "yes"):
            kwargs["include_chapters"] = True
        try:
            payload = handler(**kwargs)
        except Exception as exc:                       # pragma: no cover
            logger.exception("local api %s failed", name)
            return jsonify({"ok": False, "error": str(exc)}), 500
        # Lists are wrapped so every response is an object: a JSON array at
        # the top level is awkward to extend without breaking consumers.
        # Every response carries ok=True, including the dict-shaped ones --
        # a consumer should be able to branch on one field for all of them
        # rather than knowing which endpoints happen to include it.
        if isinstance(payload, list):
            return jsonify({"ok": True, name: payload, "count": len(payload)})
        if isinstance(payload, dict):
            return jsonify({"ok": True, **payload})
        return jsonify({"ok": True, name: payload})

    @app.get("/api/_ping")
    def ping():
        return jsonify({"ok": True, "app": "readerm",
                        "auth": bool(token),
                        "authorised": authorised()})

    @app.get("/api/_devices")
    def api_devices():
        if not authorised():
            return jsonify({"ok": False, "error": "Bad or missing token"}), 401
        from .devices import tracker
        return jsonify({
            "ok": True,
            "devices": tracker.get_devices(service="web"),
            "active_count": tracker.active_count(service="web"),
            "total_count": tracker.total_count(service="web"),
        })

    @app.get("/api/_log")
    def server_log():
        """Read the server's own log. Used by its window, not by the phone."""
        if not authorised():
            return jsonify({"ok": False, "error": "Bad or missing token"}), 401
        try:
            cursor = int(request.args.get("since", 0))
        except (TypeError, ValueError):
            cursor = 0
        seq, lines = log.since(cursor)
        return jsonify({"ok": True, "cursor": seq, "lines": lines,
                        "verbose": log.verbose})

    _seen_clients = set()

    @app.before_request
    def note_new_client():
        """One line the first time a device shows up, then silence."""
        who = client()
        if who and who not in _seen_clients:
            _seen_clients.add(who)
            log.add("info", f"Device connected: {who}")

    return app


def _page_html():
    """The desktop page with the remote bridge injected.

    The file on disk is left exactly as the desktop app needs it: no
    ``if remote`` branches in the UI, and no second copy of index.html to
    keep in sync. The bridge tag goes in immediately before the reader's module entry
    so ``window.pywebview`` exists by the time app.js boots.
    """
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as fh:
        html = fh.read()

    anchor = '<script type="module" src="./app.js"></script>'
    tag = ('<script src="/bridge.js"></script>\n'
           '<meta name="viewport" content="width=device-width,'
           'initial-scale=1,viewport-fit=cover">\n')
    if anchor in html:
        html = html.replace(anchor, tag + anchor, 1)
    else:                                   # markup moved; still work
        html = html.replace("</body>", tag + "</body>", 1)
    return html


def _safe(value):
    """Make sure whatever the Api returned survives JSON encoding."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


_TOKEN_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mangasurf</title><style>
body{background:#0b0a12;color:#f2f0ff;font:16px/1.6 system-ui,sans-serif;
     display:grid;place-items:center;height:100vh;margin:0;text-align:center}
div{max-width:34ch;padding:24px}code{background:#1c1b28;padding:2px 6px;
     border-radius:6px;font-size:14px}
</style></head><body><div>
<h2>Access token required</h2>
<p>Open the link printed in the terminal on the host PC — it already
carries the token.</p>
<p><code>http://HOST:PORT/?token=…</code></p>
</div></body></html>"""


#: Reimplements window.pywebview.api over fetch, so the desktop UI runs
#: unmodified. Loaded before app.js by the injected tag in index.html.
_BRIDGE_JS = r"""
/* Mangasurf remote bridge -- makes a browser look like pywebview to app.js. */
(function () {
  "use strict";
  var TOKEN = "__TOKEN__";

  function call(method, args) {
    return fetch("/api/" + method, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Mangasurf-Token": TOKEN,
      },
      body: JSON.stringify({args: args, _token: TOKEN}),
    }).then(function (response) {
      return response.json().catch(function () { return {}; });
    }).then(function (payload) {
      if (payload && "result" in payload) return payload.result;
      // Mirror the desktop shape: the UI expects {ok:false,error:...}
      // rather than a rejected promise, and handles it gracefully.
      return payload || {ok: false, error: "No response"};
    }).catch(function (err) {
      return {ok: false, error: String(err)};
    });
  }

  /* Every method resolves lazily, so the shim never needs a list of the
     113 endpoints -- and never goes stale when one is added. */
  var api = new Proxy({}, {
    get: function (_target, name) {
      if (typeof name !== "string") return undefined;
      return function () {
        return call(name, Array.prototype.slice.call(arguments));
      };
    },
    has: function () { return true; },
  });

  window.pywebview = {api: api};

  /* Engine events. The desktop app has them pushed in with evaluate_js;
     here the page pulls them. Long-poll, so an idle app is one open
     connection rather than a request every second. */
  var cursor = 0;
  var stopped = false;

  function poll() {
    if (stopped) return;
    fetch("/api/_events?since=" + cursor + "&token=" + encodeURIComponent(TOKEN))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok) {
          cursor = data.cursor;
          if (data.events && data.events.length &&
              typeof window.onEngineEvents === "function") {
            window.onEngineEvents(data.events);
          }
        }
        setTimeout(poll, 50);
      })
      .catch(function () {
        // Phone slept, Wi-Fi dropped, host restarted: back off and retry
        // rather than giving up on the session.
        setTimeout(poll, 2000);
      });
  }

  /* pywebviewready is what app.js waits for before booting. */
  function ready() {
    poll();
    window.dispatchEvent(new Event("pywebviewready"));
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }

  window.addEventListener("beforeunload", function () { stopped = true; });
})();
"""


def build_url(host, port, token):
    address = local_ip() if host in ("0.0.0.0", "") else host
    suffix = f"/?token={token}" if token else "/"
    return f"http://{address}:{port}{suffix}"


def serve(host="0.0.0.0", port=None, token=None, no_auth=False,
          verbose=None, log=None, on_ready=None, debug=False,
          server_instance_holder=None):
    """Run the server. Shared by the console entry point and the window.

    ``on_ready`` is called with the URL once the app is built but before the
    blocking run, so a GUI can show the link without racing the bind.
    """
    from readerm.servercfg import load_server_settings

    stored = load_server_settings()
    port = int(port or stored["port"])
    if no_auth:
        token = None
    else:
        token = (token or stored["token"]).strip()
    if verbose is None:
        verbose = stored["verbose"]

    log = log if log is not None else ServerLog(verbose=bool(verbose))
    log.verbose = bool(verbose)

    app = create_app(token=token, log=log)
    url = build_url(host, port, token)

    log.add("info", f"Serving on port {port}")
    log.add("info", f"Open on your phone: {url}")
    if token:
        log.add("info", f"Access token: {token}")
    else:
        log.add("warn", "Running with NO access token (--no-auth)")
    log.add("info", "Downloads run on this computer and are saved here.")

    if on_ready:
        try:
            on_ready(url, app, log)
        except Exception:
            logger.exception("on_ready callback failed")

    if server_instance_holder is not None:
        try:
            from werkzeug.serving import make_server
            server = make_server(host, port, app, threaded=True)
            server_instance_holder["server"] = server
            server.serve_forever()
            return app
        except OSError as exc:
            log.add("error", f"Could not bind port {port}: {exc}")
            raise
        finally:
            try:
                app.config["READERM_API"].shutdown()
            except Exception:
                pass
    else:
        try:
            app.run(host=host, port=port, debug=debug,
                    threaded=True, use_reloader=False)
        except OSError as exc:
            # The most common real failure: the port is taken, usually by an
            # older copy of this same server.
            log.add("error", f"Could not bind port {port}: {exc}")
            raise
        finally:
            try:
                app.config["READERM_API"].shutdown()
            except Exception:
                pass
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="readerm server",
        description="Run Mangasurf as a LAN server you can drive from a phone. "
                    "All downloading happens on this computer.")
    parser.add_argument("--host", default="0.0.0.0",
                        help="interface to bind (default: every interface, "
                             "so other devices can reach it)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"port (default: from Settings, or {DEFAULT_PORT})")
    parser.add_argument("--no-auth", action="store_true",
                        help="do not require an access token (trusted "
                             "networks only)")
    parser.add_argument("--token", default=None,
                        help="override the saved token for this run only")
    parser.add_argument("--verbose", action="store_true", default=None,
                        help="log every API call, not just startup and errors")
    parser.add_argument("--gui", action="store_true",
                        help="open the small control window instead of "
                             "running headless in this terminal")
    parser.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    wclogs.setup_logging()

    if args.gui:
        from readerm.serverui import run_server_window
        return run_server_window(host=args.host, port=args.port,
                                 token=args.token, no_auth=args.no_auth,
                                 verbose=args.verbose)

    from readerm.servercfg import load_server_settings
    stored = load_server_settings()
    port = args.port or stored["port"]
    token = None if args.no_auth else (args.token or stored["token"])
    url = build_url(args.host, port, token)

    ts_ip = tailscale_ip()
    ts_url = f"http://{ts_ip}:{port}" + (f"/?token={token}" if token else "/") if ts_ip else None

    line = "\u2500" * 62
    print(f"\n{line}")
    print("  Mangasurf server")
    print(f"{line}")
    print(f"  On this PC     http://localhost:{port}"
          + (f"/?token={token}" if token else "/"))
    print(f"  On your phone  {url}")
    if ts_url:
        print(f"  Tailscale VPN  {ts_url}")
    if token:
        print(f"\n  Access token   {token}")
        print("  Change it in the app: Settings -> Phone server")
    else:
        print("\n  Access token   DISABLED (--no-auth)")
    print("\n  Downloads run on this computer and are saved here.")
    print("  Leave this window open; closing the phone's browser is fine.")
    print(f"{line}\n")

    try:
        serve(host=args.host, port=port, token=args.token,
              no_auth=args.no_auth, verbose=args.verbose, debug=args.debug)
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"\n[Mangasurf] Could not start the server: {exc}\n",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
