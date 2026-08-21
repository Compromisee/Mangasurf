"""v3.2.3 — scrolling, slider fills, search, and the pages that were missing.

Reported, and each reproduced before it was fixed:

* the reader would not scroll -- a full-bleed tap-zone overlay swallowed the
  wheel, measured `scrollTop` still 0 after a 900px wheel over a 15,728px strip;
* the four reader-panel sliders never repainted their fill, because they went
  through raw `addEventListener` instead of `bindSlider`;
* search died with ``'str' object has no attribute 'get'`` -- the front-end
  passed the source id as a string to an `Api.search(query, filters: dict)`;
* search was slow: 19 sources through a pool of 4;
* there was no way to see a series before downloading it, no bookmarks tab,
  and no genre / sort / status controls.
"""
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP = os.path.join(ROOT, "mangasurf", "reader", "app")


def read(name):
    with open(os.path.join(APP, name), encoding="utf-8") as handle:
        return handle.read()


# ──────────────────────────────────────────────────────── search: the API


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from mangasurf.gui import Api

    return Api()


def test_search_accepts_a_bare_source_string(api, monkeypatch):
    """The front-end called search(query, "mangadex"). Every such call died
    on `'str' object has no attribute 'get'`."""
    from mangasurf import sources

    monkeypatch.setattr(sources, "search_all", lambda *a, **k: [])
    result = api.search("solo", "mangadex")
    assert result.get("ok") is True, result


@pytest.mark.parametrize("filters", [None, {}, {"source": "mangadex"},
                                     ["junk"], 42, "mangadex"])
def test_search_never_raises_on_a_odd_filters_value(api, monkeypatch, filters):
    from mangasurf import sources

    monkeypatch.setattr(sources, "search_all", lambda *a, **k: [])
    result = api.search("solo", filters)
    assert isinstance(result, dict)
    # Asserting only that the message is not the *str* one let a list through
    # with "'list' object has no attribute 'get'". Any junk must simply work.
    assert result.get("ok") is True, result
    assert "has no attribute" not in str(result.get("error", "")), result


def test_the_source_string_is_treated_as_the_source(api, monkeypatch):
    seen = {}

    def fake(self, source_id, **kw):
        seen["id"] = source_id
        raise RuntimeError("stop here")

    monkeypatch.setattr(type(api), "_source", fake, raising=False)
    api.search("solo", "weebcentral")
    assert seen.get("id") == "weebcentral"


# ─────────────────────────────────────────────────── search: parallelism


def test_sources_are_searched_in_a_wide_pool():
    """19 sources through a pool of 4 is five sequential waves, and one slow
    site holds up the wave behind it. Measured over the full registry:
    4 workers 4.23s, 8 -> 2.53s, 12 -> 2.32s, 16 -> 2.58s."""
    from mangasurf.sources import SEARCH_WORKERS

    assert SEARCH_WORKERS >= 8, SEARCH_WORKERS


def test_search_and_browse_share_the_pool_size():
    """browse_all is the empty-query and genre path; it was left at 4."""
    import inspect

    from mangasurf import sources

    for fn in (sources.search_all, sources.browse_all):
        default = inspect.signature(fn).parameters["workers"].default
        assert default == sources.SEARCH_WORKERS, fn.__name__


def test_the_pool_never_exceeds_the_number_of_sources():
    """A pool wider than the work just makes idle threads."""
    source = read("../../sources/__init__.py") if False else open(
        os.path.join(ROOT, "mangasurf", "sources", "__init__.py"),
        encoding="utf-8").read()
    assert "min(workers, len(ids))" in source


# ────────────────────────────────────────────── scrolling and the sliders


def test_tap_zones_do_not_capture_the_wheel():
    """`#tapzones` is `inset: 0` over the page strip. With pointer events on,
    it swallowed the wheel and a webtoon chapter would not scroll at all."""
    css = read("style.css")
    block = css[css.index("#tapzones {"):]
    block = block[:block.index("}")]
    assert "pointer-events: none" in block, block


def test_the_tap_zones_themselves_stay_inert():
    """Re-enabling pointer events on the children put a hit target back over
    the strip and the wheel was captured again."""
    css = read("style.css")
    block = css[css.index("#tapzones .tap"):]
    block = block[:block.index("}") + 1]
    assert "pointer-events: auto" not in block, block


def test_tap_clicks_are_handled_on_the_reader():
    """An inert overlay receives no clicks, so the zone is worked out from
    the pointer position instead."""
    app = read("app.js")
    assert "$('#reader').addEventListener('click'" in app
    assert "bounds.width / 3" in app


def test_touch_scrolling_is_allowed_through_the_zones():
    css = read("style.css")
    block = css[css.index("#tapzones {"):]
    block = block[:block.index("}")]
    assert "touch-action" in block


@pytest.mark.parametrize("slider", ["r-width", "r-gap", "r-zoom", "r-auto-speed"])
def test_every_reader_slider_goes_through_bindslider(slider):
    """These four used raw addEventListener, so their fill never repainted --
    dragging zoom to 250 left `--fill` at the value the panel was built with."""
    app = read("app.js")
    assert f"bindSlider('#{slider}'" in app, slider
    assert f"$('#{slider}').addEventListener('input'" not in app, slider


@pytest.mark.parametrize("slider", ["r-width", "r-gap", "r-zoom", "r-auto-speed"])
def test_every_reader_slider_has_a_value_chip(slider):
    """bindSlider writes into `<id>-out`; without the element the value is
    computed and thrown away."""
    html = read("index.html")
    assert f'id="{slider}-out"' in html, slider


def test_the_hidden_attribute_beats_a_flex_display():
    """`.field { display: flex }` overrides the UA's `[hidden] { display: none }`,
    which left "Chapters per file" on screen while "Single file" was chosen."""
    css = read("style.css")
    assert "[hidden] { display: none !important; }" in css


# ───────────────────────────────────────────────────── the detail page


def test_the_detail_page_exists():
    html = read("index.html")
    for part in ("d-cover", "d-title", "d-tags", "d-desc", "d-facts",
                 "d-chapters", "d-download", "d-queue", "d-read"):
        assert f'id="{part}"' in html, part


def test_the_detail_page_has_the_chapter_tools():
    html = read("index.html")
    for part in ("d-range", "d-min", "d-max", "d-find", "d-sort", "d-hide-have"):
        assert f'id="{part}"' in html, part
    for pick in ("all", "none", "new", "latest", "invert"):
        assert f'data-pick="{pick}"' in html, pick


def test_a_result_card_opens_the_detail_page():
    app = read("app.js")
    assert "closest('[data-manga]')" in app
    assert "openDetail(manga.dataset.manga" in app


def test_a_library_card_offers_the_detail_page_too():
    """The Read button on that page is what enters the reader."""
    app = read("app.js")
    block = app[app.index("function renderLibrary"):]
    block = block[:block.index("\n}")]
    assert "data-manga=" in block


def test_the_read_button_opens_what_was_downloaded():
    app = read("app.js")
    block = app[app.index("$('#d-read').addEventListener"):]
    block = block[:block.index("})")]
    assert "openPath" in block


# ─────────────────────────────────────────────────── range parsing (unit)


RANGE_CASES = [
    ("1-5", 60, {1, 2, 3, 4, 5}),
    ("3", 60, {3}),
    ("1-3, 7", 60, {1, 2, 3, 7}),
    ("5-1", 60, {1, 2, 3, 4, 5}),          # reversed pair
    ("  2 - 4 ,, 9 ", 60, {2, 3, 4, 9}),   # whitespace and empties
    ("58-70", 60, {58, 59, 60}),           # clamped to the end
    ("0-2", 60, {1, 2}),                   # clamped at the start
    ("nonsense", 60, set()),
    ("", 60, set()),
]


@pytest.mark.parametrize("text,total,expected", RANGE_CASES)
def test_quick_select_ranges_parse(text, total, expected, tmp_path):
    """Run the real JS through node so the test cannot drift from the app."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node is not available")

    app = read("app.js")
    start = app.index("function parseRanges")
    end = app.index("\n}", start) + 2
    script = (app[start:end]
              + f"\nconsole.log(JSON.stringify([...parseRanges({text!r}, {total})].sort((a,b)=>a-b)))")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    assert set(json.loads(out.stdout)) == expected


# ──────────────────────────────────────────────────────── bookmarks tab


def test_the_bookmarks_tab_exists():
    html = read("index.html")
    assert 'data-view="marks"' in html
    for part in ("marks-grid", "marks-folder", "marks-filter", "marks-newfolder"):
        assert f'id="{part}"' in html, part


def test_the_bookmarks_tab_is_wired_to_the_backend():
    app = read("app.js")
    for method in ("get_bookmarks", "get_bookmark_folders",
                   "create_bookmark_folder", "delete_bookmark_folder"):
        assert method in app, method


def test_the_detail_page_can_bookmark_and_watch():
    app = read("app.js")
    assert "toggle_bookmark" in app
    assert "'unwatch'" in app and "'watch'" in app


# ──────────────────────────────────────────────── genres, sorts, filters


def test_the_refine_panel_has_sort_status_and_type():
    html = read("index.html")
    for part in ("srt-sort", "srt-order", "srt-status", "srt-type", "srt-match"):
        assert f'id="{part}"' in html, part


def test_genres_are_fetched_per_source():
    app = read("app.js")
    assert "get_genres" in app
    block = app[app.index("async function refreshGenres"):]
    block = block[:block.index("\n}")]
    assert "search-source" in block, "the genre list must follow the chosen source"


def test_search_sends_the_refined_options():
    app = read("app.js")
    block = app[app.index("const res = await call('search'"):]
    block = block[:block.index("})") + 2]
    for key in ("source", "sort", "order", "status", "type",
                "genres", "genre_match"):
        assert key in block, key


def test_an_empty_query_browses_instead_of_refusing():
    """Api.search treats a blank query as "show me something"; the UI used to
    return early and never call it."""
    app = read("app.js")
    block = app[app.index("async function doSearch"):]
    block = block[:block.index("\n}")]
    assert "if (!query) return" not in block


# ────────────────────────────────────────────────────────── browser pass


@pytest.fixture(scope="module")
def origin():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=os.path.dirname(APP))

    class Server(socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

        def handle_error(self, *args):
            pass

    httpd = Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        for candidate in (os.path.expanduser("~/.cache/ms-playwright"),
                          "/home/user/.cache/ms-playwright"):
            if os.path.isdir(candidate):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
                break
    with sync_playwright() as play:
        try:
            launched = play.chromium.launch()
        except Exception as exc:                       # pragma: no cover
            pytest.skip(f"chromium unavailable: {exc}")
        yield launched
        launched.close()


MANGA = {"ok": True, "info": {
    "title": "Solo Leveling", "url": "https://x/solo", "source": "asurascans",
    "source_name": "Asura Scans", "cover": "", "authors": ["Chugong"],
    "artists": ["h-goon"], "status": "Completed", "year": 2018,
    "series_type": "Manhwa", "demographic": "Shounen", "last_chapter": "179",
    "tags": ["Action", "Adventure", "Fantasy"],
    "description": "Gates began to appear. " * 40,
    "chapters": [{"name": f"Chapter {n}"} for n in range(1, 61)]}}

STUB = {
    "get_settings": {"ok": True, "settings": {"format": "cbz", "output_dir": "/dl"}},
    "get_sources": {"ok": True, "sources": [{"id": "mangadex", "name": "MangaDex"}]},
    "get_source_config": {"ok": True, "sources": []},
    "get_filters": {"ok": True, "filters": {}},
    "lock_status": {"ok": True, "enabled": False},
    "reader_library": {"ok": True, "count": 0, "books": []},
    "reader_recent": {"ok": True, "items": []},
    "get_queue": {"ok": True, "queue": []},
    "search": {"ok": True, "results": [
        {"title": "Solo Leveling", "url": "https://x/solo", "source": "asurascans",
         "source_name": "Asura Scans", "cover": ""}]},
    "get_manga": MANGA,
    "downloaded_status": {"ok": True, "chapters": ["Chapter 1", "Chapter 2"]},
    "is_watched": {"ok": True, "watched": False},
    "get_genres": {"ok": True, "genres": [
        {"name": "Action"}, {"name": "Fantasy"}, {"name": "Romance"}]},
    "get_bookmarks": {"ok": True, "items": [
        {"title": "Solo Leveling", "url": "https://x/solo", "source": "asurascans",
         "source_name": "Asura Scans", "cover": "", "folder": ""},
        {"title": "Berserk", "url": "https://x/b", "source": "mangakatana",
         "source_name": "Mangakatana", "cover": "", "folder": "f1"}]},
    "get_bookmark_folders": {"ok": True, "unfiled": 1, "folders": [
        {"id": "f1", "name": "Reading now", "count": 1}]},
}


@pytest.fixture()
def page(browser, origin):
    init = """
    window.__calls = [];
    window.pywebview = { api: new Proxy({}, { get: (_, name) => {
      if (name === 'then') return undefined;
      return async (...args) => {
        window.__calls.push([String(name), args]);
        return (%s)[String(name)] ?? { ok: true };
      };
    }})};
    """ % json.dumps(STUB)
    pg = browser.new_page(viewport={"width": 1400, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda exc: pg.errors.append(str(exc)))
    pg.on("console", lambda msg: pg.errors.append(msg.text)
          if msg.type == "error" else None)
    pg.add_init_script(init)
    pg.goto(origin + "/app/index.html", wait_until="load")
    pg.wait_for_function("window.__readerReady === true", timeout=20000)
    yield pg
    pg.close()


def open_detail(page):
    page.evaluate("window.__reader.openDetail('https://x/solo', 'asurascans')")
    page.wait_for_timeout(800)


def test_the_app_still_boots_clean(page):
    assert page.errors == []


def test_the_detail_page_shows_the_series(page):
    open_detail(page)
    assert page.text_content("#d-title") == "Solo Leveling"
    assert "Asura Scans" in page.text_content("#d-source")
    assert "Chugong" in page.text_content("#d-people")
    assert page.locator("#d-tags .chip").count() >= 3
    assert page.locator("#d-facts dt").count() >= 4
    assert len(page.text_content("#d-desc")) > 80


def test_the_detail_page_lists_the_chapters(page):
    open_detail(page)
    assert page.locator("#d-chapters .ch").count() == 60
    assert page.text_content("#d-count") == "60"
    assert "2 downloaded" in page.text_content("#d-have")


def test_downloaded_chapters_are_marked(page):
    open_detail(page)
    assert page.locator("#d-chapters .ch.have").count() == 2


def test_selecting_chapters_updates_the_button(page):
    open_detail(page)
    page.click('#detail [data-pick="all"]')
    page.wait_for_timeout(200)
    assert "60" in page.text_content("#d-download-label")
    page.click('#detail [data-pick="none"]')
    page.wait_for_timeout(200)
    assert "all chapters" in page.text_content("#d-download-label")


def test_a_quick_select_range_selects_that_many(page):
    open_detail(page)
    page.fill("#d-range", "1-20, 25, 30-40")
    page.click("#d-range-go")
    page.wait_for_timeout(300)
    assert "32" in page.text_content("#d-download-label")


def test_new_only_skips_what_is_downloaded(page):
    open_detail(page)
    page.click('#detail [data-pick="new"]')
    page.wait_for_timeout(200)
    assert "58" in page.text_content("#d-download-label")


def test_filtering_chapters_by_name(page):
    open_detail(page)
    page.fill("#d-find", "Chapter 5")
    page.wait_for_timeout(300)
    count = page.locator("#d-chapters .ch").count()
    assert 0 < count < 60, count


def test_hiding_downloaded_chapters(page):
    open_detail(page)
    page.check("#d-hide-have")
    page.wait_for_timeout(300)
    assert page.locator("#d-chapters .ch").count() == 58


def test_the_read_button_appears_when_something_is_downloaded(page):
    open_detail(page)
    assert not page.is_hidden("#d-read")


def test_the_bundle_field_only_shows_for_every_n(page):
    open_detail(page)
    assert page.is_hidden("#d-bundle-n-wrap")
    page.click('#d-bundle [data-bundle="n"]')
    page.wait_for_timeout(200)
    assert not page.is_hidden("#d-bundle-n-wrap")


def test_escape_closes_the_detail_page(page):
    open_detail(page)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.is_hidden("#detail")


def test_the_bookmarks_tab_lists_saved_series(page):
    page.evaluate("window.__reader.showView('marks')")
    page.wait_for_timeout(700)
    assert page.locator("#marks-grid .card").count() == 2
    assert page.locator("#marks-folders .row").count() == 1


def test_bookmarks_can_be_filtered_by_folder(page):
    page.evaluate("window.__reader.showView('marks')")
    page.wait_for_timeout(700)
    page.select_option("#marks-folder", "f1")
    page.wait_for_timeout(300)
    assert page.locator("#marks-grid .card").count() == 1


def test_bookmarks_can_be_filtered_by_name(page):
    page.evaluate("window.__reader.showView('marks')")
    page.wait_for_timeout(700)
    page.fill("#marks-filter", "berserk")
    page.wait_for_timeout(300)
    assert page.locator("#marks-grid .card").count() == 1


def test_genre_chips_toggle(page):
    page.evaluate("window.__reader.showView('search')")
    page.click("#search-more")
    page.wait_for_timeout(600)
    assert page.locator("#genre-chips .chip").count() == 3
    page.click('#genre-chips [data-genre="Fantasy"]')
    page.wait_for_timeout(150)
    assert page.locator("#genre-chips .chip.on").count() == 1
    assert "1 selected" in page.text_content("#genre-count")
    page.click("#genre-clear")
    page.wait_for_timeout(150)
    assert page.locator("#genre-chips .chip.on").count() == 0


def test_search_sends_a_dict_with_the_refinements(page):
    page.evaluate("window.__reader.showView('search')")
    page.click("#search-more")
    page.wait_for_timeout(500)
    page.click('#genre-chips [data-genre="Action"]')
    page.select_option("#srt-status", "Completed")
    page.fill("#search-input", "solo")
    page.click("#search-go")
    page.wait_for_timeout(600)
    sent = [args for name, args in page.evaluate("window.__calls")
            if name == "search"]
    assert sent, "search was never called"
    payload = sent[-1][1]
    assert isinstance(payload, dict), payload
    assert payload["status"] == "Completed"
    assert "Action" in payload["genres"]
