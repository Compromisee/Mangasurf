"""Loopback asset server for the reader.

Serves three kinds of thing:

``/`` and ``/app/...``
    The reader UI and the vendored foliate-js engine, straight off disk (or out
    of the PyInstaller bundle).

``/book?path=...``
    A whole book file — ``.cbz``, ``.epub``, ``.pdf`` and friends — streamed
    with Range support so the engine can seek inside a zip without pulling the
    whole thing into memory.

``/page?path=...``
    A single loose image. Chapters that have been downloaded but not packaged
    are just folders of ``.jpg``; this is what makes those readable without
    zipping them first.

Access rules
------------
Bound to 127.0.0.1 only, and every request must carry the process token (as
``?t=`` or ``X-ReaderM-Token``). The token is generated per process and never
written to disk. Paths are checked against a set of roots that the app opts
into, so a leaked token still cannot walk out of the library.
"""

if __package__ in (None, ""):        # pragma: no cover - direct execution
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "mangasurf.reader"

import json
import logging
import mimetypes
import os
import secrets
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"

#: Session cookie carrying the access token. Set on the first request that
#: presents the token explicitly, so relative sub-resources -- and the nested
#: imports inside them -- are authorised without a query string.
COOKIE_NAME = "readerm_token"

#: Explicit types, because ``mimetypes`` on Windows reads its table out of the
#: registry and has been observed returning ``text/plain`` for ``.js`` — which
#: makes the browser refuse the module and the reader silently never boots.
MEDIA_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".jxl": "image/jxl",
    ".cbz": "application/vnd.comicbook+zip",
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
    ".mobi": "application/x-mobipocket-ebook",
    ".azw3": "application/vnd.amazon.mobi8-ebook",
    ".fb2": "application/x-fictionbook+xml",
    ".txt": "text/plain; charset=utf-8",
}

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif", ".jxl",
}


def _asset_root() -> str:
    """Where the reader's own files live, in source and when frozen."""
    if getattr(sys, "frozen", False):
        base = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)),
                            "mangasurf", "reader")
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return base


ASSET_ROOT = _asset_root()


def new_token(nbytes: int = 24) -> str:
    """A fresh per-process token. Never persisted."""
    return secrets.token_urlsafe(nbytes)


def content_type_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in MEDIA_TYPES:
        return MEDIA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def is_safe_relative(rel: str) -> bool:
    """True if ``rel`` stays inside the asset tree.

    Rejects absolute paths, drive letters and any ``..`` segment. Werkzeug
    normalises URLs before routing, but this server is plain ``http.server``,
    which does not — so the check has to be real here.
    """
    if not rel:
        return False
    if rel.startswith(("/", "\\")):
        return False
    if os.path.splitdrive(rel)[0]:
        return False
    parts = rel.replace("\\", "/").split("/")
    return not any(p in ("..", "") for p in parts if p != ".")


class AssetServer:
    """Serves reader assets and book content on loopback.

    ``allow(path)`` opts a file or directory into being readable. Nothing
    outside the asset tree is served until it has been allowed, so the reader
    cannot be talked into handing over arbitrary files.
    """

    def __init__(self, root: str = None, token: str = None, api=None):
        self.root = os.path.abspath(root or ASSET_ROOT)
        self.token = token or new_token()
        #: Object whose public methods the ``/_api/`` bridge exposes. The
        #: front-end only uses that route when ``window.pywebview`` never
        #: arrives, so leaving this None simply makes the fallback report
        #: that there is nothing to call.
        self.api = api
        self._roots = set()
        self._lock = threading.RLock()
        self._httpd = None
        self._thread = None
        self.port = None

    # -------------------------------------------------------------- allowing

    def allow(self, path: str) -> str:
        """Permit reads of ``path`` (a file or a directory tree)."""
        if not path:
            return ""
        real = os.path.realpath(os.path.abspath(path))
        with self._lock:
            self._roots.add(real)
        return real

    def allowed_roots(self) -> set:
        with self._lock:
            return set(self._roots)

    def is_allowed(self, path: str) -> bool:
        """True if ``path`` sits inside something that was allowed.

        Compares real paths so a symlink cannot be used to step outside.
        """
        if not path:
            return False
        real = os.path.realpath(os.path.abspath(path))
        with self._lock:
            roots = tuple(self._roots)
        for root in roots:
            if real == root:
                return True
            if real.startswith(root + os.sep):
                return True
        return False

    # --------------------------------------------------------------- running

    def url(self, path: str = "/") -> str:
        if not self.port:
            return ""
        if not path.startswith("/"):
            path = "/" + path
        joiner = "&" if "?" in path else "?"
        return f"http://{LOOPBACK}:{self.port}{path}{joiner}t={self.token}"

    def start(self, port: int = 0) -> int:
        """Start serving. Returns the bound port."""
        if self._httpd is not None:
            return self.port
        handler = _make_handler(self)
        self._httpd = _Server((LOOPBACK, port), handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.2},
            daemon=True,
            name="mangasurf-assets",
        )
        self._thread.start()
        logger.info("reader assets on http://%s:%s", LOOPBACK, self.port)
        return self.port

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                logger.debug("asset server shutdown failed", exc_info=True)
        self.port = None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):   # pragma: no cover
        # A reader that navigates away mid-stream produces a broken pipe on
        # every page turn. Logging a traceback for each one is just noise.
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        logger.debug("asset server error from %s", client_address, exc_info=True)


def _parse_range(header: str, size: int):
    """Parse a single ``bytes=`` range. Returns ``(start, end)`` or None."""
    if not header or not header.startswith("bytes="):
        return None
    spec = header[6:].split(",")[0].strip()
    if "-" not in spec:
        return None
    first, _, last = spec.partition("-")
    try:
        if not first:                       # bytes=-500 -> final 500 bytes
            length = int(last)
            if length <= 0:
                return None
            start = max(0, size - length)
            return start, size - 1
        start = int(first)
        end = int(last) if last else size - 1
    except ValueError:
        return None
    if start >= size or start > end:
        return None
    return start, min(end, size - 1)


def _make_handler(server: "AssetServer"):
    from urllib.parse import parse_qs, unquote, urlparse

    class Handler(BaseHTTPRequestHandler):
        server_version = "ReaderM"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):        # quiet by default
            logger.debug("asset %s", args and (args[0] % args[1:]) or "")

        # ------------------------------------------------------------ helpers

        def _deny(self, code: int, message: str = ""):
            body = (message or "").encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        _set_cookie = False

        def _send_cookie(self):
            """Hand the token to the browser once, for relative sub-requests.

            HttpOnly so page scripts cannot read it back out, SameSite=Strict
            so another origin cannot cause an authenticated request, and
            scoped to this server's port on loopback.
            """
            if not self._set_cookie:
                return
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={server.token}; Path=/; HttpOnly; SameSite=Strict")

        def _authorised(self, query) -> bool:
            """Accept the token from the query string, a header, or the cookie.

            The window is opened at ``/?t=<token>``, and that page then pulls
            in its own stylesheets, modules and images by *relative* URL. A
            browser does not copy a query string onto those, so they arrive
            bare. Measured before this: the page loaded, then every
            ``./style.css`` came back 403 and the app rendered as unstyled
            Times New Roman with no JavaScript at all.

            A Referer is not enough on its own either. CSS ``@import`` and JS
            module imports send the *stylesheet or module* as the Referer, not
            the page, so ``theme.css`` and ``themes.js`` were still refused.
            Rather than chase that chain, the first authenticated request sets
            a session cookie and every later asset rides on it.
            """
            supplied = (query.get("t") or [None])[0]
            if supplied is None:
                supplied = self.headers.get("X-ReaderM-Token")
            if supplied is None:
                supplied = self._token_from_cookie()
            if not supplied:
                return False
            return secrets.compare_digest(str(supplied), server.token)

        def _token_from_cookie(self):
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE_NAME:
                    return value or None
            return None

        def _issue_cookie(self, query) -> bool:
            """True when this request carried the token explicitly."""
            supplied = (query.get("t") or [None])[0]
            if supplied is None:
                supplied = self.headers.get("X-ReaderM-Token")
            return bool(supplied) and secrets.compare_digest(
                str(supplied), server.token)


        def _send_file(self, path: str, ctype: str = None):
            try:
                size = os.path.getsize(path)
            except OSError:
                return self._deny(404, "not found")

            ctype = ctype or content_type_for(path)
            rng = _parse_range(self.headers.get("Range"), size)

            if rng is None:
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self._send_cookie()
                self.end_headers()
                if self.command == "HEAD":
                    return
                with open(path, "rb") as fh:
                    self._pump(fh, size)
                return

            start, end = rng
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self._send_cookie()
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(path, "rb") as fh:
                fh.seek(start)
                self._pump(fh, length)

        def _pump(self, fh, remaining: int):
            chunk = 256 * 1024
            try:
                while remaining > 0:
                    block = fh.read(min(chunk, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                pass       # reader moved on; normal during fast page turns

        # ------------------------------------------------------------- routes

        def do_HEAD(self):
            self.do_GET()

        def do_POST(self):
            """The API bridge the front-end falls back to.

            ``app.js`` waits up to three seconds for ``window.pywebview`` and
            then switches to ``POST ./_api/<method>``. Nothing served that, so
            the fallback got a bare ``501 Unsupported method`` from
            ``BaseHTTPRequestHandler`` and every call in the interface failed:
            no settings, no library, no sources -- an app that opens and does
            nothing.

            That path is reached whenever the bridge is late or absent, which
            is exactly the case the fallback exists for.
            """
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            route = unquote(parsed.path)

            self._set_cookie = self._issue_cookie(query)
            if not self._authorised(query):
                return self._deny(403, "forbidden")

            prefix = "/_api/"
            if not route.startswith(prefix):
                return self._deny(404, "not found")

            method = route[len(prefix):].strip("/")
            api = server.api
            if api is None:
                return self._json({"ok": False, "error": "no API attached"}, 503)
            if not method or method.startswith("_"):
                return self._json({"ok": False, "error": "unknown method"}, 404)

            target = getattr(api, method, None)
            if target is None or not callable(target):
                return self._json({"ok": False,
                                   "error": f"unknown method: {method}"}, 404)

            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                return self._json({"ok": False, "error": "bad JSON"}, 400)

            args = payload.get("args") if isinstance(payload, dict) else None
            if not isinstance(args, list):
                args = []

            try:
                result = target(*args)
            except TypeError as exc:
                # Wrong arity from the front-end is a bug worth seeing, not a
                # 500 that looks like the whole app died.
                return self._json({"ok": False, "error": str(exc)}, 400)
            except Exception as exc:               # pragma: no cover
                logger.exception("api call %s failed", method)
                return self._json({"ok": False,
                                   "error": f"{type(exc).__name__}: {exc}"}, 500)

            if result is None:
                result = {"ok": True}
            return self._json(result)

        def _json(self, payload, code: int = 200):
            try:
                body = json.dumps(payload).encode("utf-8")
            except (TypeError, ValueError):
                body = json.dumps({"ok": False,
                                   "error": "result is not JSON"}).encode("utf-8")
                code = 500
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._send_cookie()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            route = unquote(parsed.path)

            if route == "/_ping":
                return self._deny(200, "ok")

            self._set_cookie = self._issue_cookie(query)
            if not self._authorised(query):
                return self._deny(403, "forbidden")

            if route in ("/", "/index.html", "/app", "/app/"):
                return self._asset("app/index.html")

            if route.startswith("/app/"):
                return self._asset(route[len("/app/"):])

            if route == "/engine" or route.startswith("/engine/"):
                rel = route[len("/engine/"):] if route.startswith("/engine/") else ""
                return self._asset(os.path.join("foliate", rel))

            if route in ("/book", "/page"):
                return self._content(query, images_only=(route == "/page"))

            # index.html is served from "/", so its own relative links resolve
            # to "/style.css" and "/app.js" rather than "/app/style.css".
            # Without this they 404 and the app renders unstyled with no
            # JavaScript. Serving the page at its real path would be the other
            # fix, but the window URL is what users copy to their phone, and
            # "/" is the one worth keeping short.
            # Any depth, not just one segment: the HeroUI bundle lives at
            # app/vendor/heroui.js and the page asks for "/vendor/heroui.js",
            # which a `count("/") == 1` test never matched -- the bundle 404'd
            # and window.ReaderMUI was undefined.
            if route != "/":
                candidate = "app" + route
                rel = candidate.lstrip("/")
                if is_safe_relative(rel) and os.path.isfile(
                        os.path.join(server.root, rel)):
                    return self._asset(candidate)

            # The engine is imported as "../foliate/*.js" from a page at "/",
            # which normalises to "/foliate/...".
            if route.startswith("/foliate/"):
                return self._asset(route.lstrip("/"))

            return self._deny(404, "not found")

        def _asset(self, rel: str):
            rel = rel.replace("\\", "/").lstrip("/")
            if not is_safe_relative(rel):
                return self._deny(403, "forbidden")
            path = os.path.join(server.root, rel)
            if not os.path.isfile(path):
                return self._deny(404, "not found")
            self._send_file(path)

        def _content(self, query, images_only: bool):
            raw = (query.get("path") or [""])[0]
            if not raw:
                return self._deny(400, "path required")
            path = os.path.abspath(raw)
            if not os.path.isfile(path):
                return self._deny(404, "not found")
            if not server.is_allowed(path):
                return self._deny(403, "outside the library")
            if images_only:
                if os.path.splitext(path)[1].lower() not in IMAGE_EXTENSIONS:
                    return self._deny(415, "not an image")
            self._send_file(path)

    return Handler
