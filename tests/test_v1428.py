"""v1.4.28: aggregate-member downloads, and the LAN server.

**The bug.** Downloading from a Madara member died with::

    ScrapeError: Unknown source 'madara.manhuatop'

Aggregate members ("madara.toonily") are real sources that are NOT in the
registry -- only their parent is. v1.4.20 taught ``Api._source()`` to
resolve them, which fixed cover proxying and browsing, but
``DownloadEngine`` builds its source through ``sources.get_source()``
instead. So the series page loaded and the download button failed. The CLI,
the TUI and the cover tools all took the same path and had the same hole.

**The server.** ``server.py`` serves the desktop UI to a phone, with every
call executed on the host.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    return open(path, encoding="utf-8").read()


# ================================================= aggregate members


def member_ids():
    import mangasurf.sources.madaranet as madaranet
    return [cls.id for cls in madaranet.MEMBERS]


def test_every_member_resolves_through_get_source():
    """The exact call the download engine makes."""
    from mangasurf.sources import get_source

    for member_id in member_ids():
        source = get_source(member_id)
        try:
            assert source.id == member_id
            assert source.base_url.startswith("http")
        finally:
            source.close()


def test_the_reported_id_specifically():
    from mangasurf.sources import get_source

    source = get_source("madara.manhuatop")
    try:
        assert source.name == "Manhua Top"
    finally:
        source.close()


def test_download_engine_accepts_a_member_source():
    """The reproduction: this raised ScrapeError before the fix."""
    from mangasurf.downloader import DownloadEngine, DownloadOptions

    engine = DownloadEngine(DownloadOptions(
        url="https://manhuatop.org/manga/example/", source="madara.manhuatop"))
    assert engine.source.id == "madara.manhuatop"
    assert engine.source.name == "Manhua Top"


def test_unknown_members_still_fail_loudly():
    """The fix must not turn every typo into a silent MangaDex."""
    from mangasurf.sources import get_source
    from mangasurf.sources.base import ScrapeError

    for bogus in ("madara.nope", "notaprefix.thing", "madara."):
        with pytest.raises(ScrapeError):
            get_source(bogus)


def test_plain_sources_are_unaffected():
    from mangasurf.sources import get_source

    for source_id in ("mangadex", "madaranet", "madarascans"):
        source = get_source(source_id)
        try:
            assert source.id == source_id
        finally:
            source.close()


def test_resolve_member_detects_the_capability_not_a_name():
    """MEMBERS is a module constant in madaranet.py, not a class attribute.

    An earlier version of this fix used ``hasattr(cls, "MEMBERS")``, which
    is False, so it silently fell through to "Unknown source" again.
    """
    from mangasurf.sources import SOURCES, resolve_member

    parent = SOURCES["madaranet"]
    assert not hasattr(parent, "MEMBERS"), (
        "if MEMBERS became a class attribute, simplify resolve_member")
    member = resolve_member("madara.toonily")
    assert member is not None
    member.close()


def test_resolve_member_returns_none_for_plain_ids():
    from mangasurf.sources import resolve_member

    assert resolve_member("mangadex") is None
    assert resolve_member("") is None
    assert resolve_member(None) is None


def test_the_gui_uses_the_shared_resolver():
    """Two copies of this logic is how the bug happened in the first place."""
    source = read(os.path.join(ROOT, "mangasurf", "gui", "__init__.py"))
    body = source[source.index("def _source(self"):]
    body = body[:body.index("\n    # ---")]
    assert "resolve_member" in body
    assert 'parent = "madaranet"' not in body, (
        "the GUI still carries its own member-resolution copy")


def test_covers_and_cli_go_through_the_same_door():
    """These call get_source() directly, so the registry fix covers them."""
    from mangasurf.sources import get_source

    source = get_source("madara.mangaowl")
    try:
        assert source.id == "madara.mangaowl"
    finally:
        source.close()


# ========================================================== server.py


flask = pytest.importorskip("flask", reason="flask is not installed")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import importlib

    from mangasurf import server as server_module
    importlib.reload(server_module)
    application = server_module.create_app(token="unit-test-token")
    application.config["TESTING"] = True
    return application, server_module


def post(client, method, args=None, token="unit-test-token"):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-ReaderM-Token"] = token
    return client.post(f"/api/{method}",
                       data=json.dumps({"args": args or []}),
                       headers=headers)


def test_a_call_without_a_token_is_rejected(app):
    application, _ = app
    with application.test_client() as client:
        assert post(client, "get_settings", token=None).status_code == 401


def test_a_wrong_token_is_rejected(app):
    application, _ = app
    with application.test_client() as client:
        assert post(client, "get_settings", token="nope").status_code == 401


def test_a_valid_call_runs_on_the_host(app):
    application, _ = app
    with application.test_client() as client:
        response = post(client, "get_settings")
        assert response.status_code == 200
        assert "theme" in response.get_json()["result"]


def test_arbitrary_api_methods_are_reachable(app):
    """The bridge is generic on purpose: 113 endpoints, no hand-written list
    to fall out of date."""
    application, _ = app
    with application.test_client() as client:
        sources = post(client, "get_sources").get_json()["result"]
        assert len(sources["sources"]) >= 19


def test_shutdown_is_not_reachable_over_http(app):
    """It would tear down the server answering the request."""
    application, _ = app
    with application.test_client() as client:
        assert post(client, "shutdown").status_code == 403


def test_private_methods_are_not_reachable(app):
    application, _ = app
    with application.test_client() as client:
        assert post(client, "_push", [{}]).status_code == 404
        assert post(client, "_flush").status_code == 404


def test_unknown_methods_404(app):
    application, _ = app
    with application.test_client() as client:
        assert post(client, "definitely_not_a_method").status_code == 404


def test_file_pickers_explain_themselves(app):
    """A native dialog would open on the host's screen, unseen. Saying so
    beats appearing to hang."""
    application, _ = app
    with application.test_client() as client:
        for method in ("choose_folder", "choose_file"):
            body = post(client, method).get_json()
            assert body["ok"] is False
            assert "path" in body["error"].lower()


def test_a_bad_arity_call_returns_an_error_not_a_crash(app):
    """Every Api method is wrapped by _safe_endpoint, which turns any
    exception into {"ok": False, "error": ...} before the server sees it.

    So a wrong-arity call arrives as a normal 200 carrying an error, not as
    a raised TypeError. That is the better contract -- the UI already knows
    that shape -- so the test asserts it rather than the 400 I first
    assumed. The 400 path in server.py still covers anything that manages
    to raise past the wrapper.
    """
    application, _ = app
    with application.test_client() as client:
        response = post(client, "get_settings", ["unexpected", "args"])
        assert response.status_code in (200, 400)
        body = response.get_json()
        payload = body.get("result", body)
        assert payload.get("ok") is False
        assert "argument" in payload.get("error", "").lower()


def test_an_api_exception_becomes_a_clean_error(app):
    application, server_module = app
    api = application.config["READERM_API"]

    def boom():
        raise RuntimeError("engine exploded")

    api.get_health = boom
    with application.test_client() as client:
        response = post(client, "get_health")
        assert response.status_code == 500
        assert "engine exploded" in response.get_json()["error"]


def test_the_page_carries_the_bridge(app):
    application, _ = app
    with application.test_client() as client:
        html = client.get("/?token=unit-test-token").get_data(as_text=True)
        assert "/bridge.js" in html
        assert "app.js" in html
        # The bridge must come first, or app.js boots with no pywebview.
        # Compared against the *script tag*, not any mention of the name:
        # index.html now discusses app.js in a comment near the top, so a bare
        # substring search matched the comment and failed on correct markup.
        assert html.index("/bridge.js") < html.index(
            '<script type="module" src="./app.js">')


def test_the_page_without_a_token_explains_itself(app):
    application, _ = app
    with application.test_client() as client:
        response = client.get("/")
        assert response.status_code == 401
        assert "token" in response.get_data(as_text=True).lower()


def test_the_bridge_implements_the_pywebview_shape(app):
    application, _ = app
    with application.test_client() as client:
        js = client.get("/bridge.js").get_data(as_text=True)
        assert "window.pywebview" in js
        assert "pywebviewready" in js, "app.js waits for this before booting"
        assert "onEngineEvents" in js, "engine events would never arrive"
        assert "unit-test-token" in js


def test_no_path_traversal(app):
    """Note: Werkzeug normalises the URL before routing, so these are
    already refused without server.py's own check -- confirmed by removing
    it and re-running these attacks. The assertion is on the outcome the
    user cares about, so it holds whichever layer does the work."""
    application, _ = app
    with application.test_client() as client:
        for attack in ("../../../etc/passwd", "..%2f..%2fserver.py",
                       "....//....//etc/passwd", "../server.py"):
            response = client.get(f"/{attack}")
            assert response.status_code in (400, 404), attack
            assert b"root:" not in response.get_data(), attack


def test_events_are_buffered_for_polling(app):
    """A browser has no evaluate_js channel, so events must be pullable."""
    application, _ = app
    api = application.config["READERM_API"]
    api._push({"type": "status", "message": "hello"})
    api._flush()

    with application.test_client() as client:
        body = client.get("/api/_events?since=0&token=unit-test-token"
                          ).get_json()
        assert body["ok"] is True
        assert any(e.get("message") == "hello" for e in body["events"])
        assert body["cursor"] >= 1


def test_the_event_cursor_advances(app):
    application, _ = app
    api = application.config["READERM_API"]
    with application.test_client() as client:
        api._push({"type": "status", "message": "one"})
        api._flush()
        first = client.get("/api/_events?since=0&token=unit-test-token").get_json()

        api._push({"type": "status", "message": "two"})
        api._flush()
        second = client.get(
            f"/api/_events?since={first['cursor']}&token=unit-test-token"
        ).get_json()

    assert [e["message"] for e in second["events"]] == ["two"], (
        "polling replayed events the client had already seen")


def test_a_stale_cursor_does_not_hang_forever(app):
    """A phone reconnecting after the server restarted holds a cursor from
    the previous run, which is higher than anything we will ever emit."""
    application, _ = app
    api = application.config["READERM_API"]
    api._push({"type": "status", "message": "fresh"})
    api._flush()

    with application.test_client() as client:
        started = time.time()
        body = client.get("/api/_events?since=999999&token=unit-test-token"
                          ).get_json()
        assert time.time() - started < 10, "a stale cursor blocked the poll"
        assert body["events"], "the client would never see anything again"


def test_the_buffer_is_bounded(app):
    """A long download emits thousands of progress events."""
    application, server_module = app
    buffer = server_module.EventBuffer()
    for i in range(buffer.LIMIT + 500):
        buffer.push({"type": "chapter_progress", "n": i})
    assert len(buffer._events) <= buffer.LIMIT


def test_events_reach_the_buffer_from_the_api(app):
    """ServerApi must actually redirect _flush; Api._push returns early when
    self.window is None, so a naive subclass emits nothing at all."""
    application, _ = app
    api = application.config["READERM_API"]
    buffer = application.config["READERM_BUFFER"]
    before = buffer.cursor()
    api._push({"type": "status", "message": "routed"})
    api._flush()
    assert buffer.cursor() > before, "events never left the Api"


def test_ping_needs_no_token(app):
    """So a phone can tell 'wrong token' from 'wrong address'."""
    application, _ = app
    with application.test_client() as client:
        body = client.get("/api/_ping").get_json()
        assert body["ok"] is True
        assert body["auth"] is True
        assert body["authorised"] is False


def test_no_auth_mode_allows_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import importlib

    from mangasurf import server as server_module
    importlib.reload(server_module)
    application = server_module.create_app(token=None)
    with application.test_client() as client:
        response = client.post("/api/get_settings",
                               data=json.dumps({"args": []}),
                               headers={"Content-Type": "application/json"})
        assert response.status_code == 200


def test_local_ip_is_not_loopback_shaped(tmp_path, monkeypatch):
    """gethostbyname(gethostname()) returns 127.0.1.1 on most Linux boxes,
    which is useless to a phone."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    from mangasurf import server as server_module

    address = server_module.local_ip()
    assert address.count(".") == 3
    assert not address.startswith("127.0.1.")


def test_docs_mention_the_server():
    # FEATURES.md moved into MD/ in 1.0.1; README.md stays at the root.
    for name in ("README.md", os.path.join("MD", "FEATURES.md")):
        assert "server.py" in read(os.path.join(ROOT, name)), name


# ------------------------------------------------------- end to end


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_the_server_actually_serves(tmp_path):
    """Start it as a real process, as the user would."""
    port = free_port()
    env = dict(os.environ, HOME=str(tmp_path))
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--host", "127.0.0.1",
         "--port", str(port), "--token", "e2e"],
        cwd=ROOT, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        up = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{base}/api/_ping", timeout=2):
                    up = True
                    break
            except Exception:
                time.sleep(0.25)
        assert up, "the server never started"

        request = urllib.request.Request(
            f"{base}/api/get_sources", data=b'{"args":[]}',
            headers={"Content-Type": "application/json",
                     "X-ReaderM-Token": "e2e"})
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
        assert len(payload["result"]["sources"]) >= 19

        with urllib.request.urlopen(f"{base}/?token=e2e", timeout=10) as page:
            html = page.read().decode("utf-8")
        assert "/bridge.js" in html
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
