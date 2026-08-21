"""Regression tests for v1.4.19.

* system-tray background mode, with a live context menu
* transfer rate / ETA / queue depth, which nothing measured before
* crash-resume that survives **concurrent** jobs

The journal bugs here were reproduced before being fixed: with two jobs
running, the second overwrote the first's record, and whichever finished
first wiped the other's.
"""

import os
import re
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ============================================================== progress


def test_rate_meter_is_a_rolling_window_not_a_lifetime_average():
    """A cumulative average keeps reporting a high speed long after the
    transfer slows, which is exactly when the number matters."""
    from mangasurf.progress import RateMeter

    meter = RateMeter(window=1.0)
    for _ in range(10):
        meter.add(100_000)
    fast = meter.rate()
    assert fast > 0

    # Nothing moves for longer than the window: the rate must fall away.
    time.sleep(1.2)
    assert meter.rate() < fast / 2
    # ...but the lifetime total is still correct.
    assert meter.total == 1_000_000


def test_rate_meter_does_not_divide_by_a_tiny_span():
    """Two samples milliseconds apart must not report a gigabyte a second."""
    from mangasurf.progress import RateMeter

    meter = RateMeter(window=8.0)
    meter.add(1024)
    meter.add(1024)
    assert meter.rate() <= 2048 / 0.5 + 1


def test_stalled_transfer_reports_zero():
    from mangasurf.progress import STALE_AFTER, RateMeter

    meter = RateMeter(window=2.0)
    meter.add(5_000_000)
    meter._samples[:] = [(time.time() - STALE_AFTER - 5, 5_000_000)]
    assert meter.rate() == 0.0


def test_eta_is_none_when_it_cannot_be_known():
    """A fabricated ETA is worse than an honest "--"."""
    from mangasurf.progress import JobProgress, human_eta

    job = JobProgress("j", "T")
    assert job.eta_seconds() is None            # nothing started
    job.add_page()
    assert job.eta_seconds() is None            # total unknown
    assert human_eta(None) == "--"


def test_eta_counts_down_once_pages_are_known():
    from mangasurf.progress import JobProgress

    job = JobProgress("j", "T")
    job.set_pages(total=100)
    for _ in range(10):
        job.add_page()
    first = job.eta_seconds()
    assert first is not None and first > 0

    for _ in range(80):
        job.add_page()
    assert job.eta_seconds() < first


def test_eta_projects_chapters_whose_page_lists_are_not_fetched_yet():
    """Page totals arrive chapter by chapter, so an ETA based only on known
    pages showed "--" for most of a run then jumped to a few seconds."""
    from mangasurf.progress import JobProgress

    job = JobProgress("j", "T")
    job.set_chapters(done=1, total=10)
    job.set_pages(total=100)
    for _ in range(100):
        job.add_page()
    # 1 of 10 chapters done at 100 pages -> ~900 pages still to come.
    assert job.eta_seconds() is not None


def test_formatters():
    from mangasurf.progress import human_bytes, human_eta, human_rate

    assert human_rate(0) == "0 KB/s"
    assert human_rate(5 * 1024 * 1024).endswith("MB/s")
    assert human_bytes(0) == "0 B"
    assert human_bytes(1024 * 1024).startswith("1.0 MB")
    assert human_eta(45) == "45s"
    assert human_eta(605) == "10m 05s"
    assert human_eta(7300).startswith("2h")


def test_registry_aggregates_concurrent_jobs():
    from mangasurf.progress import ProgressRegistry

    registry = ProgressRegistry()
    a = registry.job("a", "A")
    b = registry.job("b", "B")
    a.set_chapters(done=2, total=10)
    b.set_chapters(done=1, total=5)
    a.add_bytes(1024)
    b.add_bytes(2048)
    registry.set_queued(3)

    summary = registry.summary()
    assert summary["active"] == 2
    assert summary["queued"] == 3
    assert summary["chapters_done"] == 3
    assert summary["chapters_total"] == 15
    assert summary["chapters_remaining"] == 12
    assert summary["bytes"] == 3072


def test_overall_eta_is_the_longest_job_not_the_sum():
    """Jobs run in parallel: summing overstates, taking the shortest promises
    a finish that has not happened."""
    from mangasurf.progress import ProgressRegistry

    registry = ProgressRegistry()
    quick = registry.job("q")
    slow = registry.job("s")
    for job, total in ((quick, 10), (slow, 1000)):
        job.set_pages(total=total)
        job.add_page()

    etas = [quick.eta_seconds(), slow.eta_seconds()]
    assert all(e is not None for e in etas)
    assert registry.summary()["eta_seconds"] == pytest.approx(max(etas), rel=0.2)


def test_finished_jobs_leave_the_active_set():
    from mangasurf.progress import ProgressRegistry

    registry = ProgressRegistry()
    job = registry.job("x")
    assert registry.summary()["active"] == 1
    job.finish()
    assert registry.summary()["active"] == 0


def test_engine_reports_bytes_through_the_source():
    """download_file must feed the meter as chunks land, not once per file --
    counting whole files makes the rate lurch between 0 and a spike."""
    source = read(os.path.join(ROOT, "mangasurf", "sources", "base.py"))
    body = source[source.index("def download_file"):]
    assert "self.on_bytes" in body
    assert "on_bytes(len(block))" in body


def test_source_has_a_bytes_hook_defaulting_to_none():
    from mangasurf.sources import get_source

    source = get_source("witchscans")
    try:
        assert source.on_bytes is None
    finally:
        source.close()


# ================================================================== tray


def test_tray_import_never_raises_on_a_headless_machine():
    """`import pystray` itself raises Xlib.error.DisplayNameError with no
    display -- at import, before any of our code runs. Reproduced here. So
    the import must be guarded and probing must be safe."""
    from mangasurf.tray import tray_available

    assert tray_available() in (True, False)      # must not raise


def test_tray_module_does_not_import_pystray_at_module_scope():
    source = read(os.path.join(ROOT, "mangasurf", "tray.py"))
    head = source[:source.index("def tray_available")]
    assert not re.search(r"(?m)^(import pystray|from pystray)", head)


def test_menu_shows_speed_eta_queue_and_jobs():
    """The four things asked for: ETA, MB/s, chapters queued, and a way back
    into the app."""
    from mangasurf.tray import TrayController

    data = {
        "active": 2, "queued": 3,
        "chapters_done": 7, "chapters_total": 40, "chapters_remaining": 33,
        "pages_done": 812, "pages_total": 4100,
        "speed_text": "2.4 MB/s", "eta_text": "4m 12s",
        "downloaded_text": "318.4 MB",
        "jobs": [{"title": "Solo Leveling", "chapters_done": 4,
                  "chapters_total": 20}],
    }
    lines = TrayController(callbacks={"summary": lambda: data})._menu_lines()
    blob = "\n".join(lines)

    assert "2.4 MB/s" in blob
    assert "4m 12s" in blob
    assert "33 left" in blob
    assert "3 waiting" in blob
    assert "Solo Leveling" in blob


def test_menu_is_honest_when_idle():
    from mangasurf.tray import TrayController

    controller = TrayController(
        callbacks={"summary": lambda: {"active": 0, "queued": 0}})
    assert controller._menu_lines() == ["No active downloads"]
    assert "idle" in controller.tooltip()


def test_tooltip_reports_live_figures():
    from mangasurf.tray import TrayController

    data = {"active": 1, "queued": 2, "chapters_remaining": 9,
            "speed_text": "900 KB/s", "eta_text": "2m 00s"}
    tip = TrayController(callbacks={"summary": lambda: data}).tooltip()
    assert "900 KB/s" in tip and "2m 00s" in tip and "9 ch left" in tip


def test_menu_caps_the_job_list():
    """A hundred queued series must not produce a hundred menu rows."""
    from mangasurf.tray import TrayController

    jobs = [{"title": f"S{i}", "chapters_done": 0, "chapters_total": 3}
            for i in range(12)]
    data = {"active": 12, "queued": 0, "chapters_done": 0,
            "chapters_total": 36, "chapters_remaining": 36,
            "speed_text": "1 MB/s", "eta_text": "1m", "jobs": jobs}
    lines = TrayController(callbacks={"summary": lambda: data})._menu_lines()
    assert sum(1 for line in lines if line.startswith("   •")) <= 6
    assert any("more" in line for line in lines)


def test_summary_failure_does_not_break_the_menu():
    from mangasurf.tray import TrayController

    def boom():
        raise RuntimeError("nope")

    controller = TrayController(callbacks={"summary": boom})
    assert controller._menu_lines()          # still renders
    assert controller.tooltip()


def test_icon_renders_both_states():
    from mangasurf.tray import _build_icon_image

    idle = _build_icon_image(False)
    busy = _build_icon_image(True)
    assert idle is not None and busy is not None
    assert idle.size == busy.size
    assert idle.tobytes() != busy.tobytes()


def test_start_returns_false_without_a_tray():
    """The caller must be able to fall back to close-quits behaviour."""
    from mangasurf.tray import TrayController, tray_available

    if tray_available():
        pytest.skip("a real tray is available here")
    assert TrayController().start() is False


# ============================================== GUI tray integration


def test_close_hides_the_window_while_the_tray_holds_the_app():
    from mangasurf.gui import _install_tray

    _install_fake_pystray()
    from mangasurf.config import update_settings
    update_settings({"minimize_to_tray": True})

    api, window = _FakeApi(), _FakeWindow()
    controller = _install_tray(api, window)
    assert controller is not None

    closing = window.events.closing.handlers[0]
    assert closing() is False, "close must be vetoed"
    assert window.hidden is True
    controller.stop()


def test_quit_from_the_tray_really_exits():
    from mangasurf.gui import _install_tray

    _install_fake_pystray()
    from mangasurf.config import update_settings
    update_settings({"minimize_to_tray": True})

    api, window = _FakeApi(), _FakeWindow()
    controller = _install_tray(api, window)
    controller._on_quit()

    assert api._really_quitting is True
    assert window.destroyed is True
    # ...and after Quit the close is allowed through.
    assert window.events.closing.handlers[0]() is True


def test_tray_is_not_installed_when_the_setting_is_off():
    from mangasurf.config import update_settings
    from mangasurf.gui import _install_tray

    _install_fake_pystray()
    update_settings({"minimize_to_tray": False})
    assert _install_tray(_FakeApi(), _FakeWindow()) is None


def test_shutdown_is_skipped_while_the_tray_holds_the_app():
    """Tearing down sessions on close would break the very downloads the
    tray exists to keep running."""
    source = read(os.path.join(ROOT, "mangasurf", "gui", "__init__.py"))
    handler = source[source.index("def _on_closed():"):]
    handler = handler[:handler.index("window.events.closed")]
    assert "_really_quitting" in handler


def test_paused_queue_does_not_start_new_jobs():
    from mangasurf.gui import Api

    api = Api()
    api.set_queue_paused(True)
    api._cart.append({"options": {"url": "https://example.com/x"},
                      "title": "X", "cover": ""})
    assert api._start_queued() == []
    assert api.set_queue_paused(False)["paused"] is False


def test_progress_endpoint_shape():
    from mangasurf.gui import Api

    data = Api().get_progress()
    for key in ("active", "queued", "speed_text", "eta_text",
                "chapters_remaining", "paused"):
        assert key in data, key


# =============================================== crash-safe resume


def test_two_concurrent_jobs_are_both_journaled(tmp_path, monkeypatch):
    """The bug: the journal was one file, so starting B overwrote A and A
    could never be resumed."""
    _isolate_journal(tmp_path, monkeypatch)
    from mangasurf import logs

    logs.write_journal({"url": "https://a/x"}, {"title": "A"}, job_id="j1")
    logs.write_journal({"url": "https://b/y"}, {"title": "B"}, job_id="j2")

    titles = {j["title"] for j in logs.read_journals()}
    assert titles == {"A", "B"}


def test_one_job_finishing_does_not_wipe_the_other(tmp_path, monkeypatch):
    """The second bug: whichever job finished first called clear_journal()
    and erased the record of the one still running."""
    _isolate_journal(tmp_path, monkeypatch)
    from mangasurf import logs

    logs.write_journal({"url": "https://a/x"}, {"title": "A"}, job_id="j1")
    logs.write_journal({"url": "https://b/y"}, {"title": "B"}, job_id="j2")
    logs.clear_journal("j2")

    assert [j["title"] for j in logs.read_journals()] == ["A"]


def test_engine_clears_only_its_own_journal():
    source = read(os.path.join(ROOT, "mangasurf", "downloader.py"))
    assert "clear_journal(self.job_id)" in source
    assert "write_journal" in source and "job_id=self.job_id" in source


def test_legacy_single_file_journal_is_migrated(tmp_path, monkeypatch):
    import json

    _isolate_journal(tmp_path, monkeypatch)
    from mangasurf import logs

    os.makedirs(os.path.dirname(logs.JOURNAL_PATH), exist_ok=True)
    with open(logs.JOURNAL_PATH, "w", encoding="utf-8") as f:
        json.dump({"options": {"url": "https://old/x"}, "title": "Legacy"}, f)

    assert [j["title"] for j in logs.read_journals()] == ["Legacy"]
    assert not os.path.exists(logs.JOURNAL_PATH)


def test_a_truncated_journal_is_dropped_not_fatal(tmp_path, monkeypatch):
    """A crash mid-write must not poison every future read."""
    _isolate_journal(tmp_path, monkeypatch)
    from mangasurf import logs

    logs.write_journal({"url": "https://a/x"}, {"title": "Good"}, job_id="ok")
    os.makedirs(logs.JOBS_DIR, exist_ok=True)
    with open(os.path.join(logs.JOBS_DIR, "bad.json"), "w") as f:
        f.write('{"options": {"url"')      # truncated

    assert [j["title"] for j in logs.read_journals()] == ["Good"]


def test_journal_writes_are_atomic_and_fsynced():
    """A partially written journal reads back as "no job", losing the
    resume record precisely when it is needed."""
    source = read(os.path.join(ROOT, "mangasurf", "logs.py"))
    body = source[source.index("def write_journal"):source.index("def _migrate")]
    assert "os.replace" in body
    assert "os.fsync" in body


def test_gui_reports_every_pending_job(tmp_path, monkeypatch):
    _isolate_journal(tmp_path, monkeypatch)
    from mangasurf import logs
    from mangasurf.gui import Api

    logs.write_journal({"url": "https://a/x"}, {"title": "A"}, job_id="j1")
    logs.write_journal({"url": "https://b/y"}, {"title": "B"}, job_id="j2")

    result = Api().get_pending_job()
    assert {p["title"] for p in result["pending_all"]} == {"A", "B"}
    assert result["pending"] is not None          # back-compat


def test_cli_resume_survives_piped_input():
    """The second prompt lacked the EOF guard the first has, so a piped "n"
    crashed with EOFError instead of exiting cleanly."""
    source = read(os.path.join(ROOT, "mangasurf", "cli.py"))
    body = source[source.index("def cmd_resume"):source.index("def cmd_download")]
    assert body.count("except (KeyboardInterrupt, EOFError)") >= 2


# ------------------------------------------------------------- helpers


def _isolate_journal(tmp_path, monkeypatch):
    """Point the journal at a temp dir for one test."""
    from mangasurf import logs

    base = str(tmp_path)
    monkeypatch.setattr(logs, "BASE_DIR", base)
    monkeypatch.setattr(logs, "JOBS_DIR", os.path.join(base, "jobs"))
    monkeypatch.setattr(logs, "JOURNAL_PATH", os.path.join(base, "job.json"))


class _Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


class _FakeWindow:
    def __init__(self):
        self.events = type("E", (), {"closing": _Event(),
                                     "closed": _Event()})()
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


class _FakeApi:
    _queue_paused = False
    _really_quitting = False

    def shutdown(self):
        return {"ok": True}

    def set_queue_paused(self, paused=None):
        return {"ok": True, "paused": False}

    def get_progress(self):
        return {"ok": True, "active": 0, "queued": 0}


def _install_fake_pystray():
    """A pystray stand-in, so tray wiring is testable without a desktop."""
    import types

    module = types.ModuleType("pystray")

    class Menu(list):
        SEPARATOR = object()

        def __init__(self, generator=None):
            super().__init__()

    class MenuItem:
        def __init__(self, text, action, **kwargs):
            self.text = text
            self.action = action

    class Icon:
        def __init__(self, name, icon=None, title=None, menu=None):
            self.name = name
            self.icon = icon
            self.title = title
            self.menu = menu
            self.notes = []
            self._alive = True

        def run(self):
            while self._alive:
                time.sleep(0.02)

        def stop(self):
            self._alive = False

        def update_menu(self):
            pass

        def notify(self, message, title=None):
            self.notes.append(message)

    module.Icon = Icon
    module.Menu = Menu
    module.MenuItem = MenuItem
    sys.modules["pystray"] = module
    return module
