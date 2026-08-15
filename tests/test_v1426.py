"""v1.4.26 regression tests.

* reopening from the tray must not tear the app down
* the already-downloaded result modes (show / darken / hide)
* FEATURES.md is readable prose, not a wall of numbers
"""

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


def read(path):
    return open(path, encoding="utf-8").read()


# ======================================================= tray reopen


def test_hold_does_not_end_on_an_idle_queue():
    """An empty queue must not release the hold.

    v1.4.24 ended the wait as soon as nothing was downloading. Closing to
    the tray with an idle queue then tore the process down ~0.7s later, so
    clicking "Open ReaderM" flashed the window and lost it. Guard the
    predicate directly, because the subprocess tests are slow.
    """
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def _hold_for_tray("):]
    body = body[:body.index("\ndef ")]
    predicate = body[body.index("def keep_holding"):body.index("logger.info")]
    assert "get_progress" not in predicate, (
        "the hold must not end just because the queue is idle")
    assert "_really_quitting" in predicate


def test_show_window_is_not_racing_a_shutdown():
    """Reopening must clear the hidden flag, never trigger teardown."""
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def show_window():"):]
    body = body[:body.index("def quit_app():")]
    assert "_hidden_to_tray = False" in body
    assert "shutdown" not in body


# ============================================ downloaded_status API


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import config, features, library
    for module in (config, features, library):
        importlib.reload(module)
    import readerm.gui as gui
    importlib.reload(gui)
    return gui, library


def test_downloaded_status_reports_a_real_percentage(api):
    gui, library = api
    for i in range(12):
        library.record_chapter("https://x/solo", "Solo Leveling",
                               f"Chapter {i + 1}", pages=20)

    res = gui.Api().downloaded_status([
        {"url": "https://x/solo", "title": "Solo Leveling", "last_chapter": 200},
    ])
    assert res["ok"]
    row = res["status"]["https://x/solo"]
    assert row["chapters"] == 12
    assert row["total"] == 200
    assert row["percent"] == 6
    assert row["complete"] is False


def test_unknown_total_never_becomes_a_fake_percentage(api):
    """A source that does not report a chapter count must not make a
    partly-downloaded series look finished."""
    gui, library = api
    for i in range(5):
        library.record_chapter("https://x/mystery", "Mystery",
                               f"Chapter {i + 1}", pages=10)

    res = gui.Api().downloaded_status([{"url": "https://x/mystery"}])
    row = res["status"]["https://x/mystery"]
    assert row["total"] == 0
    assert row["percent"] is None, "invented a percentage from an unknown total"
    assert row["complete"] is False
    assert row["chapters"] == 5


def test_a_complete_series_is_flagged(api):
    gui, library = api
    for i in range(20):
        library.record_chapter("https://x/done", "Done", f"Chapter {i + 1}")

    res = gui.Api().downloaded_status([
        {"url": "https://x/done", "last_chapter": 20}])
    row = res["status"]["https://x/done"]
    assert row["percent"] == 100
    assert row["complete"] is True


def test_results_you_do_not_have_are_omitted(api):
    """Only hits come back, so a page of unknown results stays cheap."""
    gui, library = api
    library.record_chapter("https://x/have", "Have", "Chapter 1")

    res = gui.Api().downloaded_status([
        {"url": "https://x/have"},
        {"url": "https://x/not-have"},
        {"url": "https://x/also-not"},
    ])
    assert set(res["status"]) == {"https://x/have"}


def test_empty_and_malformed_input_is_safe(api):
    gui, _ = api
    assert gui.Api().downloaded_status([])["status"] == {}
    assert gui.Api().downloaded_status(None)["status"] == {}
    assert gui.Api().downloaded_status(["nonsense", {}, {"no": "url"}])["status"] == {}


def test_percent_is_capped_when_the_library_leads_the_source(api):
    """Sources under-report their own totals often enough that this happens."""
    gui, library = api
    for i in range(30):
        library.record_chapter("https://x/ahead", "Ahead", f"Chapter {i + 1}")

    res = gui.Api().downloaded_status([
        {"url": "https://x/ahead", "last_chapter": 10}])
    row = res["status"]["https://x/ahead"]
    assert row["percent"] == 100, "percentage must never exceed 100"
    assert row["complete"] is True


def test_setting_exists_with_a_sane_default():
    from readerm.gui import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["downloaded_results"] == "darken"


# ==================================================== FEATURES.md shape


def test_features_is_not_a_wall_of_numbers():
    """It was 816 lines of "541. ..." ordered by release, which is a
    changelog wearing a feature list's clothes."""
    text = read(os.path.join(ROOT, "MD", "FEATURES.md"))
    numbered = [l for l in text.splitlines() if re.match(r"^\d+\.\s", l)]
    assert len(numbered) < 20, (
        f"{len(numbered)} numbered feature lines remain; group them by topic")


def test_features_is_organised_by_topic_not_by_version():
    text = read(os.path.join(ROOT, "MD", "FEATURES.md"))
    headings = re.findall(r"^##\s+(.+)$", text, re.M)
    assert len(headings) >= 12, "expected a topic per section"
    versioned = [h for h in headings if re.search(r"v?\d+\.\d+\.\d+", h)]
    assert versioned == [], f"version-titled sections remain: {versioned}"


def test_features_has_a_table_of_contents():
    text = read(os.path.join(ROOT, "MD", "FEATURES.md"))
    # GitHub's slug rule: lowercase, drop punctuation, spaces to hyphens --
    # but existing hyphens are KEPT. The old version stripped them, so a
    # heading like "Reading it in an e-reader" produced "ereader" here and
    # a correct link looked broken.
    headings = {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
                for h in re.findall(r"^##\s+(.+)$", text, re.M)}
    links = set(re.findall(r"\]\(#([a-z0-9-]+)\)", text))
    assert links, "no table of contents"
    missing = links - headings
    assert missing == set(), f"contents links with no section: {missing}"


def test_features_documents_the_new_setting():
    text = read(os.path.join(ROOT, "MD", "FEATURES.md"))
    assert "Already downloaded" in text
    for mode in ("Darken", "Hide"):
        assert mode in text


def test_features_source_table_matches_the_registry():
    """The table lists sites by hand, so it can drift from the code."""
    from readerm.sources import list_sources

    text = read(os.path.join(ROOT, "MD", "FEATURES.md"))
    table = text[text.index("### Registered sources"):]
    table = table[:table.index("**Madara Sites** is a single entry")]
    listed = {re.sub(r"[*`]", "", row.split("|")[1]).strip().lower()
              for row in table.splitlines() if row.startswith("|")}
    real = {m["name"].lower() for m in list_sources()}
    assert real <= listed, f"missing from FEATURES.md: {real - listed}"


def test_no_stale_counts_in_features():
    from readerm.sources import SOURCE_CLASSES

    text = read(os.path.join(ROOT, "MD", "FEATURES.md"))
    assert f"{len(SOURCE_CLASSES)} registered" in text


# ========================================================== browser


playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright is not installed")

PAGE_URL = "file://" + os.path.join(WEB, "index.html")

RESULTS = [
    {"title": "Solo Leveling", "url": "https://x/solo", "source": "mangadex",
     "source_name": "MangaDex", "last_chapter": 200},
    {"title": "Berserk", "url": "https://x/berserk", "source": "mangadex",
     "source_name": "MangaDex", "last_chapter": 380},
    {"title": "Monster", "url": "https://x/monster", "source": "mangadex",
     "source_name": "MangaDex"},
    {"title": "Pluto", "url": "https://x/pluto", "source": "mangadex",
     "source_name": "MangaDex", "last_chapter": 65},
]

STATUS = {
    "https://x/solo": {"chapters": 100, "total": 200, "percent": 50,
                       "complete": False, "title": "Solo Leveling"},
    "https://x/berserk": {"chapters": 380, "total": 380, "percent": 100,
                          "complete": True, "title": "Berserk"},
    "https://x/monster": {"chapters": 7, "total": 0, "percent": None,
                          "complete": False, "title": "Monster"},
}

BRIDGE = """
(() => {
  const ok = (e) => Object.assign({ok:true}, e||{});
  const settings = %(settings)s;
  const api = {
    get_settings: async () => settings,
    set_settings: async (s) => { Object.assign(settings, s); return ok(); },
    check_lock: async () => ({locked:false, enabled:false}),
    get_sources: async () => ok({sources:[]}),
    get_genres: async () => ok({genres:[]}),
    get_tray_state: async () => ok({available:true,enabled:false,running:false}),
    get_cart: async () => ok({queued:[]}),
    get_progress: async () => ok({active:0, jobs:[]}),
    get_stats: async () => ok({stats:{totals:{},derived:{},sources:{},days:{}}}),
    get_insights: async () => ok({insights:{}}),
    get_calendar: async () => ok({calendar:null}),
    search: async () => ok({results: %(results)s}),
    trending: async () => ok({results: %(results)s}),
    browse: async () => ok({results: %(results)s}),
    downloaded_status: async () => ok({status: %(status)s}),
  };
  window.pywebview = {api: new Proxy(api, {
    get: (t,k) => (k in t) ? t[k] : (async () => ({ok:true})),
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


def open_page(browser, mode):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.errors = []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.add_init_script(BRIDGE % {
        "settings": json.dumps({"theme": "midnight", "accent": "teal",
                                "output_dir": "/tmp/out",
                                "downloaded_results": mode}),
        "results": json.dumps(RESULTS),
        "status": json.dumps(STATUS),
    })
    page.goto(PAGE_URL)
    page.wait_for_timeout(900)
    return page
