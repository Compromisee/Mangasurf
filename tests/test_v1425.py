"""v1.4.25 regression tests: the tray notification loop.

Reported as "runs in BG sometimes, but repeated notifications over and over
like a loop".

Reproduced before fixing: ``_on_closing`` notified **unconditionally** on
every close event, with no duplicate suppression and no check for "already
hidden". A window manager that delivers the close event more than once --
minimise/restore, a taskbar "Close window", or the backend-retry loop in
``run_gui`` which closes the window once per attempt -- produced one balloon
per event. Measured: **20 close events in 0.41s produced 20 balloons.**

The fix has to suppress repeats *without* eating genuine events, and that
distinction is the point of half the tests here: a first attempt used a
blanket rate limit and silently dropped 4 of 5 real "download finished"
notifications.
"""

import os
import sys
import threading
import time
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    return open(path, encoding="utf-8").read()


# ------------------------------------------------------------- fixtures


def install_fake_pystray():
    """A pystray stand-in that records every balloon it is asked to show."""
    module = types.ModuleType("pystray")

    class Menu:
        SEPARATOR = object()

        def __init__(self, *args):
            pass

    class MenuItem:
        def __init__(self, *args, **kwargs):
            pass

    class Icon:
        def __init__(self, name, icon=None, title=None, menu=None):
            self.name, self.icon, self.title, self.menu = name, icon, title, menu
            self.notes = []
            self._stop = threading.Event()

        def run(self):
            self._stop.wait()

        def stop(self):
            self._stop.set()

        def update_menu(self):
            pass

        def notify(self, message, title=None):
            self.notes.append(message)

    module.Menu, module.MenuItem, module.Icon = Menu, MenuItem, Icon
    sys.modules["pystray"] = module
    return module


class FakeWindow:
    """Mimics pywebview's event plumbing, including the veto contract."""

    def __init__(self):
        from webview.event import Event, EventContainer

        self.events = EventContainer()
        self.events.closing = Event(self, True)     # should_lock=True
        self.events.closed = Event(self)
        self.events.shown = Event(self)
        self.hidden = False
        self.destroyed = False

    def hide(self):
        self.hidden = True

    def show(self):
        self.hidden = False

    def restore(self):
        pass

    def destroy(self):
        self.destroyed = True

    def close(self):
        """Deliver one close event; returns True when the close was vetoed."""
        self.events.closing.clear()
        return self.events.closing.set()


class FakeApi:
    def __init__(self, active=1, queued=0):
        self.active, self.queued = active, queued
        self._queue_paused = False

    def get_progress(self):
        return {"active": self.active, "queued": self.queued, "jobs": []}

    def set_queue_paused(self, paused=None):
        return {"ok": True}

    def shutdown(self):
        return {"ok": True}


@pytest.fixture()
def tray_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    install_fake_pystray()
    from readerm.config import update_settings
    update_settings({"minimize_to_tray": True, "tray_notifications": True})

    created = []

    def build(active=1, queued=0):
        from readerm.gui import _install_tray
        api, window = FakeApi(active, queued), FakeWindow()
        controller = _install_tray(api, window)
        assert controller is not None
        created.append(controller)
        return api, window, controller

    yield build
    for controller in created:
        controller.stop()


# =============================================== the loop itself


def test_repeated_close_events_do_not_repeat_the_notification(tray_setup):
    """The reported bug. 20 close events used to give 20 balloons."""
    api, window, tray = tray_setup()

    for _ in range(20):
        assert window.close() is True, "every close must still be vetoed"

    notes = tray.icon.notes
    assert len(notes) <= 1, (
        f"20 close events produced {len(notes)} notifications: {notes[:5]}")
    assert window.hidden is True


def test_repeat_closes_are_suppressed_even_without_dedupe(tray_setup):
    """Isolate the "already hidden" guard from the notify() dedupe.

    The two defences overlap, so removing either one alone still looked
    fine. This disables the text-dedupe entirely -- every notify() call
    would go straight through -- so the only thing that can keep the count
    down is the close handler declining to notify when already hidden.
    """
    api, window, tray = tray_setup()

    # Neuter BOTH notify()-level defences, so only the close handler is
    # left to prevent the repeat. Without this the test passes even with
    # the guard deleted, which is exactly how it first fooled me.
    seen = []

    def raw_notify(message, title=None, dedupe_seconds=None, once=False):
        seen.append(message)
        tray.icon.notify(message, title)
        return True

    tray.notify = raw_notify

    for _ in range(15):
        window.close()

    assert len(seen) <= 1, (
        "with dedupe disabled, the close handler still notified on every "
        f"repeat: {len(seen)} balloons")


def test_the_window_still_hides_on_every_close(tray_setup):
    """Suppressing the balloon must not suppress the hiding."""
    api, window, tray = tray_setup()
    window.close()
    assert window.hidden is True

    # Reopen from the tray, then close again.
    tray._on_open()
    assert window.hidden is False
    window.close()
    assert window.hidden is True


def test_reopening_lets_the_notification_happen_again(tray_setup):
    """Hiding again after deliberately reopening is a new event."""
    api, window, tray = tray_setup()
    window.close()
    first = len(tray.icon.notes)
    assert first == 1

    tray._on_open()          # user reopens from the tray menu
    window.close()
    assert len(tray.icon.notes) == 2, (
        "after reopening, hiding again should notify once more")


def test_backend_retry_does_not_stack_notifications(tray_setup):
    """run_gui retries alternative backends, closing the window each time."""
    api, window, tray = tray_setup()
    for _ in range(3):       # three backend attempts
        window.close()
    assert len(tray.icon.notes) <= 1


# =============================================== honesty of the message


def test_no_downloads_means_no_download_claim(tray_setup):
    """"Still downloading in the background" with an empty queue is false."""
    api, window, tray = tray_setup(active=0, queued=0)
    window.close()
    assert tray.icon.notes, "closing to the tray should say something once"
    message = tray.icon.notes[0].lower()
    assert "still downloading" not in message, (
        f"claimed downloads that do not exist: {tray.icon.notes[0]!r}")
    assert "tray" in message or "running" in message


def test_active_downloads_are_reported_as_such(tray_setup):
    api, window, tray = tray_setup(active=2)
    window.close()
    assert "downloading" in tray.icon.notes[0].lower()


def test_queued_only_still_counts_as_busy(tray_setup):
    """Nothing running yet, but work is waiting -- that is still busy."""
    api, window, tray = tray_setup(active=0, queued=3)
    window.close()
    assert "downloading" in tray.icon.notes[0].lower()


# =============================================== notify() in isolation


def test_identical_messages_are_deduplicated():
    from readerm.tray import TrayController

    install_fake_pystray()
    tray = TrayController()
    assert tray.start()
    try:
        sent = [tray.notify("the same thing") for _ in range(10)]
        assert sum(1 for s in sent if s) == 1, (
            f"10 identical calls produced {len(tray.icon.notes)} balloons")
    finally:
        tray.stop()


def test_different_messages_all_get_through():
    """The critical counter-test.

    A blanket rate limit would pass the dedupe test above and still be
    wrong: five books finishing in quick succession are five real events.
    An early version of this fix dropped 4 of 5.
    """
    from readerm.tray import TrayController

    install_fake_pystray()
    tray = TrayController()
    assert tray.start()
    try:
        for i in range(5):
            tray.notify(f"Book {i} - 12 chapters downloaded")
        assert len(tray.icon.notes) == 5, (
            f"genuine per-book notifications were suppressed: {tray.icon.notes}")
    finally:
        tray.stop()


def test_dedupe_window_expires():
    from readerm.tray import TrayController

    install_fake_pystray()
    tray = TrayController()
    assert tray.start()
    try:
        assert tray.notify("hello", dedupe_seconds=0.2) is True
        assert tray.notify("hello", dedupe_seconds=0.2) is False
        time.sleep(0.25)
        assert tray.notify("hello", dedupe_seconds=0.2) is True
    finally:
        tray.stop()


def test_once_messages_never_repeat():
    from readerm.tray import TrayController

    install_fake_pystray()
    tray = TrayController()
    assert tray.start()
    try:
        assert tray.notify("only once", once=True) is True
        time.sleep(0.05)
        # Even with the dedupe window disabled, once=True still holds.
        assert tray.notify("only once", once=True, dedupe_seconds=0) is False
        tray.reset_notifications()
        assert tray.notify("only once", once=True) is True
    finally:
        tray.stop()


def test_notify_without_an_icon_is_safe():
    from readerm.tray import TrayController

    assert TrayController().notify("no icon here") is False


# =============================================== finished-download path


def test_every_finished_download_still_notifies(tmp_path, monkeypatch):
    """End-to-end through Api: N books finishing produce N balloons."""
    monkeypatch.setenv("HOME", str(tmp_path))
    install_fake_pystray()

    import readerm.gui as gui
    from readerm.config import update_settings
    from readerm.tray import TrayController

    update_settings({"tray_notifications": True, "max_concurrent_jobs": 2})

    class Engine:
        def __init__(self, opt, on_event=None, job_id=None):
            self.opt = opt

        def run(self):
            time.sleep(0.02)
            return {"ok": True, "downloaded": 4}

        def stop(self):
            pass

    monkeypatch.setattr(gui, "DownloadEngine", Engine)

    api = gui.Api()
    api._push = lambda event: None
    api._flush = lambda: None
    tray = TrayController()
    tray.start()
    api._tray = tray
    try:
        for i in range(5):
            api.add_to_cart({"url": f"https://example.com/m/{i}",
                             "title": f"Book {i}", "selection": "all"})
        deadline = time.time() + 10
        while time.time() < deadline:
            with api._jobs_lock:
                if not api._cart and not api._active_jobs():
                    break
            time.sleep(0.05)
        time.sleep(0.3)
        assert len(tray.icon.notes) == 5, (
            f"expected one balloon per book, got {tray.icon.notes}")
    finally:
        tray.stop()


def test_a_stopped_download_stays_quiet(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    install_fake_pystray()

    import readerm.gui as gui
    from readerm.config import update_settings
    from readerm.tray import TrayController

    update_settings({"tray_notifications": True})

    class Engine:
        def __init__(self, opt, on_event=None, job_id=None):
            pass

        def run(self):
            return {"ok": False, "stopped": True}

        def stop(self):
            pass

    monkeypatch.setattr(gui, "DownloadEngine", Engine)
    api = gui.Api()
    api._push = lambda event: None
    api._flush = lambda: None
    tray = TrayController()
    tray.start()
    api._tray = tray
    try:
        api.add_to_cart({"url": "https://example.com/m/1", "title": "Book",
                         "selection": "all"})
        time.sleep(0.5)
        assert tray.icon.notes == []
    finally:
        tray.stop()


def test_notifications_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    install_fake_pystray()
    from readerm.config import update_settings
    from readerm.gui import _install_tray

    update_settings({"minimize_to_tray": True, "tray_notifications": False})
    api, window = FakeApi(), FakeWindow()
    tray = _install_tray(api, window)
    try:
        import readerm.gui as gui
        api2 = gui.Api()
        api2._tray = tray
        api2._notify_finished({"title": "Book"}, {"ok": True, "downloaded": 2})
        assert tray.icon.notes == []
    finally:
        tray.stop()


# =============================================== source guards


def test_close_handler_checks_the_hidden_flag():
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    handler = source[source.index("def _on_closing():"):]
    handler = handler[:handler.index("def _on_shown():")]
    assert "_hidden_to_tray" in handler, (
        "the close handler must not notify again when already hidden")


def test_show_window_clears_the_hidden_flag():
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    handler = source[source.index("def show_window():"):]
    handler = handler[:handler.index("def quit_app():")]
    assert "_hidden_to_tray = False" in handler
    assert "reset_notifications" in handler
