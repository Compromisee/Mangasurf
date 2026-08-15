"""Regression tests for v1.4.5.

Covers:

* ManhwaRead bulk downloads losing chapters to unpadded base64.
* The connection pool being smaller than the worker count.
* Concurrent downloads of different manga mixing chapter progress.
* The download cart / queue.

Everything here is offline. The live behaviour these encode was measured
while fixing the bugs and is quoted in the relevant docstrings.
"""

import base64
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ========================================================== manhwaread


def test_unpadded_base64_decodes():
    """The site strips ``=`` padding when the length is not a multiple of 4.

    Measured over twelve consecutive chapters of one series: chapter 03 had
    ``len % 4 == 2`` and raised ``binascii.Error: Incorrect padding`` while
    the other eleven decoded fine. That is ~8% of chapters, which is why a
    single-chapter download usually worked and a bulk range reliably failed.
    """
    from readerm.sources.manhwaread import ManhwaReadSource

    # Build a payload whose base64 genuinely carries "=" padding, i.e. the
    # raw byte length is not a multiple of three. The site emits exactly
    # this with the padding removed.
    pages = [{"src": "126201/mr_001.jpg", "w": 800, "h": 5000}]
    raw = json.dumps(pages)
    while len(raw.encode()) % 3 == 0:
        raw += " "
    encoded = base64.b64encode(raw.encode()).decode()
    stripped = encoded.rstrip("=")
    assert stripped != encoded, "payload should need padding"

    decoded = ManhwaReadSource.decode_payload(stripped)
    assert json.loads(decoded) == pages


def test_padded_base64_still_decodes():
    from readerm.sources.manhwaread import ManhwaReadSource

    payload = [{"src": "1/a.jpg"}]
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    assert json.loads(ManhwaReadSource.decode_payload(encoded)) == payload


@pytest.mark.parametrize("length_mod", [0, 1, 2, 3])
def test_every_padding_offset_decodes(length_mod):
    """Whatever the remainder, re-padding must produce valid output."""
    from readerm.sources.manhwaread import ManhwaReadSource

    blob = b"x" * (30 + length_mod)
    encoded = base64.b64encode(blob).decode().rstrip("=")
    out = ManhwaReadSource.decode_payload(encoded)
    assert out.startswith("x")


def test_decoder_ignores_whitespace():
    from readerm.sources.manhwaread import ManhwaReadSource

    encoded = base64.b64encode(b"hello world").decode()
    spaced = "  " + encoded[:4] + "\n" + encoded[4:] + " "
    assert ManhwaReadSource.decode_payload(spaced).strip() == "hello world"


def test_source_uses_the_tolerant_decoder():
    """A raw b64decode here is what broke bulk downloads."""
    src = read(os.path.join(ROOT, "readerm", "sources", "manhwaread.py"))
    body = src[src.index("def get_chapter_images"):]
    assert "decode_payload" in body
    assert "base64.b64decode(payload" not in body


# ======================================================= connection pool


def test_connection_pool_covers_every_worker():
    """urllib3 pools ten connections by default but the engine runs up to
    sixteen image threads, so connections were discarded and reopened."""
    from readerm.sources.base import Source

    assert Source.POOL_SIZE >= 16


def test_session_is_mounted_with_the_wider_pool():
    from readerm.sources.mangadex import MangaDexSource

    source = MangaDexSource()
    try:
        for prefix in ("http://", "https://"):
            adapter = source.session.get_adapter(prefix)
            assert adapter._pool_maxsize >= 16
            assert adapter._pool_connections >= 16
    finally:
        source.close()


# ============================================== concurrent job isolation


def test_progress_is_keyed_on_job_and_chapter():
    """Two manga both reporting "Chapter 01" must not collapse into one.

    The coalescing map used to be keyed on the chapter name alone, so the
    newest event silently replaced the other series' progress.
    """
    from readerm.gui import Api

    api = Api.__new__(Api)
    api.window = object()          # not None, so _push does not bail out
    api._push_lock = __import__("threading").Lock()
    api._pending_events = []
    api._pending_progress = {}
    api._flush_timer = None
    api._flush = lambda: None

    api._push({"type": "chapter_progress", "job": "job1",
               "chapter": "Chapter 01", "done": 5, "total": 30})
    api._push({"type": "chapter_progress", "job": "job2",
               "chapter": "Chapter 01", "done": 1, "total": 12})

    assert len(api._pending_progress) == 2
    kept = {(k[0], v["done"]) for k, v in api._pending_progress.items()}
    assert kept == {("job1", 5), ("job2", 1)}


def test_same_job_same_chapter_still_coalesces():
    """Only the newest progress for one chapter of one job is kept."""
    from readerm.gui import Api

    api = Api.__new__(Api)
    api.window = object()
    api._push_lock = __import__("threading").Lock()
    api._pending_events = []
    api._pending_progress = {}
    api._flush_timer = None
    api._flush = lambda: None

    for done in (1, 2, 3):
        api._push({"type": "chapter_progress", "job": "job1",
                   "chapter": "Chapter 01", "done": done, "total": 30})

    assert len(api._pending_progress) == 1
    assert list(api._pending_progress.values())[0]["done"] == 3


def test_events_are_stamped_with_their_job():
    from readerm.gui import Api

    api = Api.__new__(Api)
    api._jobs = {"job7": {"id": "job7", "title": "Berserk"}}
    seen = []
    api._push = seen.append

    api._job_event("job7")({"type": "chapter_start", "chapter": "Chapter 01"})
    assert seen[0]["job"] == "job7"
    assert seen[0]["job_title"] == "Berserk"


# =================================================================== cart


def _fresh_api():
    from readerm.gui import Api

    api = Api()
    return api


def test_cart_starts_empty():
    api = _fresh_api()
    cart = api.get_cart()
    assert cart["ok"] and cart["jobs"] == [] and cart["queued"] == []


def test_cart_rejects_an_entry_with_no_url():
    api = _fresh_api()
    assert api.add_to_cart({})["ok"] is False
    assert api.add_to_cart({"url": "  "})["ok"] is False


def test_cart_queues_past_the_concurrency_limit(monkeypatch):
    """Entries beyond the limit wait rather than being rejected."""
    api = _fresh_api()
    monkeypatch.setattr(api, "max_concurrent_jobs", lambda: 2)
    spawned = []

    def fake_spawn(entry):
        record = {"id": f"job{len(spawned) + 1}", "status": "running",
                  "url": entry["options"]["url"], "selection": "all",
                  "title": entry.get("title", ""), "cover": "",
                  "source": "", "engine": None, "result": None}
        api._jobs[record["id"]] = record
        spawned.append(record)
        return record

    monkeypatch.setattr(api, "_spawn", fake_spawn)

    for i in range(4):
        api.add_to_cart({"url": f"https://x/{i}", "selection": "all"})

    assert len(spawned) == 2, "concurrency limit not honoured"
    assert len(api.get_cart()["queued"]) == 2


def test_cart_refuses_duplicates(monkeypatch):
    api = _fresh_api()
    monkeypatch.setattr(api, "max_concurrent_jobs", lambda: 1)
    monkeypatch.setattr(api, "_spawn", lambda e: api._jobs.setdefault(
        "job1", {"id": "job1", "status": "running", "url": e["options"]["url"],
                 "selection": e["options"].get("selection", "all"),
                 "title": "", "cover": "", "source": "", "engine": None,
                 "result": None}))

    api.add_to_cart({"url": "https://x/1", "selection": "all"})
    again = api.add_to_cart({"url": "https://x/1", "selection": "all"})
    assert again["ok"] is False
    assert "already" in again["error"].lower()


def test_cart_entries_can_be_removed(monkeypatch):
    api = _fresh_api()
    monkeypatch.setattr(api, "max_concurrent_jobs", lambda: 0 or 1)
    monkeypatch.setattr(api, "_spawn", lambda e: api._jobs.setdefault(
        "job1", {"id": "job1", "status": "running", "url": "taken",
                 "selection": "all", "title": "", "cover": "", "source": "",
                 "engine": None, "result": None}))

    api.add_to_cart({"url": "https://x/1", "selection": "all"})   # runs
    api.add_to_cart({"url": "https://x/2", "selection": "all"})   # queued
    assert len(api.get_cart()["queued"]) == 1

    assert api.remove_from_cart("https://x/2")["removed"] == 1
    assert api.get_cart()["queued"] == []


def test_clear_cart_empties_the_queue(monkeypatch):
    api = _fresh_api()
    monkeypatch.setattr(api, "max_concurrent_jobs", lambda: 1)
    monkeypatch.setattr(api, "_spawn", lambda e: api._jobs.setdefault(
        "job1", {"id": "job1", "status": "running", "url": "taken",
                 "selection": "all", "title": "", "cover": "", "source": "",
                 "engine": None, "result": None}))

    for i in range(3):
        api.add_to_cart({"url": f"https://x/{i}", "selection": "all"})
    assert api.clear_cart()["removed"] == 2
    assert api.get_cart()["queued"] == []


def test_concurrency_limit_is_clamped(monkeypatch):
    from readerm import gui as guimod

    api = _fresh_api()
    # 0 and None are meaningless here and fall back to the default of 2
    # (``... or 2``); everything else is clamped into 1..5.
    for value, expected in ((0, 2), (None, 2), (1, 1), (3, 3), (99, 5),
                            (-4, 1), ("x", 2)):
        monkeypatch.setattr(guimod, "load_settings",
                            lambda v=value: {"max_concurrent_jobs": v})
        assert api.max_concurrent_jobs() == expected


def test_stop_targets_one_job_only():
    """Stopping one download must not touch the others."""
    api = _fresh_api()

    class FakeEngine:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    a, b = FakeEngine(), FakeEngine()
    api._jobs = {
        "job1": {"id": "job1", "status": "running", "engine": a},
        "job2": {"id": "job2", "status": "running", "engine": b},
    }
    api._flush = lambda: None
    api.stop_download("job1")
    assert a.stopped is True
    assert b.stopped is False


def test_stop_without_an_id_stops_everything():
    api = _fresh_api()

    class FakeEngine:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    a, b = FakeEngine(), FakeEngine()
    api._jobs = {
        "job1": {"id": "job1", "status": "running", "engine": a},
        "job2": {"id": "job2", "status": "running", "engine": b},
    }
    api._cart = [{"options": {"url": "x"}}]
    api._flush = lambda: None
    api.stop_download()
    assert a.stopped and b.stopped
    assert api._cart == [], "a blanket stop should also drop the queue"


def test_a_stopped_job_is_not_reported_as_failed():
    src = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = src[src.index("def _run_job"):src.index("def _spawn")]
    assert '"stopped"' in body


# ================================================================= UI


def test_cart_api_is_reachable_from_js():
    from readerm.gui import Api

    for method in ("add_to_cart", "get_cart", "remove_from_cart",
                   "clear_cart", "max_concurrent_jobs"):
        assert callable(getattr(Api, method, None)), method


def test_max_concurrent_jobs_has_a_default():
    from readerm.gui import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["max_concurrent_jobs"] >= 1
