"""Serve the downloaded library as an OPDS catalog.

    python opdsserve.py                      # http://<this-pc>:8578/opds
    python opdsserve.py --gui                # with a control window
    python opdsserve.py --no-auth            # no username/password

Point Readest (or Panels, KyBook, Chunky, Aldiko, Thorium...) at the printed
URL and your downloads appear as a browsable catalog with covers.

Authentication
--------------
HTTP Basic, because that is what the OPDS spec names and what every reader
implements -- a bearer token in a header, as ``readerm.server`` uses, is not
something an OPDS client can be told about. The password is the same access
token from Settings, so there is one secret to manage rather than two. The
username is ignored; readers demand a field for it, so it is accepted and
discarded rather than being a second thing to remember.

This is plain HTTP on a home network. Do not port-forward it.
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import secrets
import sys
import threading
import time

# Allow running this file directly (python readerm/opdsserve.py, or an IDE's
# "Run file"). Without this the relative imports below have no parent
# package and raise ImportError before anything else happens.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"

try:
    from flask import Flask, Response, abort, request, send_file
except ImportError:                                        # pragma: no cover
    print("Flask is not installed. Run:\n\n    pip install flask\n"
          "\nor install the server extra:\n\n    pip install -e \".[server]\"\n",
          file=sys.stderr)
    raise SystemExit(1)

from . import logs as wclogs
from . import opds
from .opds import DEFAULT_PORT, PAGE_SIZE

logger = logging.getLogger("readerm.opdsserve")


class OpdsLog:
    """A ring of readable lines for the control window.

    Same shape as ServerLog in readerm/server.py so the window's polling
    code is identical; kept separate because the two servers run
    independently and mixing their logs would be confusing.
    """

    LIMIT = 600

    def __init__(self, verbose=False):
        self.verbose = verbose
        self._lines = []
        self._seq = 0
        self._lock = threading.Lock()

    def add(self, level, message, verbose_only=False):
        if verbose_only and not self.verbose:
            return
        with self._lock:
            self._seq += 1
            self._lines.append({"seq": self._seq,
                                "time": time.strftime("%H:%M:%S"),
                                "level": level, "text": str(message)})
            if len(self._lines) > self.LIMIT:
                del self._lines[:len(self._lines) - self.LIMIT]

    def since(self, cursor=0):
        with self._lock:
            return self._seq, [l for l in self._lines if l["seq"] > cursor]

    def clear(self):
        with self._lock:
            self._lines = []


def create_app(token=None, log=None):
    """Build the OPDS Flask app. Separate so tests can drive it."""
    log = log if log is not None else OpdsLog()
    app = Flask(__name__)
    app.config["OPDS_TOKEN"] = token
    app.config["OPDS_LOG"] = log

    def base_url():
        """The absolute prefix every link in the feed must use.

        Relative hrefs are legal, but several readers resolve them against
        the wrong base after following a redirect, and the resulting 404s
        look like an empty library. Absolute URLs sidestep it.
        """
        return request.url_root.rstrip("/")

    # ------------------------------------------------------------ auth

    def authorised():
        if not token:
            return True
        header = request.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                raw = base64.b64decode(header[6:]).decode("utf-8", "replace")
            except Exception:
                return False
            # The username is whatever the reader asked the user to type;
            # only the password carries the secret.
            _user, _, password = raw.partition(":")
            return secrets.compare_digest(password, token)
        # A token in the query string helps for a quick browser check.
        supplied = request.args.get("token")
        return bool(supplied) and secrets.compare_digest(supplied, token)

    def challenge():
        log.add("warn", f"Rejected {request.path} from {_client()} "
                        "- bad or missing password")
        return Response(
            "Authentication required", 401,
            {"WWW-Authenticate": 'Basic realm="ReaderM library"'})

    def _client():
        return request.headers.get("X-Forwarded-For") or request.remote_addr

    def xml(body, content_type):
        return Response(body, mimetype=content_type,
                        headers={"Cache-Control": "no-cache"})

    _seen = set()

    @app.before_request
    def note_client():
        who = _client()
        if who and who not in _seen:
            _seen.add(who)
            log.add("info", f"Reader connected: {who}")

    # ------------------------------------------------------------ feeds

    @app.get("/")
    def index():
        """A human landing page; readers want /opds."""
        if not authorised():
            return challenge()
        rows = opds.library_rows()
        return Response(_LANDING % {
            "count": len(rows),
            "url": base_url() + "/opds",
        }, mimetype="text/html")

    @app.get("/opds")
    @app.get("/opds/")
    def root():
        if not authorised():
            return challenge()
        rows = opds.library_rows()
        log.add("call", f"root feed ({len(rows)} titles)", verbose_only=True)
        return xml(opds.navigation_feed(base_url(), rows), opds.NAV_TYPE)

    def _page():
        try:
            return max(0, int(request.args.get("page", 0)))
        except (TypeError, ValueError):
            return 0

    @app.get("/opds/all")
    def all_titles():
        if not authorised():
            return challenge()
        rows = sorted(opds.library_rows(), key=lambda r: r["title"].lower())
        log.add("call", f"all titles, page {_page()}", verbose_only=True)
        return xml(opds.acquisition_feed(base_url(), rows, "All titles",
                                         "/opds/all", _page()), opds.ACQ_TYPE)

    @app.get("/opds/recent")
    def recent():
        if not authorised():
            return challenge()
        rows = opds.library_rows()           # already newest-first
        log.add("call", f"recent, page {_page()}", verbose_only=True)
        return xml(opds.acquisition_feed(base_url(), rows, "Recently added",
                                         "/opds/recent", _page()),
                   opds.ACQ_TYPE)

    @app.get("/opds/sources")
    def sources():
        if not authorised():
            return challenge()
        groups = opds.group_by_source(opds.library_rows())
        entries = []
        for name in sorted(groups):
            path = f"/opds/source/{name}"
            entries.append(
                "  <entry>\n"
                f"    {opds.element('title', name)}\n"
                f"    {opds.element('id', opds.stable_id('src', name))}\n"
                f"    {opds.element('updated', opds._now_rfc3339())}\n"
                f"    {opds.element('content', f'{len(groups[name])} titles', type='text')}\n"
                f"  {opds.link('subsection', base_url() + path, opds.ACQ_TYPE)}\n"
                "  </entry>")
        return xml(opds.feed(
            opds.stable_id("sources"), "By source", entries,
            [opds.link("self", base_url() + "/opds/sources", opds.NAV_TYPE),
             opds.link("start", base_url() + "/opds", opds.NAV_TYPE),
             opds.link("up", base_url() + "/opds", opds.NAV_TYPE)]),
            opds.NAV_TYPE)

    @app.get("/opds/source/<name>")
    def by_source(name):
        if not authorised():
            return challenge()
        rows = opds.group_by_source(opds.library_rows()).get(name, [])
        return xml(opds.acquisition_feed(
            base_url(), rows, name, f"/opds/source/{name}", _page(),
            facets=False), opds.ACQ_TYPE)

    @app.get("/opds/letters")
    def letters():
        if not authorised():
            return challenge()
        groups = opds.group_by_letter(opds.library_rows())
        entries = []
        for letter in groups:
            path = f"/opds/letter/{letter}"
            entries.append(
                "  <entry>\n"
                f"    {opds.element('title', letter)}\n"
                f"    {opds.element('id', opds.stable_id('letter', letter))}\n"
                f"    {opds.element('updated', opds._now_rfc3339())}\n"
                f"    {opds.element('content', f'{len(groups[letter])} titles', type='text')}\n"
                f"  {opds.link('subsection', base_url() + path, opds.ACQ_TYPE)}\n"
                "  </entry>")
        return xml(opds.feed(
            opds.stable_id("letters"), "Alphabetical", entries,
            [opds.link("self", base_url() + "/opds/letters", opds.NAV_TYPE),
             opds.link("start", base_url() + "/opds", opds.NAV_TYPE),
             opds.link("up", base_url() + "/opds", opds.NAV_TYPE)]),
            opds.NAV_TYPE)

    @app.get("/opds/letter/<letter>")
    def by_letter(letter):
        if not authorised():
            return challenge()
        rows = opds.group_by_letter(opds.library_rows()).get(letter, [])
        return xml(opds.acquisition_feed(
            base_url(), rows, f"Titles: {letter}", f"/opds/letter/{letter}",
            _page(), facets=False), opds.ACQ_TYPE)

    @app.get("/opds/search.xml")
    def search_document():
        if not authorised():
            return challenge()
        return xml(opds.opensearch_document(base_url()), opds.SEARCH_TYPE)

    @app.get("/opds/search")
    def search():
        if not authorised():
            return challenge()
        query = request.args.get("q", "")
        rows = opds.search_rows(opds.library_rows(), query)
        log.add("info", f"Search '{query}' -> {len(rows)} results")
        return xml(opds.acquisition_feed(
            base_url(), rows, f"Search: {query}",
            f"/opds/search?q={query}", _page(), facets=False), opds.ACQ_TYPE)

    # -------------------------------------------------------- resources

    def _row_by_id(short_id):
        for row in opds.library_rows():
            if row["id"].split(":")[-1] == short_id:
                return row
        return None

    @app.get("/opds/cover/<short_id>")
    def cover(short_id):
        if not authorised():
            return challenge()
        row = _row_by_id(short_id)
        if not row or not row["cover"]:
            abort(404)
        return send_file(row["cover"],
                         mimetype=opds.image_type_for(row["cover"]))

    @app.get("/opds/download/<short_id>/<int:index>")
    def download(short_id, index):
        if not authorised():
            return challenge()
        row = _row_by_id(short_id)
        if not row or index >= len(row["files"]):
            abort(404)
        path = row["files"][index]
        if not os.path.isfile(path):
            log.add("error", f"Missing file for {row['title']}: {path}")
            abort(404)
        log.add("info", f"Sending {os.path.basename(path)} to {_client()}")
        return send_file(path, mimetype=opds.media_type_for(path),
                         as_attachment=True,
                         download_name=os.path.basename(path))

    @app.get("/opds/_ping")
    def ping():
        return {"ok": True, "app": "readerm-opds",
                "auth": bool(token),
                "titles": len(opds.library_rows())}

    @app.get("/opds/_log")
    def read_log():
        if not authorised():
            return challenge()
        try:
            cursor = int(request.args.get("since", 0))
        except (TypeError, ValueError):
            cursor = 0
        seq, lines = log.since(cursor)
        return {"ok": True, "cursor": seq, "lines": lines,
                "verbose": log.verbose}

    return app


_LANDING = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ReaderM library</title><style>
body{background:#0b0a12;color:#f2f0ff;font:15px/1.6 system-ui,sans-serif;
display:grid;place-items:center;min-height:100vh;margin:0;text-align:center}
div{max-width:44ch;padding:26px}
code{background:#1c1b28;padding:3px 8px;border-radius:6px;font-size:13px;
word-break:break-all;display:inline-block;margin-top:6px}
h1{font-size:22px;margin-bottom:6px}
p{color:#a8a3c4}
</style></head><body><div>
<h1>ReaderM library</h1>
<p>%(count)s titles, served as an OPDS catalog.</p>
<p>Add this URL in Readest, Panels, KyBook or any OPDS reader:</p>
<code>%(url)s</code>
<p style="margin-top:18px;font-size:13px">Use your access token as the
<b>password</b>. Any username works.</p>
</div></body></html>"""


# ------------------------------------------------------------------ running


def build_url(host, port, token=None):
    from .server import local_ip

    address = local_ip() if host in ("0.0.0.0", "") else host
    return f"http://{address}:{port}/opds"


def serve(host="0.0.0.0", port=None, token=None, no_auth=False,
          verbose=None, log=None, on_ready=None, debug=False):
    """Run the OPDS server. Shared by the CLI and the control window."""
    from .servercfg import load_server_settings

    stored = load_server_settings()
    port = int(port or opds_port())
    token = None if no_auth else (token or stored["token"]).strip()
    if verbose is None:
        verbose = stored["verbose"]

    log = log if log is not None else OpdsLog(verbose=bool(verbose))
    log.verbose = bool(verbose)

    app = create_app(token=token, log=log)
    url = build_url(host, port, token)

    rows = opds.library_rows()
    log.add("info", f"Serving {len(rows)} titles on port {port}")
    log.add("info", f"Catalog URL: {url}")
    if token:
        log.add("info", f"Password: {token}  (any username)")
    else:
        log.add("warn", "Running with NO password (--no-auth)")

    if on_ready:
        try:
            on_ready(url, app, log)
        except Exception:
            logger.exception("on_ready callback failed")

    try:
        app.run(host=host, port=port, debug=debug, threaded=True,
                use_reloader=False)
    except OSError as exc:
        log.add("error", f"Could not bind port {port}: {exc}")
        raise
    return app


def opds_port():
    """The OPDS port from settings, defaulting beside the app server."""
    from .config import load_settings

    try:
        value = int(load_settings().get("opds_port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT
    return value if 1 <= value <= 65535 else DEFAULT_PORT


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="readerm opds",
        description="Serve your downloaded library as an OPDS catalog, so "
                    "Readest and other readers can browse it.")
    parser.add_argument("--host", default="0.0.0.0",
                        help="interface to bind (default: all, so other "
                             "devices can reach it)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"port (default: from Settings, or {DEFAULT_PORT})")
    parser.add_argument("--no-auth", action="store_true",
                        help="serve without a password (trusted networks only)")
    parser.add_argument("--token", default=None,
                        help="override the saved token for this run")
    parser.add_argument("--verbose", action="store_true", default=None,
                        help="log every request")
    parser.add_argument("--gui", action="store_true",
                        help="open the control window instead of running "
                             "headless in this terminal")
    parser.add_argument("--debug", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    wclogs.setup_logging()

    if args.gui:
        from .opdsui import run_opds_window
        return run_opds_window(host=args.host, port=args.port,
                               token=args.token, no_auth=args.no_auth,
                               verbose=args.verbose)

    from .servercfg import load_server_settings
    stored = load_server_settings()
    port = args.port or opds_port()
    token = None if args.no_auth else (args.token or stored["token"])
    url = build_url(args.host, port, token)
    count = len(opds.library_rows())

    line = "\u2500" * 62
    print(f"\n{line}")
    print("  ReaderM OPDS catalog")
    print(f"{line}")
    print(f"  Titles         {count}")
    print(f"  Catalog URL    {url}")
    print(f"  On this PC     http://localhost:{port}/opds")
    if token:
        print(f"\n  Password       {token}")
        print("  Username       anything (ignored)")
        print("  Change it in the app: Settings -> Phone server")
    else:
        print("\n  Password       DISABLED (--no-auth)")
    print("\n  Add the catalog URL in Readest, Panels, KyBook or similar.")
    print(f"{line}\n")

    if not count:
        print("  Nothing downloaded yet - the catalog will be empty until\n"
              "  you download something.\n")

    try:
        serve(host=args.host, port=port, token=args.token,
              no_auth=args.no_auth, verbose=args.verbose, debug=args.debug)
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"\n[ReaderM] Could not start the OPDS server: {exc}\n",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
