"""v3.2.4 — library covers, reader chrome, and two navigation bugs.

Reported, each reproduced first:

* clicking a cover in the library opened the *download* page rather than the
  reader;
* changing zoom moved you off the spot you were reading -- measured on page 6
  of 12 at 200%: scrollHeight fell 71216 -> 57216 while scrollTop stayed at
  35000, taking the position from 0.497 through the chapter to 0.620;
* MangaDex covers "not loading" -- server-side they return 200, and they load
  fine in the page. What did not load was the *library* cover, which is an
  absolute path on disk that no browser can fetch;
* no page list in the reader, no per-page bookmarks, no minimalist mode, and
  the book icon in the corner was a generic glyph rather than the folder's
  cover.
"""
import functools
import http.server
import json
import os
import socketserver
import struct
import sys
import threading
import zlib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP = os.path.join(ROOT, "mangasurf", "reader", "app")


def read(name):
    with open(os.path.join(APP, name), encoding="utf-8") as handle:
        return handle.read()


def png(w, h, rgb):
    def chunk(tag, data):
        payload = tag + data
        return (struct.pack(">I", len(data)) + payload
                + struct.pack(">I", zlib.crc32(payload) & 0xffffffff))
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# ─────────────────────────────────────────────────────────────── covers


@pytest.fixture()
def shelf(tmp_path, monkeypatch):
    """A real downloaded series, with a cover.jpg beside the chapter."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()

    series = tmp_path / "dl" / "Series"
    chapter = series / "Chapter 1"
    chapter.mkdir(parents=True)
    for i in range(1, 6):
        (chapter / f"{i:06d}.jpg").write_bytes(png(60, 90, (10 * i, 90, 200)))
    (series / "cover.jpg").write_bytes(png(60, 90, (220, 90, 140)))

    from mangasurf import library

    library.record_chapter("http://x/s", "Series", "Chapter 1", pages=5,
                           cover=str(series / "cover.jpg"),
                           directory=str(series), source="mangadex")

    from mangasurf.gui import Api

    api = Api()
    yield api, str(chapter), str(series)
    server = api._asset_server()
    if server:
        server.stop()
    from mangasurf.reader.api import ReaderApi
    ReaderApi._assets = None


def test_a_local_cover_is_served_over_http(shelf):
    """The library stores an absolute path; a page served over http cannot
    load that, so every downloaded series showed "No cover"."""
    api, _, _ = shelf
    book = api.reader_library()["books"][0]
    assert book["cover"].startswith("http://127.0.0.1:"), book["cover"]


def test_the_served_cover_really_returns_the_image(shelf):
    import urllib.request

    api, _, _ = shelf
    url = api.reader_library()["books"][0]["cover"]
    with urllib.request.urlopen(url, timeout=10) as response:
        assert response.status == 200
        assert response.read(4).startswith(b"\x89PNG")


def test_a_remote_cover_is_left_alone(shelf):
    """MangaDex URLs already work from the page; proxying them would be a
    pointless round trip."""
    api, _, _ = shelf
    remote = "https://uploads.mangadex.org/covers/abc/def.jpg.512.jpg"
    assert api.cover_src(remote) == remote


def test_a_data_uri_is_left_alone(shelf):
    api, _, _ = shelf
    uri = "data:image/png;base64,AAAA"
    assert api.cover_src(uri) == uri


def test_a_missing_cover_becomes_empty_not_a_broken_url(shelf):
    api, _, _ = shelf
    assert api.cover_src("/no/such/cover.jpg") == ""
    assert api.cover_src("") == ""
    assert api.cover_src(None) == ""


def test_the_folder_cover_is_found_for_the_reader_icon(shelf):
    """cover.jpg lives in the series folder, one level above the chapter."""
    api, chapter, _ = shelf
    assert api.folder_cover(chapter).startswith("http://127.0.0.1:")


def test_opening_a_chapter_carries_its_cover_and_page_names(shelf):
    api, chapter, _ = shelf
    opened = api.reader_open(chapter)
    assert opened["ok"] is True
    assert opened["cover"].startswith("http://127.0.0.1:")
    assert opened["names"] == [f"{i:06d}.jpg" for i in range(1, 6)]


def test_page_names_are_relative_to_the_chapter(shelf):
    """The sidebar shows "000001.jpg", not the whole absolute path."""
    api, chapter, _ = shelf
    for name in api.reader_open(chapter)["names"]:
        assert not os.path.isabs(name), name


def test_mangadex_cover_urls_follow_the_documented_shape():
    """uploads.mangadex.org/covers/{manga-id}/{fileName}[.size.jpg] -- getting
    this wrong is the classic "MangaDex covers are broken" report."""
    from mangasurf.sources.mangadex import MangaDexSource as MangaDex

    url = MangaDex.cover_url("manga-id", "file.jpg", "small")
    assert url.startswith("https://uploads.mangadex.org/covers/manga-id/file.jpg")
    assert url.endswith(".256.jpg")
    assert MangaDex.cover_url("m", "f.jpg", "original").endswith("f.jpg")


# ──────────────────────────────────────────────────── zoom keeps its place


def test_a_reflowing_attribute_anchors_the_position():
    """scrollTop is an absolute offset, so the same number lands elsewhere
    once the pages change height."""
    source = read("manga-view.js")
    assert "#captureAnchor" in source
    assert "#restoreAnchor" in source
    block = source[source.index("attributeChangedCallback"):]
    block = block[:block.index("#captureAnchor()")]
    for attribute in ("zoom", "max-width", "gap"):
        assert f"'{attribute}'" in block, attribute


def test_the_anchor_records_a_page_and_an_offset_into_it():
    source = read("manga-view.js")
    # the *definition*, not the call site inside attributeChangedCallback
    block = source[source.index("    #captureAnchor() {"):]
    block = block[:block.index("    #restoreAnchor")]
    assert "offsetTop" in block
    assert "offsetHeight" in block


def test_jumping_to_a_page_sets_the_offset_directly():
    """scrollIntoView lands short while a `.pending` placeholder is standing
    in for an unloaded image -- measured 32112 where offsetTop said 48000."""
    source = read("manga-view.js")
    block = source[source.index("    goTo(index) {"):]
    block = block[:block.index("\n    next(")]
    assert "scrollTop = el.offsetTop" in block
    # ignore the comments explaining why scrollIntoView was dropped
    code = "\n".join(line for line in block.splitlines()
                     if not line.strip().startswith("//"))
    assert "scrollIntoView" not in code
    # ...and the offset is re-read, because scrolling towards a distant page
    # loads the ones in between and pushes the destination down.
    assert "chase" in code
    assert "chase" in block, "must re-read the offset as pages load"


# ──────────────────────────────────────────────────── library card routing


def test_a_library_cover_opens_the_reader():
    """It used to carry data-manga, which is the series / download page."""
    source = read("app.js")
    block = source[source.index("function renderLibrary"):]
    block = block[:block.index("\n}")]
    assert 'data-open="${esc(first.path)}"' in block


def test_a_library_card_still_offers_the_series_page():
    source = read("app.js")
    block = source[source.index("function renderLibrary"):]
    block = block[:block.index("\n}")]
    assert "thumb-info" in block
    assert "data-manga=" in block


def test_the_inner_info_button_wins_over_the_card():
    """closest('[data-open]') walks up from the button to the card, so the
    more specific target has to be tested first."""
    source = read("app.js")
    block = source[source.index("// open anything with data-open"):]
    block = block[:block.index("const goto")]
    assert block.index("closest('[data-manga]')") < block.index("closest('[data-open]')")


# ───────────────────────────────────────────── reader chrome (markup)


def test_the_reader_has_a_pages_button_and_sidebar():
    html = read("index.html")
    assert 'id="r-pages"' in html
    assert 'id="r-pagelist"' in html
    assert 'id="pl-items"' in html
    assert 'id="pl-filter"' in html


def test_the_reader_has_a_book_icon():
    html = read("index.html")
    assert 'id="r-book"' in html


def test_the_reader_has_a_minimalist_toggle_and_hover_edges():
    html = read("index.html")
    assert 'id="r-zen"' in html
    assert 'class="zen-edge top"' in html
    assert 'class="zen-edge bottom"' in html


def test_page_bookmarks_are_hidden_until_hover():
    css = read("style.css")
    block = css[css.index(".pl-row .pmark {"):]
    block = block[:block.index("}")]
    assert "opacity: 0" in block
    assert ".pl-row:hover .pmark { opacity: 1; }" in css
    assert ".pl-row .pmark.on { opacity: 1;" in css, "a set bookmark must stay visible"


def test_minimalist_mode_hides_both_bars():
    css = read("style.css")
    assert "#reader.zen #r-top" in css
    assert "#reader.zen #r-bottom" in css
    assert "#reader.zen.peek-top #r-top" in css
    assert "#reader.zen.peek-bottom #r-bottom" in css


def test_the_hover_edges_are_inert_outside_minimalist_mode():
    """A permanently live strip across the top would eat ordinary clicks."""
    css = read("style.css")
    block = css[css.index(".zen-edge {"):]
    block = block[:block.index("}")]
    assert "pointer-events: none" in block
    assert "#reader.zen .zen-edge { pointer-events: auto; }" in css


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


PAGES = ["data:image/png;base64," + __import__("base64").b64encode(
    png(300, 900, (60 + i * 12, 120, 200 - i * 9))).decode() for i in range(1, 13)]

OPENED = {"ok": True, "kind": "pages", "title": "Chapter 1", "path": "/d/c1",
          "pages": PAGES, "names": [f"{i:06d}.jpg" for i in range(1, 13)],
          "count": 12, "cover": PAGES[0], "position": {}}

STUB = {
    "get_settings": {"ok": True, "settings": {}},
    "get_sources": {"ok": True, "sources": []},
    "get_source_config": {"ok": True, "sources": []},
    "get_filters": {"ok": True, "filters": {}},
    "lock_status": {"ok": True, "enabled": False},
    "reader_library": {"ok": True, "count": 1, "books": [{
        "title": "Series", "url": "http://x/s", "source": "mangadex",
        "cover": PAGES[0], "directory": "/d", "chapters": 1,
        "items": [{"kind": "folder", "path": "/d/c1", "label": "Chapter 1",
                   "pages": 12, "readable": True}]}]},
    "reader_recent": {"ok": True, "items": []},
    "get_queue": {"ok": True, "queue": []},
    "reader_open": OPENED,
    "reader_chapters": {"ok": True, "chapters": []},
    "reader_annotations": {"ok": True, "annotations": {"bookmarks": [], "notes": []}},
    "reader_add_bookmark": {"ok": True, "bookmark": {"id": "b1", "index": 3}},
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
    pg = browser.new_page(viewport={"width": 1300, "height": 860})
    pg.errors = []
    pg.on("pageerror", lambda exc: pg.errors.append(str(exc)))
    pg.on("console", lambda msg: pg.errors.append(msg.text)
          if msg.type == "error" else None)
    pg.add_init_script(init)
    pg.goto(origin + "/app/index.html", wait_until="load")
    pg.wait_for_function("window.__readerReady === true", timeout=20000)
    yield pg
    pg.close()


def enter_reader(page):
    page.click("#library-grid .card .thumb")
    page.wait_for_timeout(1600)


def test_clicking_a_library_cover_opens_the_reader(page):
    enter_reader(page)
    assert not page.is_hidden("#reader")
    assert page.is_hidden("#detail"), "it opened the download page instead"


def test_the_info_button_opens_the_series_page(page):
    page.click("#library-grid .thumb-info")
    page.wait_for_timeout(800)
    assert not page.is_hidden("#detail")
    assert page.is_hidden("#reader")


def test_the_pages_sidebar_lists_every_page(page):
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(500)
    assert not page.is_hidden("#r-pagelist")
    assert page.locator(".pl-row").count() == 12
    assert page.locator(".pl-row .pn").first.text_content() == "000001.jpg"


def test_the_sidebar_marks_the_current_position(page):
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(500)
    assert page.locator(".pl-current").count() == 1
    assert page.locator(".pl-row.on").count() == 1


def test_clicking_a_page_jumps_exactly_there(page):
    """The list re-renders whenever the reader relocates, so a plain click can
    land on a row that has just been replaced. Dispatch on the live node."""
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(500)
    page.evaluate("document.querySelector('.pl-row[data-page=\"7\"]').click()")
    page.wait_for_timeout(900)
    assert page.evaluate("document.getElementById('mv').index") == 7
    landed = page.evaluate("""() => {
        const mv = document.getElementById('mv');
        const sc = mv.shadowRoot.getElementById('scroller');
        const img = mv.shadowRoot.querySelectorAll('img.pg')[7];
        return Math.abs(sc.scrollTop - img.offsetTop);
    }""")
    assert landed < 2, f"landed {landed}px away from the page"


def test_the_page_filter_narrows_the_list(page):
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(500)
    page.fill("#pl-filter", "00001")
    page.wait_for_timeout(400)
    count = page.locator(".pl-row").count()
    assert 0 < count < 12, count


def test_a_page_can_be_bookmarked_from_the_list(page):
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(500)
    assert page.locator(".pmark.on").count() == 0
    page.evaluate("document.querySelector('.pl-row[data-page=\"3\"] .pmark').click()")
    page.wait_for_timeout(700)
    assert page.locator(".pmark.on").count() == 1


def test_the_book_icon_shows_the_folder_cover(page):
    enter_reader(page)
    assert page.evaluate(
        "document.getElementById('r-book').classList.contains('has-cover')")


def test_the_sidebar_header_shows_the_book(page):
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(500)
    assert page.text_content("#pl-title") == "Chapter 1"
    assert "12 pages" in page.text_content("#pl-sub")
    assert page.evaluate(
        "document.getElementById('pl-cover').classList.contains('has-cover')")


def test_minimalist_mode_hides_the_chrome(page):
    enter_reader(page)
    page.click("#r-zen")
    page.wait_for_timeout(500)
    assert page.evaluate(
        "getComputedStyle(document.getElementById('r-top')).opacity") == "0"
    assert page.evaluate(
        "getComputedStyle(document.getElementById('r-bottom')).opacity") == "0"


def test_hovering_an_edge_brings_the_toolbar_back(page):
    enter_reader(page)
    page.click("#r-zen")
    page.wait_for_timeout(400)
    page.mouse.move(650, 6)
    page.wait_for_timeout(400)
    assert page.evaluate(
        "getComputedStyle(document.getElementById('r-top')).opacity") == "1"
    page.mouse.move(650, 430)
    page.wait_for_timeout(400)
    assert page.evaluate(
        "getComputedStyle(document.getElementById('r-top')).opacity") == "0"


def test_minimalist_mode_closes_the_drawers(page):
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(300)
    page.click("#r-zen")
    page.wait_for_timeout(400)
    assert page.is_hidden("#r-pagelist")


def test_zoom_keeps_the_reading_position(page):
    """Measured before the fix: page 6 of 12 at zoom 200% went from 0.497
    through the chapter to 0.620 because scrollTop stayed put."""
    enter_reader(page)
    # Scroll there by hand rather than with goTo(): goTo re-reads the offset
    # as pages load, which would compensate for a missing anchor and hide the
    # very thing this checks.
    page.evaluate("""() => {
        const mv = document.getElementById('mv');
        const sc = mv.shadowRoot.getElementById('scroller');
        const img = mv.shadowRoot.querySelectorAll('img.pg')[5];
        if (img.dataset.src && !img.src) img.src = img.dataset.src;
        sc.scrollTop = img.offsetTop;
    }""")
    page.wait_for_timeout(900)
    page.evaluate("""() => {
        const mv = document.getElementById('mv');
        const sc = mv.shadowRoot.getElementById('scroller');
        sc.scrollTop = mv.shadowRoot.querySelectorAll('img.pg')[5].offsetTop;
    }""")
    # Distant pages stay lazily unloaded by design, so waiting for *none*
    # pending never finishes. Wait for the strip height to stop moving, which
    # is what actually makes the baseline fair.
    page.wait_for_function(
        """() => {
            const sc = document.getElementById('mv').shadowRoot
                .getElementById('scroller');
            const now = sc.scrollHeight;
            const steady = window.__lastH === now;
            window.__lastH = now;
            return steady;
        }""",
        timeout=15000, polling=400)
    page.wait_for_timeout(400)
    # The invariant is "still looking at the same page", not "same fraction".
    # Pages that have not loaded yet keep a fixed 80vh placeholder that does
    # not scale with zoom, so the *proportion* of the strip legitimately moves
    # while the position does not -- measured scrollTop tracking page 6 exactly
    # from 19500 to 39000 while fraction went 0.7312 -> 0.7789.
    before = page.evaluate("""() => {
        const mv = document.getElementById('mv');
        const sc = mv.shadowRoot.getElementById('scroller');
        const img = mv.shadowRoot.querySelectorAll('img.pg')[5];
        return { index: mv.index, offset: sc.scrollTop - img.offsetTop };
    }""")
    page.evaluate("""() => {
        const el = document.getElementById('r-zoom');
        el.value = '200';
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    page.wait_for_timeout(1000)
    after = page.evaluate("""() => {
        const mv = document.getElementById('mv');
        const sc = mv.shadowRoot.getElementById('scroller');
        const img = mv.shadowRoot.querySelectorAll('img.pg')[5];
        return { index: mv.index, offset: sc.scrollTop - img.offsetTop };
    }""")
    assert after["index"] == before["index"] == 5, (before, after)
    assert abs(after["offset"]) < 30, (before, after)


def test_the_reader_logs_no_errors(page):
    enter_reader(page)
    page.click("#r-pages")
    page.wait_for_timeout(300)
    page.click("#r-zen")
    page.wait_for_timeout(300)
    page.evaluate("window.__reader.setZen(false)")
    page.wait_for_timeout(300)
    assert page.errors == []
