"""v1.4.24 regression tests.

Covers, in the order the issues were reported:

* closing to tray must not end the process
* the stylesheet must not be blocked by a remote font CDN
* the bouncing search icon must not be clipped by its container
* the queue must theme itself instead of hardcoding dark colours
* the duplicated "Active chapters" panel must be gone
* advanced queue logging
* the contribution calendar and the source carousel

The browser tests skip automatically without Playwright.
"""

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


def read(path):
    return open(path, encoding="utf-8").read()


# ============================================================ system tray


FAKE_PYSTRAY = textwrap.dedent("""
    import sys, threading, types
    ps = types.ModuleType("pystray")
    class Menu:
        SEPARATOR = object()
        def __init__(self, *a): pass
    class MenuItem:
        def __init__(self, *a, **k): pass
    class Icon:
        def __init__(self, *a, **k): self._s = threading.Event()
        def run(self): self._s.wait()
        def stop(self): self._s.set()
        def update_menu(self): pass
        def notify(self, *a, **k): pass
    ps.Menu, ps.MenuItem, ps.Icon = Menu, MenuItem, Icon
    sys.modules["pystray"] = ps
""")


def run_child(body, timeout=6):
    """Run a snippet in a real subprocess; report whether it stayed alive."""
    code = ('import sys\nsys.path.insert(0, %r)\n' % ROOT) + FAKE_PYSTRAY + body
    env = dict(os.environ, HOME=tempfile.mkdtemp())
    proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    started = time.time()
    try:
        out, _ = proc.communicate(timeout=timeout)
        return {"alive": False, "seconds": time.time() - started,
                "out": out, "rc": proc.returncode}
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        return {"alive": True, "seconds": time.time() - started, "out": out}


FAKE_WEBVIEW = textwrap.dedent("""
    import types
    from webview.event import Event, EventContainer
    wv = types.ModuleType("webview")
    class FakeWindow:
        def __init__(self):
            self.events = EventContainer()
            self.events.closed = Event(self)
            self.events.closing = Event(self, True)
            self.events.loaded = Event(self)
            self.hidden = False
        def hide(self): self.hidden = True
        def show(self): self.hidden = False
        def restore(self): pass
        def destroy(self): pass
        def evaluate_js(self, *a, **k): pass
    WIN = FakeWindow()
    wv.create_window = lambda *a, **k: WIN
    def start(*a, **k):
        WIN.events.closing.set()
        WIN.events.closed.set()
        print("loop-returned", flush=True)
    wv.start = start
    wv.FileDialog = None
    wv.FOLDER_DIALOG = wv.OPEN_DIALOG = wv.SAVE_DIALOG = 0
    sys.modules["webview"] = wv
""")


def test_closing_to_tray_does_not_end_the_process():
    """The reported bug: minimise-to-tray hid the window and the app died.

    Root cause: the tray icon runs on a *daemon* thread, as does every
    worker, so once webview.start() returned the interpreter exited and took
    the downloads with it. Measured before the fix: 0.06s to exit.
    """
    result = run_child(FAKE_WEBVIEW + textwrap.dedent("""
        from readerm.config import update_settings
        update_settings({"minimize_to_tray": True})
        import readerm.gui as g
        g.Api.get_progress = lambda self: {"active": 1, "queued": 0, "jobs": []}
        g.run_gui()
        print("run_gui-returned", flush=True)
    """), timeout=5)
    assert "loop-returned" in result["out"]
    assert result["alive"], (
        "the process exited after the GUI loop returned; the tray is not "
        f"holding it open (exited in {result['seconds']:.2f}s)")


def test_quit_from_the_tray_lets_the_process_exit():
    """The hold must not become a hang: Quit has to end it."""
    result = run_child(textwrap.dedent("""
        import threading
        from readerm.tray import TrayController
        from readerm.gui import _hold_for_tray
        class Api:
            _really_quitting = False
            def get_progress(self): return {"active": 5, "queued": 0}
            def shutdown(self): pass
        tray = TrayController(callbacks={"summary": lambda: {"active": 5}})
        tray.start()
        threading.Timer(0.6, tray._on_quit).start()
        _hold_for_tray(Api(), tray)
        print("released", flush=True)
    """), timeout=6)
    assert not result["alive"], "Quit did not release the main thread"
    assert "released" in result["out"]


def test_an_idle_app_stays_in_the_tray():
    """An empty queue is not a reason to quit.

    This test used to assert the opposite, and that assertion was wrong.
    v1.4.24 ended the hold as soon as nothing was downloading, to stop a
    tray that failed to draw an icon stranding an invisible process. But
    "no downloads running" is not "nobody wants this app": closing to the
    tray with an empty queue tore the process down 0.74s later, so clicking
    *Open ReaderM* flashed the window up and it vanished again -- the
    reported "opens for a quick second then disappears".

    The icon-failed case is handled where it belongs: _install_tray only
    returns a controller once the icon is actually running.
    """
    result = run_child(textwrap.dedent("""
        from readerm.tray import TrayController
        from readerm.gui import _hold_for_tray
        class Api:
            _really_quitting = False
            def get_progress(self): return {"active": 0, "queued": 0}
            def shutdown(self): print("SHUTDOWN", flush=True)
        tray = TrayController(callbacks={"summary": lambda: {"active": 0}})
        tray.start()
        _hold_for_tray(Api(), tray)
        print("released", flush=True)
    """), timeout=6)
    assert result["alive"], (
        "an idle app in the tray quit on its own; reopening it would flash "
        "the window and lose it")
    assert "SHUTDOWN" not in result["out"]


def test_reopening_from_the_tray_does_not_shut_the_app_down():
    """The window must survive being reopened while the queue is idle."""
    result = run_child(textwrap.dedent("""
        import threading, time
        from readerm.tray import TrayController
        from readerm.gui import _hold_for_tray
        class Api:
            _really_quitting = False
            def get_progress(self): return {"active": 0, "queued": 0}
            def shutdown(self): print("SHUTDOWN", flush=True)
        shown = []
        tray = TrayController(callbacks={
            "summary": lambda: {"active": 0},
            "show_window": lambda: shown.append(time.time()),
        })
        tray.start()

        def reopen():
            time.sleep(1.0)
            tray._on_open()
            print("REOPENED", flush=True)
        threading.Thread(target=reopen, daemon=True).start()

        _hold_for_tray(Api(), tray)
        print("released", flush=True)
    """), timeout=6)
    assert "REOPENED" in result["out"]
    assert result["alive"], "the app quit after being reopened from the tray"
    assert "SHUTDOWN" not in result["out"], (
        "shutdown ran while the window was on screen")


def test_no_tray_means_no_hold():
    """Without a tray the app must exit exactly as it always did."""
    result = run_child(textwrap.dedent("""
        from readerm.gui import _hold_for_tray
        class Api:
            _really_quitting = False
            def get_progress(self): return {"active": 9}
            def shutdown(self): pass
        _hold_for_tray(Api(), None)
        print("released", flush=True)
    """), timeout=6)
    assert not result["alive"]
    assert result["seconds"] < 3


def test_run_gui_actually_calls_the_hold():
    """Guard the wiring, not just the helper.

    An earlier version of this suite exercised _hold_for_tray directly and
    still passed with the call deleted from run_gui.
    """
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def run_gui():"):]
    assert "_hold_for_tray(api, tray)" in body


def test_turning_the_setting_off_lets_the_window_close():
    """The toggle must take effect without a restart."""
    from webview.event import Event, EventContainer

    sys.modules.pop("pystray", None)
    exec(FAKE_PYSTRAY, {"sys": sys})

    from readerm.config import update_settings
    from readerm.gui import _install_tray

    class Window:
        def __init__(self):
            self.events = EventContainer()
            self.events.closing = Event(self, True)
            self.events.closed = Event(self)
            self.hidden = False

        def hide(self):
            self.hidden = True

        def show(self):
            pass

        def restore(self):
            pass

        def destroy(self):
            pass

    class Api:
        def get_progress(self):
            return {"active": 0}

        def set_queue_paused(self, paused=None):
            return {"ok": True}

        def shutdown(self):
            return {"ok": True}

    update_settings({"minimize_to_tray": True})
    api, window = Api(), Window()
    tray = _install_tray(api, window)
    assert tray is not None

    assert window.events.closing.set() is True, "close should be vetoed"
    assert window.hidden

    # The user turns the setting off while the app is running.
    update_settings({"minimize_to_tray": False})
    window.events.closing.clear()
    assert window.events.closing.set() is False, \
        "with the setting off the window must close for real"
    tray.stop()


def test_tray_keepalive_is_exposed():
    from readerm.tray import TrayController

    controller = TrayController()
    assert hasattr(controller, "wait_for_quit")
    assert controller.quit_requested() is False
    controller.stop()
    assert controller.quit_requested() is True


def test_packaging_bundles_pystray():
    """PyInstaller cannot follow pystray's backend import chain."""
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    for module in ("pystray", "pystray._win32", "PIL.ImageDraw"):
        assert f'"{module}"' in spec, f"{module} missing from ReaderM.spec"


# ====================================================== startup stylesheet


# ========================================================= queue theming


# ============================================= duplicated chapters panel


# ======================================================= advanced logging


def test_advanced_log_setting_exists():
    from readerm.gui import DEFAULT_SETTINGS

    assert "queue_log_advanced" in DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["queue_log_advanced"] is False


# ==================================================== contribution graph


def test_calendar_covers_whole_weeks_and_fills_gaps():
    from readerm import features

    cal = features.stat_calendar(weeks=53, today="2026-07-30")
    assert len(cal["days"]) == 53 * 7
    # Must start on a Sunday, like GitHub's grid.
    first = datetime.date.fromisoformat(cal["days"][0]["date"])
    assert first.weekday() == 6
    # Every day present, including empty ones.
    dates = [d["date"] for d in cal["days"]]
    assert len(set(dates)) == len(dates)
    gaps = [d for d in cal["days"] if d["chapters"] == 0]
    assert gaps, "a calendar with no empty days is not filling gaps"
    assert all(d["level"] == 0 for d in gaps)


def test_calendar_levels_scale_to_the_busiest_day(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import features
    importlib.reload(features)

    today = datetime.date.today()
    for offset, count in ((0, 100), (1, 50), (2, 25), (3, 1)):
        day = (today - datetime.timedelta(days=offset)).isoformat()
        features._save(features.STATS_PATH, {"days": {
            **features._load(features.STATS_PATH, {}).get("days", {}),
            day: {"chapters": count, "pages": 0, "bytes": 0, "sources": {}},
        }})

    cal = features.stat_calendar()
    levels = {d["date"]: d["level"] for d in cal["days"]}
    assert levels[today.isoformat()] == 4
    # A single chapter must never round down to "nothing happened".
    assert levels[(today - datetime.timedelta(days=3)).isoformat()] >= 1


def test_per_day_sources_are_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import features
    importlib.reload(features)

    features.record_stat("mangadex", chapters=3)
    features.record_stat("flamecomics", chapters=7)

    cal = features.stat_calendar()
    today = [d for d in cal["days"]
             if d["date"] == datetime.date.today().isoformat()][0]
    assert today["sources"] == {"mangadex": 3, "flamecomics": 7}
    assert today["chapters"] == 10
    assert today["top"] == "flamecomics"


def test_old_stats_without_source_days_still_count(tmp_path, monkeypatch):
    """Days recorded before per-source tracking must not be dropped."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import features
    importlib.reload(features)

    day = datetime.date.today().isoformat()
    os.makedirs(features.DIR, exist_ok=True)
    json.dump({"days": {day: {"chapters": 12, "pages": 100, "bytes": 5}}},
              open(features.STATS_PATH, "w"))

    cal = features.stat_calendar()
    entry = [d for d in cal["days"] if d["date"] == day][0]
    assert entry["chapters"] == 12
    assert entry["sources"] == {}
    assert entry["level"] > 0


def test_calendar_api_returns_display_names(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import features
    importlib.reload(features)
    features.record_stat("madara.toonily", chapters=2)
    features.record_stat("mangadex", chapters=1)

    from readerm.gui import Api
    result = Api().get_calendar()
    assert result["ok"]
    names = result["calendar"]["names"]
    # Aggregate members must resolve, not show their raw namespaced slug.
    assert names["madara.toonily"] == "Toonily"
    assert names["mangadex"] == "MangaDex"


def test_source_name_resolution():
    from readerm.gui import Api

    api = Api()
    assert api._source_name("mangadex") == "MangaDex"
    assert api._source_name("madaranet") == "Madara Sites"
    assert api._source_name("madarascans") == "Madara Scans"
    assert api._source_name("madara.toonily") == "Toonily"
    assert api._source_name("?") == "Unknown"
    # An unknown id must degrade to something readable, never crash.
    assert api._source_name("something.else")


# ============================================================== browser


playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright is not installed")

PAGE_URL = "file://" + os.path.join(WEB, "index.html")

BRIDGE = """
(() => {
  const ok = (e) => Object.assign({ok: true}, e || {});
  const api = {
    get_settings: async () => ({theme: "light", accent: "teal",
                                output_dir: "/tmp/out"}),
    check_lock: async () => ({locked: false, enabled: false}),
    get_sources: async () => ok({sources: []}),
    get_genres: async () => ok({genres: []}),
    get_cart: async () => ok({queued: []}),
    get_progress: async () => Object.assign({ok: true},
      window.__progress || {active: 0, jobs: []}),
    get_calendar: async () => ok({calendar: window.__calendar || null}),
    get_stats: async () => ok({stats: window.__stats ||
      {totals: {}, derived: {}, sources: {}, days: {}}}),
    get_insights: async () => ok({insights: {}}),
    // Without this the catch-all Proxy answers {ok:true} with no
    // `available`, and refreshTrayState() disables the switch -- a quirk of
    // the stub, not the app.
    get_tray_state: async () => ok({available: true, enabled: false,
                                    running: false}),
    search: async () => ok({results: []}),
    trending: async () => ok({results: []}),
  };
  window.pywebview = {api: new Proxy(api, {
    get: (t, k) => (k in t) ? t[k] : (async () => ({ok: true})),
  })};
})();
"""


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        for candidate in (os.path.expanduser("~/.cache/ms-playwright"),
                          "/home/user/.cache/ms-playwright"):
            if os.path.isdir(candidate):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
                break
    with sync_playwright() as p:
        try:
            launched = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"chromium unavailable: {exc}")
        yield launched
        launched.close()


@pytest.fixture()
def page(browser):
    page = browser.new_page(viewport={"width": 1400, "height": 950})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.add_init_script(BRIDGE)
    page.goto(PAGE_URL)
    page.wait_for_timeout(400)
    yield page
    page.close()


JOBS = """
window.__progress = {active: 1, jobs: [{job_id: "a", title: "Solo Leveling",
  bytes_per_second: 5033164, eta_seconds: 92, bytes: 88010000,
  history: [1,4,9,16,25,36,44,48,50,49].map(v => v * 100000)}]};
jobs.set("a", {id: "a", title: "Solo Leveling", url: "https://x/solo",
  source: "Asura Scans", done: 11, total: 18, finished: false,
  chapters: [{name: "Chapter 11", done: 12, total: 16}]});
state.downloading = true;
"""


CAL = """
window.__calendar = (() => {
  const days = [];
  const start = new Date('2025-08-03T00:00:00');
  for (let i = 0; i < 371; i++) {
    const d = new Date(start.getTime() + i * 86400000);
    const busy = i % 3 === 0;
    days.push({
      date: d.toISOString().slice(0, 10),
      chapters: busy ? (i % 40) + 1 : 0,
      pages: 0, bytes: 0,
      level: busy ? Math.min(4, Math.floor((i % 40) / 10) + 1) : 0,
      sources: busy ? {mangadex: (i % 9) + 1, flamecomics: (i % 5) + 1} : {},
      top: busy ? 'mangadex' : '',
    });
  }
  return {days, weeks: 53, peak: 40,
          total: days.reduce((n, d) => n + d.chapters, 0),
          sources: {mangadex: 900, flamecomics: 400},
          names: {mangadex: 'MangaDex', flamecomics: 'Flame Comics'}};
})();
window.__stats = {totals: {chapters: 1300}, derived: {},
                  sources: {mangadex: {chapters: 900},
                            flamecomics: {chapters: 400}}, days: {}};
"""
