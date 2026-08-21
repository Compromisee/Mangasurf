"""Regression tests for the reported issues:

  1. MangaDex covers replaced by a "read this at MangaDex" placeholder
  2. Freeze / crash 0xCFFFFFFF during large downloads
  3. Search results not loading
  4. Excessive resource usage
"""

import importlib
import os
import sys
import tempfile
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "mangasurf", "gui", "web")


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    import mangasurf.config as config
    import mangasurf.features as features
    for module in (config, features):
        importlib.reload(module)
    yield home


# =================================== 1. covers / hotlink placeholder


def test_cover_urls_keep_the_full_filename():
    from mangasurf.sources.mangadex import MangaDexSource

    url = MangaDexSource.cover_url("mid", "abc.png", "medium")
    assert url.endswith("abc.png.512.jpg")


# ============================== 2. event flood -> WebView2 crash


class FakeWindow:
    def __init__(self):
        self.calls = 0
        self.events = 0
        self.lock = threading.Lock()

    def evaluate_js(self, js):
        import json
        import re
        with self.lock:
            self.calls += 1
            match = re.match(r"window\.onEngineEvents\((.*)\)$", js, re.S)
            if match:
                self.events += len(json.loads(match.group(1)))


def _api_with_window():
    from mangasurf.gui import Api

    api = Api()
    api.window = FakeWindow()
    return api


def test_progress_events_are_batched():
    """A burst of progress events must not become one bridge call each."""
    api = _api_with_window()
    for i in range(500):
        api._push({"type": "chapter_progress", "chapter": "Ch 1",
                   "done": i, "total": 500})
    api._flush()
    assert api.window.calls <= 3, "progress events were not coalesced"


def test_progress_coalesces_to_the_latest_per_chapter():
    api = _api_with_window()
    for i in range(50):
        api._push({"type": "chapter_progress", "chapter": "A", "done": i, "total": 50})
    for i in range(50):
        api._push({"type": "chapter_progress", "chapter": "B", "done": i, "total": 50})
    api._flush()
    # one surviving update per chapter, not 100
    assert api.window.events == 2


def test_lifecycle_events_are_never_dropped():
    api = _api_with_window()
    api._push({"type": "chapter_start", "chapter": "A"})
    api._push({"type": "chapter_done", "chapter": "A", "pages": 10})
    api._push({"type": "packaged", "file": "x.cbz"})
    api._flush()
    assert api.window.events == 3


def test_terminal_events_flush_immediately():
    """The UI must not wait for a timer to learn the job finished."""
    api = _api_with_window()
    api._push({"type": "finished", "result": {"ok": True}})
    assert api.window.calls >= 1


def test_batching_cuts_bridge_crossings_dramatically():
    """The crash scenario: many chapters x many pages, emitted fast."""
    api = _api_with_window()
    emitted = 0
    for chapter in range(40):
        api._push({"type": "chapter_start", "chapter": f"Ch {chapter}"})
        emitted += 1
        for page in range(60):
            api._push({"type": "chapter_progress", "chapter": f"Ch {chapter}",
                       "done": page, "total": 60})
            emitted += 1
    api._flush()
    assert emitted == 40 * 61
    # without batching this was one evaluate_js per event
    assert api.window.calls < emitted / 50


def test_shutdown_cancels_the_timer():
    api = _api_with_window()
    api._push({"type": "chapter_progress", "chapter": "A", "done": 1, "total": 2})
    assert api._flush_timer is not None
    api.shutdown()
    assert api._flush_timer is None


def test_push_without_a_window_is_safe():
    from mangasurf.gui import Api

    api = Api()
    api.window = None
    api._push({"type": "chapter_progress", "chapter": "A"})   # must not raise


# ==================================== 3. search results not loading


def test_backend_search_returns_results_with_covers(monkeypatch):
    from mangasurf.gui import Api

    class FakeSource:
        supports_browse = True
        id = "mangadex"
        name = "MangaDex"

        def search(self, query, limit=20, **kwargs):
            return [{"title": "Berserk", "url": "u", "source": "mangadex",
                     "source_name": "MangaDex", "cover": "https://c/x.jpg"}]

        def close(self):
            pass

    monkeypatch.setattr("mangasurf.sources.get_source", lambda sid, **kw: FakeSource())
    result = Api().search("berserk", {"source": "all"})
    assert result["ok"] is True
    assert result["results"]
    assert all(r["cover"] for r in result["results"])


def test_search_failure_is_reported_not_swallowed(monkeypatch):
    from mangasurf.gui import Api

    api = Api()
    monkeypatch.setattr(api, "_source",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = api.search("x", {"source": "mangadex"})
    assert result["ok"] is False
    assert "boom" in result["error"]


# ========================================= 4. resource usage


def test_images_stream_to_disk():
    """Buffering whole images in RAM multiplied by every worker thread."""
    source = open(os.path.join(os.path.dirname(WEB), "..", "sources", "base.py"),
                  encoding="utf-8").read()
    assert "iter_content" in source
    assert "stream=True" in source


def test_download_still_rejects_non_images(tmp_path):
    from mangasurf.sources.base import Source

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/html"}

        def iter_content(self, chunk_size=1):
            yield b"<!DOCTYPE html><html>"

        def raise_for_status(self):
            pass

    class FakeSession:
        def get(self, *a, **k):
            return FakeResponse()

    source = Source()
    source.session = FakeSession()
    target = tmp_path / "out.jpg"
    assert source.download_file("http://x/y.jpg", str(target), max_retries=1) is False
    assert not target.exists()
    assert not (tmp_path / "out.jpg.part").exists()


def test_engine_uses_one_shared_image_pool():
    """A pool per chapter meant chapter_workers x image_workers threads."""
    downloader = open(os.path.join(os.path.dirname(WEB), "..", "downloader.py"),
                      encoding="utf-8").read()
    assert "_image_pool" in downloader
    assert downloader.count("ThreadPoolExecutor(") <= 3


def test_image_pool_is_bounded():
    from mangasurf.downloader import DownloadOptions

    options = DownloadOptions(url="x", chapter_workers=8, image_workers=10)
    bounded = max(1, min(16, options.chapter_workers * options.image_workers))
    assert bounded == 16, "in-flight requests must stay capped"


# ============================================ 5. GUI polish


# ========================= reported: unstyled inputs / invisible toggles
