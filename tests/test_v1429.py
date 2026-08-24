"""v1.4.29: a settings-backed server token, a server window, and landing.py.

The token used to be ``secrets.token_urlsafe(12)`` regenerated on every
launch, so the phone had to be re-paired each restart and any bookmarked
link stopped working. It is now a saved setting with a 16-character minimum,
validated in one place that all three UIs share.
"""

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


def read(path):
    return open(path, encoding="utf-8").read()


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import config, servercfg
    importlib.reload(config)
    importlib.reload(servercfg)
    return servercfg


# ==================================================== token validation


def test_the_minimum_is_sixteen(home):
    assert home.MIN_TOKEN_LENGTH == 16
    assert home.validate_token("a" * 15)[0] is False
    assert home.validate_token("a" * 16)[0] is True


def test_short_tokens_say_how_short(home):
    ok, message = home.validate_token("abc")
    assert ok is False
    assert "3" in message and "16" in message, message


def test_an_empty_token_is_rejected(home):
    assert home.validate_token("")[0] is False
    assert home.validate_token(None)[0] is False
    assert home.validate_token("   ")[0] is False


def test_url_unsafe_characters_are_rejected(home):
    """The token travels in a query string; anything needing percent-encoding
    makes the printed link wrong when retyped."""
    for bad in ("has space here!", "quote'sinit here", "sla/shes/in/it",
                "amp&ersand&here", "hash#inside#it"):
        assert home.validate_token(bad)[0] is False, bad


def test_url_safe_punctuation_is_allowed(home):
    assert home.validate_token("My-Token_2026.x~ok")[0] is True


def test_generated_tokens_pass_their_own_validator(home):
    for _ in range(50):
        token = home.generate_token()
        assert len(token) >= home.MIN_TOKEN_LENGTH
        assert home.validate_token(token)[0] is True, token


def test_generated_tokens_avoid_confusable_characters(home):
    """This string gets copied off a screen by hand."""
    joined = "".join(home.generate_token() for _ in range(40))
    for confusable in "lI10O":
        assert confusable not in joined, confusable


def test_generated_tokens_differ(home):
    assert len({home.generate_token() for _ in range(20)}) == 20


# ================================================== persistence


def test_a_token_is_created_and_saved_on_first_use(home):
    first = home.load_server_settings()["token"]
    assert home.validate_token(first)[0] is True
    # The whole point: the same token next time, not a new one.
    assert home.load_server_settings()["token"] == first


def test_the_token_survives_a_reload(home, tmp_path, monkeypatch):
    """A fresh process must agree with the one that printed the link."""
    first = home.load_server_settings()["token"]
    import importlib

    from readerm import config, servercfg
    importlib.reload(config)
    importlib.reload(servercfg)
    assert servercfg.load_server_settings()["token"] == first


def test_a_custom_token_is_kept(home):
    ok, _msg, cfg = home.save_server_settings(token="MyChosenToken2026")
    assert ok
    assert cfg["token"] == "MyChosenToken2026"
    assert home.load_server_settings()["token"] == "MyChosenToken2026"


def test_a_rejected_token_does_not_overwrite_the_good_one(home):
    home.save_server_settings(token="AGoodLongToken123")
    ok, _msg, _cfg = home.save_server_settings(token="short")
    assert ok is False
    assert home.load_server_settings()["token"] == "AGoodLongToken123", (
        "a rejected value replaced the working token")


def test_a_corrupt_stored_token_is_replaced(home):
    """Someone hand-editing config.json must not lock the server out."""
    from mangasurf.config import update_settings

    update_settings({"server_token": "xx"})
    token = home.load_server_settings()["token"]
    assert home.validate_token(token)[0] is True
    assert token != "xx"


def test_port_bounds(home):
    assert home.save_server_settings(port=80)[0] is False
    assert home.save_server_settings(port=70000)[0] is False
    assert home.save_server_settings(port="nonsense")[0] is False
    assert home.save_server_settings(port=9000)[0] is True
    assert home.load_server_settings()["port"] == 9000


def test_a_corrupt_port_falls_back(home):
    from mangasurf.config import update_settings

    update_settings({"server_port": "banana"})
    assert home.load_server_settings()["port"] == 8577


def test_the_settings_have_defaults():
    from mangasurf.gui import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["server_token"] == ""
    assert DEFAULT_SETTINGS["server_port"] == 8577
    assert DEFAULT_SETTINGS["server_verbose"] is False


def test_no_randomised_token_at_launch():
    """The regression: a token regenerated per run meant re-pairing the
    phone every restart."""
    source = read(os.path.join(ROOT, "readerm", "server.py"))
    assert "token_urlsafe" not in source, (
        "server.py still generates a throwaway token")


# =========================================== the desktop settings panel


def test_the_api_exposes_the_server_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import config, servercfg
    importlib.reload(config)
    importlib.reload(servercfg)
    import mangasurf.gui as gui
    importlib.reload(gui)

    api = gui.Api()
    cfg = api.get_server_config()
    assert cfg["ok"] and cfg["min_length"] == 16
    assert cfg["token"] and cfg["url"].startswith("http")

    assert api.set_server_config(token="tiny")["ok"] is False
    assert api.set_server_config(token="AProperlyLongToken")["ok"] is True
    assert api.get_server_config()["token"] == "AProperlyLongToken"

    generated = api.generate_server_token()
    assert generated["ok"] and len(generated["token"]) >= 16


def test_the_gui_and_the_server_agree(tmp_path, monkeypatch):
    """Two validators would eventually disagree; there must be one."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import config, servercfg
    importlib.reload(config)
    importlib.reload(servercfg)
    import mangasurf.gui as gui
    importlib.reload(gui)

    gui.Api().set_server_config(token="SharedBetweenBoth1")
    assert servercfg.load_server_settings()["token"] == "SharedBetweenBoth1"

    gui_source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = gui_source[gui_source.index("def set_server_config"):]
    body = body[:body.index("def generate_server_token")]
    assert "save_server_settings" in body, (
        "the GUI validates the token itself instead of sharing the helper")


# ====================================================== the server window


def test_the_server_window_module_imports():
    from readerm import serverui

    assert hasattr(serverui, "ServerController")
    assert hasattr(serverui, "run_server_window")
    assert "pywebview" in serverui.PAGE


def test_the_controller_reports_state(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import importlib

    from readerm import config, servercfg, serverui
    importlib.reload(config)
    importlib.reload(servercfg)
    importlib.reload(serverui)

    controller = serverui.ServerController(host="127.0.0.1")
    state = controller.get_state()
    assert state["running"] is False
    assert len(state["token"]) >= 16
    assert state["min_length"] == 16


def test_the_controller_validates_like_everything_else(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import importlib

    from readerm import config, servercfg, serverui
    importlib.reload(config)
    importlib.reload(servercfg)
    importlib.reload(serverui)

    controller = serverui.ServerController(host="127.0.0.1")
    assert controller.save_token("nope")["ok"] is False
    assert controller.save_token("ThisOneIsLongEnough")["ok"] is True
    assert controller.save_port(22)["ok"] is False
    assert controller.save_port(9123)["ok"] is True
    assert len(controller.generate_token()["token"]) >= 16


def test_the_window_page_is_valid_html():
    from readerm import serverui

    page = serverui.PAGE
    for node in ("id=\"token\"", "id=\"port\"", "id=\"log\"", "id=\"url\"",
                 "id=\"copyBtn\"", "id=\"verbose\""):
        assert node in page, node
    assert page.count("<script>") == page.count("</script>")


# ================================================== server log buffer


def test_the_log_records_and_replays(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    from readerm import server as server_module

    log = server_module.ServerLog()
    log.add("info", "one")
    log.add("warn", "two")
    cursor, lines = log.since(0)
    assert [l["text"] for l in lines] == ["one", "two"]
    # A second poll from the same cursor must not replay.
    _cursor2, fresh = log.since(cursor)
    assert fresh == []


def test_verbose_only_lines_respect_the_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    from readerm import server as server_module

    quiet = server_module.ServerLog(verbose=False)
    quiet.add("call", "chatty", verbose_only=True)
    quiet.add("error", "important")
    assert [l["text"] for l in quiet.since(0)[1]] == ["important"]

    loud = server_module.ServerLog(verbose=True)
    loud.add("call", "chatty", verbose_only=True)
    assert len(loud.since(0)[1]) == 1


def test_the_log_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    from readerm import server as server_module

    log = server_module.ServerLog()
    for i in range(log.LIMIT + 300):
        log.add("info", f"line {i}")
    assert len(log._lines) <= log.LIMIT


def test_rejected_calls_are_always_logged(tmp_path, monkeypatch):
    """A bad token is the one line you actually want to see."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import importlib

    from readerm import server as server_module
    importlib.reload(server_module)

    log = server_module.ServerLog(verbose=False)
    app = server_module.create_app(token="a" * 20, log=log)
    with app.test_client() as client:
        client.post("/api/get_settings", json={"args": []},
                    headers={"X-ReaderM-Token": "wrong"})
    text = " ".join(l["text"] for l in log.since(0)[1])
    assert "Rejected" in text and "get_settings" in text


def test_the_log_endpoint_needs_the_token(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import importlib

    from readerm import server as server_module
    importlib.reload(server_module)

    app = server_module.create_app(token="b" * 20)
    with app.test_client() as client:
        assert client.get("/api/_log").status_code == 401
        good = client.get("/api/_log?token=" + "b" * 20)
        assert good.status_code == 200
        assert good.get_json()["ok"] is True


def test_serve_uses_the_saved_token(tmp_path, monkeypatch):
    """The link the server prints must be the one the phone will need."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import importlib

    from readerm import config, servercfg
    importlib.reload(config)
    importlib.reload(servercfg)
    servercfg.save_server_settings(token="TheSavedTokenHere1")

    from readerm import server as server_module
    importlib.reload(server_module)
    url = server_module.build_url("127.0.0.1", 8577,
                                  servercfg.load_server_settings()["token"])
    assert "TheSavedTokenHere1" in url


# ========================================================== landing.py


def test_landing_imports():
    sys.path.insert(0, ROOT)
    from readerm import landing

    assert hasattr(landing, "Launcher")
    assert hasattr(landing, "find_python")


def test_landing_offers_every_interface():
    sys.path.insert(0, ROOT)
    from readerm import landing

    assert set(landing.Launcher.TARGETS) == {"gui", "menu", "tui", "cli",
                                             "server", "opds"}


def test_terminal_interfaces_get_a_terminal():
    """A TUI written to a pipe is useless."""
    sys.path.insert(0, ROOT)
    from readerm import landing

    for key in ("menu", "tui", "cli"):
        assert landing.Launcher.TARGETS[key][2] is True, key
    for key in ("gui", "server"):
        assert landing.Launcher.TARGETS[key][2] is False, key


def test_venv_is_found_in_the_project_folder(tmp_path, monkeypatch):
    sys.path.insert(0, ROOT)
    from readerm import landing

    fake = tmp_path / ".venv" / "bin"
    fake.mkdir(parents=True)
    (fake / "python3").write_text("#!/bin/sh\n")
    monkeypatch.setattr(landing, "HERE", str(tmp_path))
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    path, where = landing.find_python()
    assert path == str(fake / "python3")
    assert where == "project folder"


def test_venv_is_found_two_levels_up(tmp_path, monkeypatch):
    """A checkout is often one folder inside a workspace owning the venv."""
    sys.path.insert(0, ROOT)
    from readerm import landing

    project = tmp_path / "workspace" / "checkout"
    project.mkdir(parents=True)
    fake = tmp_path / "venv" / "bin"
    fake.mkdir(parents=True)
    (fake / "python3").write_text("#!/bin/sh\n")

    monkeypatch.setattr(landing, "HERE", str(project))
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    path, where = landing.find_python()
    assert path == str(fake / "python3")
    assert "2 level" in where


def test_no_venv_falls_back_and_says_so(tmp_path, monkeypatch):
    sys.path.insert(0, ROOT)
    from readerm import landing

    monkeypatch.setattr(landing, "HERE", str(tmp_path))
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)

    path, where = landing.find_python()
    assert path == sys.executable
    assert "no venv" in where.lower()


def test_the_current_venv_wins(monkeypatch):
    """Running landing.py from an activated venv is the common case."""
    sys.path.insert(0, ROOT)
    from readerm import landing

    monkeypatch.setattr(sys, "prefix", "/somewhere/venv")
    monkeypatch.setattr(sys, "base_prefix", "/usr")
    path, where = landing.find_python()
    assert path == sys.executable
    assert where == "this venv"


def test_launching_an_unknown_target_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    from readerm import landing

    result = landing.Launcher().launch("nonsense")
    assert result["ok"] is False
    assert "Unknown" in result["error"]


def test_the_launcher_logs_the_command_it_ran(tmp_path, monkeypatch):
    """When a launch fails, the exact command is the useful thing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    from readerm import landing

    launcher = landing.Launcher()
    text = " ".join(l["text"] for l in launcher.get_log()["lines"])
    assert "Python:" in text and landing.HERE in text


def test_the_launcher_really_starts_a_process(tmp_path, monkeypatch):
    """End to end: spawn the plain server and reach it over HTTP."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sys.path.insert(0, ROOT)
    import urllib.request

    from readerm import landing

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    launcher = landing.Launcher()
    launcher.TARGETS = dict(launcher.TARGETS)
    launcher.TARGETS["probe"] = (
        "Probe", ["server.py", "--host", "127.0.0.1", "--port", str(port)],
        False, "test only")
    try:
        assert launcher.launch("probe")["ok"] is True
        deadline = time.time() + 20
        reached = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/_ping", timeout=2):
                    reached = True
                    break
            except Exception:
                time.sleep(0.25)
        assert reached, "the launched process never served anything"
        assert launcher.running().get("probe") is True
    finally:
        for proc in launcher._children.values():
            proc.terminate()


def test_the_landing_page_has_a_collapsible_log():
    sys.path.insert(0, ROOT)
    from readerm import landing

    assert 'id="log"' in landing.PAGE
    assert "toggleLog" in landing.PAGE
    # Collapsed by default -- the log is for when something goes wrong.
    assert "#log{" in landing.PAGE.replace(" ", "")
    css = landing.PAGE[landing.PAGE.index("#log{"):]
    assert "display:none" in css[:400].replace(" ", "")


def test_docs_mention_landing():
    # FEATURES.md moved into MD/ in 1.0.1; README.md stays at the root.
    for name in ("README.md", os.path.join("MD", "FEATURES.md")):
        assert "landing.py" in read(os.path.join(ROOT, name)), name
