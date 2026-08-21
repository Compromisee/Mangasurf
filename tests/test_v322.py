"""v3.2.2 — the API fallback the front-end relies on returned 501.

``app.js`` waits up to three seconds for ``window.pywebview`` and then falls
back to ``POST ./_api/<method>``. Nothing served that route, so the fallback
got a bare ``501 Unsupported method`` from ``BaseHTTPRequestHandler`` and every
call failed: no settings, no library, no sources -- an app that opens and then
does nothing.

That path is reached whenever the bridge is late or missing, which is exactly
what the fallback is for.
"""
import json
import os
import sys
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class _Api:
    """A stand-in with one of everything the bridge has to cope with."""

    def __init__(self):
        self.seen = []

    def echo(self, *args):
        self.seen.append(args)
        return {"ok": True, "args": list(args)}

    def needs_one(self, value):
        return {"ok": True, "value": value}

    def returns_none(self):
        return None

    def not_json(self):
        return {"ok": True, "thing": object()}

    def explodes(self):
        raise RuntimeError("boom")

    def _private(self):
        return {"ok": True}

    not_callable = "a string"


@pytest.fixture()
def server():
    from mangasurf.reader.assets import AssetServer

    api = _Api()
    srv = AssetServer(api=api)
    srv.start()
    srv.test_api = api
    yield srv
    srv.stop()


def post(server, method, args=None, token=True, raw=None):
    url = f"http://127.0.0.1:{server.port}/_api/{method}"
    body = raw if raw is not None else json.dumps({"args": args or []}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Cookie"] = f"readerm_token={server.token}"
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers=headers)
    try:
        response = urllib.request.urlopen(request, timeout=10)
        return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_the_api_route_answers_at_all(server):
    """A bare BaseHTTPRequestHandler replies 501 to any POST."""
    status, _ = post(server, "echo")
    assert status == 200, f"the bridge fallback returned {status}"


def test_arguments_reach_the_method(server):
    status, body = post(server, "echo", ["one", 2, True])
    assert status == 200
    assert json.loads(body)["args"] == ["one", 2, True]


def test_a_method_returning_none_is_reported_as_ok(server):
    """pywebview turns None into null; the UI checks `res?.ok`, so a bare
    null would read as a failure."""
    status, body = post(server, "returns_none")
    assert status == 200
    assert json.loads(body) == {"ok": True}


def test_an_unknown_method_is_a_clean_json_404(server):
    status, body = post(server, "no_such_thing")
    assert status == 404
    payload = json.loads(body)
    assert payload["ok"] is False
    assert "no_such_thing" in payload["error"]


def test_private_methods_are_not_reachable(server):
    status, body = post(server, "_private")
    assert status == 404
    assert json.loads(body)["ok"] is False


def test_a_non_callable_attribute_is_not_reachable(server):
    status, body = post(server, "not_callable")
    assert status == 404
    assert json.loads(body)["ok"] is False


def test_wrong_arity_is_a_message_not_a_500(server):
    """A front-end bug should say what is wrong, not look like a dead app."""
    status, body = post(server, "needs_one")
    assert status == 400
    assert "needs_one" in json.loads(body)["error"]


def test_a_raising_method_returns_json_not_a_stack_page(server):
    status, body = post(server, "explodes")
    assert status == 500
    payload = json.loads(body)
    assert payload["ok"] is False
    assert "boom" in payload["error"]


def test_an_unserialisable_result_does_not_kill_the_connection(server):
    status, body = post(server, "not_json")
    assert status == 500
    assert json.loads(body)["ok"] is False


def test_malformed_json_is_refused_politely(server):
    status, body = post(server, "echo", raw=b"{not json at all")
    assert status == 400
    assert json.loads(body)["ok"] is False


def test_a_missing_body_is_treated_as_no_arguments(server):
    status, body = post(server, "echo", raw=b"")
    assert status == 200
    assert json.loads(body)["args"] == []


def test_args_that_are_not_a_list_are_ignored(server):
    status, body = post(server, "echo", raw=json.dumps({"args": "nope"}).encode())
    assert status == 200
    assert json.loads(body)["args"] == []


def test_the_bridge_still_needs_the_token(server):
    status, body = post(server, "echo", token=False)
    assert status == 403
    assert b"forbidden" in body


def test_a_post_outside_the_api_prefix_is_refused_as_a_route(server):
    """Both the prefix check and the method lookup answer 404, so the status
    alone proves nothing: with the prefix check removed, "POST /style.css"
    still 404s as an unknown method. The body is what distinguishes a route
    that does not exist from a method that does not exist.
    """
    url = f"http://127.0.0.1:{server.port}/style.css"
    request = urllib.request.Request(
        url, data=b"{}", method="POST",
        headers={"Cookie": f"readerm_token={server.token}"})
    try:
        response = urllib.request.urlopen(request, timeout=10)
        status, body = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    assert status == 404
    assert b"not found" in body, body
    assert b"unknown method" not in body, "fell through to the method lookup"


def test_a_server_with_no_api_says_so(server):
    from mangasurf.reader.assets import AssetServer

    bare = AssetServer()
    bare.start()
    try:
        status, body = post(bare, "echo")
        assert status == 503
        assert json.loads(body)["ok"] is False
    finally:
        bare.stop()


# ─────────────────────────────────────────────────── wired to the real Api


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from mangasurf.gui import Api

    api = Api()
    api.reader_info()
    server = api._asset_server()
    yield server
    server.stop()
    from mangasurf.reader.api import ReaderApi
    ReaderApi._assets = None


def test_the_real_api_is_attached_to_the_asset_server(live):
    """Nothing wired the Api in, so the fallback had nothing to call."""
    assert live.api is not None
    assert callable(getattr(live.api, "get_settings", None))


def test_an_asset_server_created_before_the_api_is_adopted(tmp_path, monkeypatch):
    """`_assets` is a class attribute shared by every Api instance, so a
    server can already exist -- created by another instance, or by a test --
    by the time reader_info() runs. Without the late-attach branch that
    server keeps `api = None` for the rest of the session and the HTTP
    fallback answers 503 forever.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    from mangasurf.gui import Api
    from mangasurf.reader.api import ReaderApi
    from mangasurf.reader.assets import AssetServer

    orphan = AssetServer()          # no api, exactly like the old code path
    orphan.start()
    ReaderApi._assets = orphan
    try:
        api = Api()
        api.reader_info()
        assert orphan.api is not None, "an existing server never got the Api"
        status, body = post(orphan, "get_settings")
        assert status == 200, body
    finally:
        orphan.stop()
        ReaderApi._assets = None


@pytest.mark.parametrize("method", [
    "get_settings", "get_sources", "get_filters", "get_stats",
    "reader_library", "reader_recent", "get_queue",
])
def test_the_calls_the_interface_makes_on_boot_all_work(live, method):
    status, body = post(live, method)
    assert status == 200, f"{method} -> {status}"
    payload = json.loads(body)
    assert isinstance(payload, dict)
    assert payload.get("ok") is not False, payload


def test_settings_come_back_populated(live):
    status, body = post(live, "get_settings")
    assert status == 200
    payload = json.loads(body)
    settings = payload.get("settings", payload)
    assert len(settings) > 20, "the interface would boot with no preferences"
    assert "theme" in settings


def test_the_front_end_still_declares_the_fallback():
    """If app.js stops using /_api/ this whole route is dead code, and the
    next person should be told rather than left guessing."""
    app = open(os.path.join(ROOT, "mangasurf", "reader", "app", "app.js"),
               encoding="utf-8").read()
    assert "./_api/" in app
    assert "window.pywebview" in app
