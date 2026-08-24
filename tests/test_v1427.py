"""v1.4.27 regression tests: duplicate instances and the Windows crash.

Both come from a crash log the user supplied, covering 116 sessions.

**Duplicates.** Nothing stopped a second copy launching while the first sat
hidden in the tray -- and running it again is the obvious way to "reopen" a
hidden window. Reproduced: three launches against one profile left three
processes alive, three tray icons, and three download engines writing the
same library and config.

**The crash.** Two hard faults in the log, neither catchable:

    Windows fatal exception: access violation
      Thread : pystray/_win32.py _mainloop      <- tray loop already running
      Current: clr_loader/types.py __call__     <- .NET CLR loading
               webview/platforms/winforms.py <module>

The tray's Win32 message loop was already running when pywebview loaded the
CLR. The fix starts the tray only after the toolkit is up.
"""

import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    return open(path, encoding="utf-8").read()


# =========================================================== singleton


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import singleton
    importlib.reload(singleton)
    return singleton


def test_second_start_is_refused(home):
    first = home.InstanceServer()
    assert first.start() is True
    try:
        assert home.InstanceServer().start() is False
    finally:
        first.stop()


def test_second_start_surfaces_the_first_window(home):
    """Refusing silently would be worse than the duplicate: the user clicks
    the launcher and nothing happens."""
    shown = []
    first = home.InstanceServer(on_show=lambda: shown.append(1))
    assert first.start()
    try:
        home.InstanceServer().start()
        deadline = time.time() + 3
        while not shown and time.time() < deadline:
            time.sleep(0.05)
        assert shown, "the running instance was never asked to come forward"
    finally:
        first.stop()


def test_every_extra_launch_surfaces_it_again(home):
    shown = []
    first = home.InstanceServer(on_show=lambda: shown.append(1))
    assert first.start()
    try:
        for _ in range(3):
            home.InstanceServer().start()
        deadline = time.time() + 4
        while len(shown) < 3 and time.time() < deadline:
            time.sleep(0.05)
        assert len(shown) == 3, f"only {len(shown)} of 3 launches surfaced it"
    finally:
        first.stop()


def test_a_stale_port_file_does_not_block_startup(home):
    """A killed instance leaves the file behind. The next launch must work."""
    import json

    os.makedirs(home.BASE_DIR, exist_ok=True)
    with open(home.INSTANCE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"port": 59999, "token": "dead", "pid": 999999}, fh)

    assert home.notify_existing() is False
    fresh = home.InstanceServer()
    try:
        assert fresh.start() is True, "a stale file locked the app out"
    finally:
        fresh.stop()


def test_the_slot_is_released_on_stop(home):
    first = home.InstanceServer()
    assert first.start()
    first.stop()
    second = home.InstanceServer()
    try:
        assert second.start() is True
    finally:
        second.stop()


def test_a_wrong_token_is_ignored(home):
    """Only loopback is bound, but another local user must still not be able
    to drive the window around."""
    fired = []
    server = home.InstanceServer(on_show=lambda: fired.append(1))
    assert server.start()
    try:
        with socket.create_connection((home.HOST, server.port), 2) as sock:
            sock.sendall(b"not-the-token show\n")
            sock.settimeout(1.0)
            try:
                reply = sock.recv(16)
            except OSError:
                reply = b""
        assert reply.strip() != b"ok"
        time.sleep(0.4)
        assert not fired, "an unauthenticated client moved the window"
    finally:
        server.stop()


def test_only_loopback_is_bound(home):
    server = home.InstanceServer()
    assert server.start()
    try:
        assert server._sock.getsockname()[0] == "127.0.0.1"
    finally:
        server.stop()


def test_run_gui_claims_the_slot_before_importing_webview():
    """Order matters: importing pywebview loads the CLR, and the crash log
    shows that dying. A duplicate must be turned away before it gets there.
    """
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def run_gui():"):]
    claim = body.index("instance.start()")
    webview_import = body.index("import webview")
    assert claim < webview_import, (
        "the single-instance check must run before 'import webview'")


# ============================================ crash: tray/CLR ordering


def test_tray_starts_after_the_toolkit():
    """The crash: pystray's Win32 message loop was already running when
    pywebview loaded the .NET CLR."""
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def run_gui():"):]

    setup = body[:body.index("webview.start(")]
    # _install_tray may only be *called* from inside the deferred helper,
    # never at module flow level before the toolkit starts. Checking for
    # the bare call text is not enough -- it now lives inside
    # _start_tray_once(), which is exactly what we want.
    assert "_start_tray_once" in setup, "expected a deferred tray install"
    for line in setup.splitlines():
        if "_install_tray(" in line and not line.strip().startswith("#"):
            indent = len(line) - len(line.lstrip())
            assert indent >= 8, (
                f"_install_tray is called at top level of run_gui: {line!r}")
    # And the deferred helper must be triggered by an event, not called.
    assert "window.events.shown += _start_tray_once" in setup


IDEMPOTENCE = textwrap.dedent("""
    import sys, threading, time, types
    sys.path.insert(0, %r)
    CREATED = []
    ps = types.ModuleType("pystray")
    ps.Menu = type("Menu", (), {"SEPARATOR": object(),
                                "__init__": lambda self, *a: None})
    ps.MenuItem = type("MenuItem", (), {"__init__": lambda s, *a, **k: None})
    class Icon:
        def __init__(self, *a, **k):
            CREATED.append(1); self._s = threading.Event()
        def run(self): self._s.wait()
        def stop(self): self._s.set()
        def update_menu(self): pass
        def notify(self, *a, **k): pass
    ps.Icon = Icon
    sys.modules["pystray"] = ps

    from webview.event import Event, EventContainer
    wv = types.ModuleType("webview")
    class Win:
        def __init__(self):
            self.events = EventContainer()
            self.events.closing = Event(self, True)
            self.events.closed = Event(self)
            self.events.loaded = Event(self)
            self.events.shown = Event(self)
        def hide(self): pass
        def show(self): pass
        def restore(self): pass
        def destroy(self): pass
        def evaluate_js(self, *a, **k): pass
    WIN = Win()
    wv.create_window = lambda *a, **k: WIN
    wv.FileDialog = None
    wv.FOLDER_DIALOG = wv.OPEN_DIALOG = wv.SAVE_DIALOG = 0
    def start(*a, **k):
        # Fire every trigger: shown, then long enough for the 4s fallback
        # timer, then a close. Exactly one icon may be created.
        WIN.events.shown.set()
        time.sleep(5.0)
        WIN.events.closing.clear(); WIN.events.closing.set()
        WIN.events.closed.set()
    wv.start = start
    sys.modules["webview"] = wv

    from mangasurf.config import update_settings
    update_settings({"minimize_to_tray": True})
    import mangasurf.gui as g
    g.Api.get_progress = lambda self: {"active": 0, "queued": 0, "jobs": []}

    def report():
        time.sleep(7)
        print("ICONS", len(CREATED), flush=True)
        import os as _os; _os._exit(0)
    threading.Thread(target=report, daemon=True).start()
    g.run_gui()
""") % ROOT


def test_tray_install_is_idempotent(tmp_path):
    """Three triggers can fire (shown, fallback timer, close). Exactly one
    tray icon may be created -- two would mean two icons in the tray and two
    refresh loops."""
    env = dict(os.environ, HOME=str(tmp_path))
    proc = subprocess.run([sys.executable, "-c", IDEMPOTENCE], env=env,
                          capture_output=True, text=True, timeout=40)
    counts = [line for line in proc.stdout.splitlines()
              if line.startswith("ICONS")]
    assert counts, f"harness produced no result: {proc.stdout[-400:]}"
    created = int(counts[0].split()[1])
    assert created == 1, (
        f"{created} tray icons were created; the install is not idempotent")


def test_a_backend_that_never_fires_shown_still_gets_a_tray():
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def run_gui():"):]
    assert "_tray_fallback" in body, (
        "no fallback for backends that do not fire 'shown'")
    assert "threading.Timer" in body


def test_a_fast_close_still_gets_a_tray():
    """If the user closes the window before either trigger fires, minimise
    to tray must still work rather than quitting the app."""
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    assert "_on_closing_pre" in source
    body = source[source.index("def _on_closing_pre():"):]
    body = body[:body.index("return True")]
    assert "_start_tray_once()" in body


def test_windows_does_not_retry_backends_after_a_failed_import():
    """Retrying another backend re-enters the CLR load that already crashed
    once. The log shows the access violation happening inside that import.
    """
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("last_error = None"):]
    body = body[:body.index("_show_fatal(")]
    assert 'sys.platform == "win32"' in body and "break" in body, (
        "Windows still retries backends after a failed toolkit import")


# ================================================= end-to-end processes


FAKE = textwrap.dedent("""
    import sys, threading, time, types
    sys.path.insert(0, %r)
    ps = types.ModuleType("pystray")
    ps.Menu = type("Menu", (), {"SEPARATOR": object(),
                                "__init__": lambda self, *a: None})
    ps.MenuItem = type("MenuItem", (), {"__init__": lambda s, *a, **k: None})
    class Icon:
        def __init__(self, *a, **k): self._s = threading.Event()
        def run(self): self._s.wait()
        def stop(self): self._s.set()
        def update_menu(self): pass
        def notify(self, *a, **k): pass
    ps.Icon = Icon
    sys.modules["pystray"] = ps

    from webview.event import Event, EventContainer
    wv = types.ModuleType("webview")
    class Win:
        def __init__(self):
            self.events = EventContainer()
            self.events.closing = Event(self, True)
            self.events.closed = Event(self)
            self.events.loaded = Event(self)
            self.events.shown = Event(self)
        def hide(self): pass
        def show(self): pass
        def restore(self): pass
        def destroy(self): pass
        def evaluate_js(self, *a, **k): pass
    WIN = Win()
    wv.create_window = lambda *a, **k: WIN
    wv.FileDialog = None
    wv.FOLDER_DIALOG = wv.OPEN_DIALOG = wv.SAVE_DIALOG = 0
    def start(*a, **k):
        WIN.events.shown.set()
        time.sleep(0.4)
        WIN.events.closing.set()
        WIN.events.closed.set()
    wv.start = start
    sys.modules["webview"] = wv

    from mangasurf.config import update_settings
    update_settings({"minimize_to_tray": True})
    import mangasurf.gui as g
    g.Api.get_progress = lambda self: {"active": 0, "queued": 0, "jobs": []}
    print("PID", __import__("os").getpid(), flush=True)
    g.run_gui()
""") % ROOT


def test_three_launches_leave_one_process(tmp_path):
    """The headline reproduction, as real processes."""
    env = dict(os.environ, HOME=str(tmp_path))
    procs = []
    try:
        for _ in range(3):
            procs.append(subprocess.Popen(
                [sys.executable, "-c", FAKE], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True))
            time.sleep(1.0)
        time.sleep(2.5)
        alive = [p for p in procs if p.poll() is None]
        assert len(alive) == 1, (
            f"{len(alive)} copies running at once; each has its own tray "
            "icon and download engine on the same library")
    finally:
        for p in procs:
            p.kill()


# ======================================================== screenshots


DOCS = os.path.join(ROOT, "docs")


def test_every_referenced_screenshot_exists():
    """README and the landing page must not point at deleted files."""
    import re as _re

    missing = []
    readme = read(os.path.join(ROOT, "README.md"))
    for rel in set(_re.findall(r"\(docs/([a-z0-9._-]+\.png)\)", readme)):
        if not os.path.isfile(os.path.join(DOCS, rel)):
            missing.append(f"README -> {rel}")

    site = read(os.path.join(DOCS, "index.html"))
    for rel in set(_re.findall(r'src="([a-z0-9._-]+\.png)"', site)):
        if not os.path.isfile(os.path.join(DOCS, rel)):
            missing.append(f"index.html -> {rel}")

    assert missing == [], f"broken image references: {missing}"


def test_no_orphaned_screenshots():
    """A screenshot nobody shows is a stale screenshot nobody updates."""
    import re as _re

    referenced = set()
    readme = read(os.path.join(ROOT, "README.md"))
    referenced |= set(_re.findall(r"\(docs/([a-z0-9._-]+\.png)\)", readme))
    site = read(os.path.join(DOCS, "index.html"))
    referenced |= set(_re.findall(r'src="([a-z0-9._-]+\.png)"', site))

    on_disk = {f for f in os.listdir(DOCS) if f.endswith(".png")}
    orphans = on_disk - referenced
    assert orphans == set(), f"unreferenced screenshots: {sorted(orphans)}"


def test_screenshots_show_the_current_ui():
    """The committed shots were twelve releases stale, advertising a UI that
    no longer existed. Pin the ones that prove the current features."""
    for name in ("gui-queue.png", "gui-insights.png", "gui-tools.png"):
        path = os.path.join(DOCS, name)
        assert os.path.isfile(path), f"{name} is missing"
        # A blank or truncated capture is worse than none.
        assert os.path.getsize(path) > 40_000, f"{name} looks empty"


# ========================================================= crash log


def test_crash_log_is_trimmed(tmp_path, monkeypatch):
    """The supplied log had 116 session markers around 2 real crashes.

    Left alone it grows without bound and buries the one thing it exists
    to record.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import logs
    importlib.reload(logs)

    os.makedirs(logs.LOG_DIR, exist_ok=True)
    with open(logs.CRASH_FILE, "w", encoding="utf-8") as fh:
        for i in range(20000):
            fh.write(f"\n--- session start 2026-07-{(i % 28) + 1:02d} 10:00 ---\n")
        fh.write("\nWindows fatal exception: access violation\n"
                 "  REAL TRACEBACK\n")
    before = os.path.getsize(logs.CRASH_FILE)
    assert before > logs.CRASH_LOG_MAX_BYTES

    logs._trim_crash_log()

    after = os.path.getsize(logs.CRASH_FILE)
    assert after <= logs.CRASH_LOG_MAX_BYTES, f"{after} bytes after trimming"
    body = open(logs.CRASH_FILE, encoding="utf-8").read()
    assert "REAL TRACEBACK" in body, "trimming threw away the actual crash"


def test_trim_starts_at_a_session_boundary(tmp_path, monkeypatch):
    """Opening mid-traceback would make the log unreadable."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import logs
    importlib.reload(logs)

    os.makedirs(logs.LOG_DIR, exist_ok=True)
    with open(logs.CRASH_FILE, "w", encoding="utf-8") as fh:
        fh.write("x" * (logs.CRASH_LOG_MAX_BYTES + 5000))
        fh.write("\n--- session start 2026-07-30 23:00:00 ---\ntail\n")
    logs._trim_crash_log()
    body = open(logs.CRASH_FILE, encoding="utf-8").read()
    assert body.startswith("--- earlier entries trimmed ---")
    assert "session start" in body


def test_a_small_crash_log_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import logs
    importlib.reload(logs)

    os.makedirs(logs.LOG_DIR, exist_ok=True)
    with open(logs.CRASH_FILE, "w", encoding="utf-8") as fh:
        fh.write("a real traceback, nice and short\n")
    logs._trim_crash_log()
    assert open(logs.CRASH_FILE, encoding="utf-8").read() == \
        "a real traceback, nice and short\n"
