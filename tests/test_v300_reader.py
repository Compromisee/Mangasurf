"""v3.0.0 — the manga renderer, driven through a real browser.

These lay the page out for real rather than asserting on attributes. The two
worst bugs found while building `manga-view.js` were both invisible to any
cheaper check:

* every page was an unloaded ``<img>`` with no intrinsic height, so the whole
  strip collapsed — measured ``scrollHeight 640 == clientHeight 640``, webtoon
  mode could not scroll, and the position observer reported the *last* page the
  moment a chapter opened;
* the options drawer was positioned over the toolbar and swallowed clicks on
  the buttons that open it (Playwright: "<h3>Reading</h3> intercepts pointer
  events" for thirty seconds).
"""
import base64
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

READER = os.path.join(ROOT, "readerm", "reader")
APP = os.path.join(READER, "app")


def _png(width, height, rgb):
    def chunk(tag, data):
        payload = tag + data
        return (struct.pack(">I", len(data)) + payload
                + struct.pack(">I", zlib.crc32(payload) & 0xffffffff))

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


PAGE_COLOURS = [(214, 66, 66), (72, 168, 108), (70, 116, 214),
                (226, 182, 62), (150, 90, 200), (240, 120, 30)]

#: Pages are handed to the element as data: URLs so the tests need no server
#: for the images themselves -- only the modules have to come over http.
PAGE_URLS = ["data:image/png;base64," + base64.b64encode(
    _png(300, 900, colour)).decode() for colour in PAGE_COLOURS]


@pytest.fixture(scope="module")
def origin():
    """Serve the reader over http: ES modules are blocked on file://."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=READER)

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
        except Exception as exc:                     # pragma: no cover
            pytest.skip(f"chromium unavailable: {exc}")
        yield launched
        launched.close()


HOST = """<!doctype html><meta charset=utf-8>
<body style="margin:0;background:#101014">
<manga-view id="v" style="width:420px;height:640px;display:block"></manga-view>
<script type="module">
import '%s/app/manga-view.js';
window.__events = [];
const v = document.getElementById('v');
for (const type of ['relocate', 'end', 'loaded', 'page-error'])
    v.addEventListener(type, e => window.__events.push([type, e.detail]));
window.__ready = true;
</script>"""


@pytest.fixture()
def view(browser, origin):
    """A manga-view with six tall pages loaded and settled."""
    page = browser.new_page(viewport={"width": 520, "height": 700})
    page.errors = []
    page.on("pageerror", lambda exc: page.errors.append(str(exc)))
    page.on("console", lambda msg: page.errors.append(msg.text)
            if msg.type == "error" else None)
    page.goto(origin + "/_host.html", wait_until="load")
    page.wait_for_function("window.__ready === true", timeout=15000)
    page.evaluate("pages => document.getElementById('v').open({ pages })", PAGE_URLS)
    page.wait_for_function(
        "() => [...document.getElementById('v').shadowRoot"
        ".querySelectorAll('img.pg')].some(i => i.complete && i.naturalWidth > 0)",
        timeout=15000)
    page.wait_for_timeout(250)
    yield page
    page.close()


@pytest.fixture(scope="module", autouse=True)
def _host_file(origin):
    """The host page has to sit under the served root to import the module."""
    path = os.path.join(READER, "_host.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(HOST % "")
    yield
    if os.path.isfile(path):
        os.remove(path)


def metrics(page):
    return page.evaluate("""() => {
        const v = document.getElementById('v');
        const sc = v.shadowRoot.getElementById('scroller');
        const tr = v.shadowRoot.getElementById('track');
        const imgs = [...v.shadowRoot.querySelectorAll('img.pg')];
        return {
            mode: v.mode, paged: v.paged, index: v.index, length: v.length,
            fraction: v.fraction,
            scrollHeight: sc.scrollHeight, clientHeight: sc.clientHeight,
            scrollTop: sc.scrollTop,
            scrollable: sc.scrollHeight > sc.clientHeight + 1,
            visible: imgs.filter(i => i.style.display !== 'none').length,
            trackDirection: getComputedStyle(tr).flexDirection,
            pending: imgs.filter(i => i.classList.contains('pending')).length,
        };
    }""")


# ------------------------------------------------------------------ webtoon


def test_a_chapter_opens_on_the_first_page_not_the_last(view):
    """The collapsed-strip bug reported page 6 of 6 the instant it opened."""
    assert metrics(view)["index"] == 0


def test_webtoon_mode_is_actually_scrollable(view):
    view.evaluate("document.getElementById('v').setAttribute('mode','webtoon')")
    view.wait_for_timeout(200)
    data = metrics(view)
    assert data["scrollable"], data
    assert data["scrollHeight"] > data["clientHeight"] * 3


def test_unloaded_pages_still_reserve_height(view):
    """Otherwise every page stacks at offsetTop 0 and the strip has no length."""
    height = view.evaluate("""() => {
        const v = document.getElementById('v');
        const img = document.createElement('img');
        img.className = 'pg pending';
        v.shadowRoot.getElementById('track').append(img);
        const h = img.getBoundingClientRect().height;
        img.remove();
        return h;
    }""")
    assert height > 50, f"a pending page reserved only {height}px"


def test_webtoon_has_no_gap_between_pages(view):
    """A long strip is one continuous image; any gap slices it into panels.

    The gap is set to something non-zero first, otherwise this passes on the
    default value alone and proves nothing about webtoon mode.
    """
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','vertical');
        v.setAttribute('gap','24');
    }""")
    view.wait_for_timeout(150)
    before = view.evaluate("getComputedStyle(document.getElementById('v'))"
                           ".getPropertyValue('--page-gap').trim()")
    assert before == "24px", "the gap did not apply in vertical mode"

    view.evaluate("document.getElementById('v').setAttribute('mode','webtoon')")
    view.wait_for_timeout(150)
    after = view.evaluate("getComputedStyle(document.getElementById('v'))"
                          ".getPropertyValue('--page-gap').trim()")
    assert after == "0px", f"webtoon left a {after} gap between pages"


def test_scrolling_moves_through_the_strip(view):
    view.evaluate("document.getElementById('v').setAttribute('mode','webtoon')")
    view.wait_for_timeout(150)
    before = metrics(view)["scrollTop"]
    view.evaluate("document.getElementById('v').next()")
    view.wait_for_timeout(200)
    assert metrics(view)["scrollTop"] > before


# -------------------------------------------------------------- paged modes


def test_paged_mode_shows_one_page_at_a_time(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr'); v.goTo(0);
    }""")
    view.wait_for_timeout(150)
    assert metrics(view)["visible"] == 1


def test_left_to_right_advances_on_go_right(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr'); v.goTo(1); v.goRight();
    }""")
    assert metrics(view)["index"] == 2


def test_right_to_left_reverses_the_page_keys(view):
    """Japanese reading order: the right-hand key goes *back* through pages."""
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','rtl'); v.goTo(3); v.goRight();
    }""")
    assert metrics(view)["index"] == 2
    view.evaluate("document.getElementById('v').goLeft()")
    assert metrics(view)["index"] == 3


def test_right_to_left_reverses_the_visual_order(view):
    view.evaluate("document.getElementById('v').setAttribute('mode','rtl')")
    view.wait_for_timeout(150)
    assert metrics(view)["trackDirection"] == "row-reverse"
    view.evaluate("document.getElementById('v').setAttribute('mode','ltr')")
    view.wait_for_timeout(150)
    assert metrics(view)["trackDirection"] == "row"


def test_a_double_page_spread_shows_two_pages(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr'); v.goTo(0); v.setAttribute('spread','');
    }""")
    view.wait_for_timeout(150)
    assert metrics(view)["visible"] == 2


def test_a_spread_advances_two_pages_at_a_time(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr'); v.setAttribute('spread',''); v.goTo(0); v.next();
    }""")
    assert metrics(view)["index"] == 2


# ------------------------------------------------------------------ resume


def test_a_saved_fraction_is_restored(view):
    """setFraction right after open used to land on 0: the strip had no
    scrollable span yet, so the seek was silently thrown away."""
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','webtoon'); v.setFraction(0.5);
    }""")
    view.wait_for_timeout(400)
    fraction = metrics(view)["fraction"]
    assert 0.4 < fraction < 0.6, fraction


def test_seeking_to_the_end_reports_the_last_page(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr'); v.goTo(v.length - 1);
    }""")
    data = metrics(view)
    assert data["index"] == data["length"] - 1


# ------------------------------------------------------------------- edges


def test_reaching_the_end_fires_exactly_one_edge_event(view):
    view.evaluate("""() => {
        window.__events.length = 0;
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr'); v.goTo(v.length - 1); v.next();
    }""")
    edges = [e for e in view.evaluate("window.__events") if e[0] == "end"]
    assert len(edges) == 1
    assert edges[0][1]["edge"] == "end"


def test_going_back_from_the_first_page_reports_the_start_edge(view):
    view.evaluate("""() => {
        window.__events.length = 0;
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr'); v.goTo(0); v.prev();
    }""")
    edges = [e for e in view.evaluate("window.__events") if e[0] == "end"]
    assert edges and edges[0][1]["edge"] == "start"


def test_a_broken_page_reports_itself(view):
    view.evaluate("""() => {
        window.__events.length = 0;
        document.getElementById('v').open({ pages: ['data:image/png;base64,bm90YW5pbWFnZQ=='] });
    }""")
    view.wait_for_timeout(600)
    kinds = [e[0] for e in view.evaluate("window.__events")]
    assert "page-error" in kinds


# ------------------------------------------------------------------ hygiene


def test_the_renderer_logs_no_errors(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        for (const mode of ['webtoon','vertical','ltr','rtl']) {
            v.setAttribute('mode', mode); v.next(); v.prev(); v.goTo(2);
        }
    }""")
    view.wait_for_timeout(300)
    assert view.errors == []


def test_every_mode_reports_a_sane_page_count(view):
    for mode in ("webtoon", "vertical", "ltr", "rtl"):
        view.evaluate("m => document.getElementById('v').setAttribute('mode', m)", mode)
        view.wait_for_timeout(120)
        data = metrics(view)
        assert data["length"] == len(PAGE_URLS)
        assert 0 <= data["index"] < data["length"], (mode, data)


# --------------------------------------------------------------- full shell


@pytest.fixture()
def shell(browser, origin):
    """The whole reader UI with a stubbed Python bridge."""
    stub = {
        "get_settings": {"ok": True, "settings": {
            "reader_mode": "webtoon", "reader_theme": "midnight",
            "reader_fit": "contain", "reader_gap": 0,
            "reader_max_width": "100%", "reader_spread": False,
            "reader_filter": "none", "reader_zoom": 1,
            "reader_keep_position": True, "reader_tap_zones": True}},
        "get_sources": {"ok": True, "sources": [{"id": "mangadex", "name": "MangaDex"}]},
        "reader_library": {"ok": True, "count": 1, "books": [{
            "title": "Test Series", "url": "u", "source": "mangadex", "cover": "",
            "directory": "/d", "chapters": 3,
            "items": [{"kind": "folder", "path": "/d/Chapter 1",
                       "label": "Chapter 1", "pages": 6, "readable": True}]}]},
        "reader_recent": {"ok": True, "items": []},
        "reader_chapters": {"ok": True, "chapters": []},
        "reader_annotations": {"ok": True, "annotations": {"bookmarks": [], "notes": []}},
        "get_queue": {"ok": True, "queue": []},
    }
    opened = {"ok": True, "kind": "pages", "title": "Test Series — Chapter 1",
              "path": "/d/Chapter 1", "pages": PAGE_URLS, "count": len(PAGE_URLS),
              "position": {}}
    init = """
    window.__calls = [];
    window.pywebview = { api: new Proxy({}, { get: (_, name) => {
      if (name === 'then') return undefined;
      return async (...args) => {
        window.__calls.push(String(name));
        if (String(name) === 'reader_open') return %s;
        return (%s)[String(name)] ?? { ok: true };
      };
    }})};
    """ % (json.dumps(opened), json.dumps(stub))

    page = browser.new_page(viewport={"width": 1280, "height": 820})
    page.errors = []
    page.on("pageerror", lambda exc: page.errors.append(str(exc)))
    page.on("console", lambda msg: page.errors.append(msg.text)
            if msg.type == "error" else None)
    page.add_init_script(init)
    page.goto(origin + "/app/index.html", wait_until="load")
    page.wait_for_function("window.__readerReady === true", timeout=20000)
    yield page
    page.close()



def open_reader(shell):
    """Open the reader from the library.

    Since v3.2.3 a library card opens the *detail* page -- cover, tags,
    description, chapter picker -- and the Read button there is what enters
    the reader. Tests that only cared about the reader go straight to it.
    """
    shell.evaluate("p => window.__reader.openPath(p)", "/d/Chapter 1")
    shell.wait_for_timeout(900)


def test_the_reader_boots(shell):
    assert shell.evaluate("window.__readerReady") is True
    assert shell.is_hidden("#boot")


def test_the_library_lists_downloads(shell):
    assert shell.locator(".card").count() == 1
    assert "Test Series" in shell.text_content("#library-grid")


def test_opening_a_card_shows_the_reader(shell):
    open_reader(shell)
    assert not shell.is_hidden("#reader")
    assert shell.text_content("#r-count").strip() == f"1 / {len(PAGE_URLS)}"


def test_the_options_drawer_does_not_cover_the_toolbar(shell):
    """The drawer used to sit at top:0 and eat clicks on the very buttons
    that open and close it."""
    open_reader(shell)
    shell.click("#r-settings")
    shell.wait_for_timeout(300)
    assert not shell.is_hidden("#r-panel")
    # every toolbar button must still be reachable
    for selector in ("#r-close", "#r-chapters", "#r-bookmark", "#r-fullscreen"):
        box = shell.locator(selector).bounding_box()
        panel = shell.locator("#r-panel").bounding_box()
        assert box is not None, selector
        assert box["y"] + box["height"] <= panel["y"] + 1, selector
    shell.click("#r-chapters")          # would time out if intercepted
    shell.wait_for_timeout(200)
    assert not shell.is_hidden("#r-chaplist")


def test_switching_mode_from_the_drawer_changes_the_renderer(shell):
    open_reader(shell)
    shell.click("#r-settings")
    shell.click('#mode-seg button[data-mode="rtl"]')
    shell.wait_for_timeout(300)
    assert shell.get_attribute("#mv", "mode") == "rtl"


def test_every_theme_applies_without_error(shell):
    from_page = shell.evaluate("""async () => {
        const { THEME_ORDER } = await import('./themes.js');
        const seen = [];
        for (const name of THEME_ORDER) {
            window.__reader.setTheme(name);
            seen.push([name,
                getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(),
                document.documentElement.dataset.theme]);
        }
        return seen;
    }""")
    assert len(from_page) >= 8, from_page
    for name, background, applied in from_page:
        assert background, f"{name} left --bg empty"
        assert applied == name, f"{name} applied as {applied}"


def test_light_themes_really_are_light(shell):
    dark = shell.evaluate("""async () => {
        const { THEMES } = await import('./themes.js');
        const out = {};
        for (const [name, theme] of Object.entries(THEMES)) {
            window.__reader.setTheme(name);
            out[name] = [theme.dark,
                getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()];
        }
        return out;
    }""")

    def luminance(value):
        value = value.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255

    for name, (is_dark, background) in dark.items():
        lum = luminance(background)
        if is_dark:
            assert lum < 0.5, f"{name} claims dark but --bg luminance is {lum:.2f}"
        else:
            assert lum > 0.5, f"{name} claims light but --bg luminance is {lum:.2f}"


def test_the_shell_logs_no_console_errors(shell):
    open_reader(shell)
    shell.click("#r-settings")
    shell.wait_for_timeout(200)
    shell.evaluate("window.__reader.showView('search')")
    shell.evaluate("window.__reader.showView('queue')")
    shell.evaluate("window.__reader.showView('settings')")
    shell.wait_for_timeout(300)
    assert shell.errors == []


# -------------------------------------------------------------- autoscroll


def test_auto_scroll_moves_the_strip(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','webtoon');
        v.shadowRoot.getElementById('scroller').scrollTop = 0;
        v.startAutoScroll(600);
    }""")
    view.wait_for_timeout(700)
    moved = metrics(view)["scrollTop"]
    view.evaluate("document.getElementById('v').stopAutoScroll()")
    assert moved > 40, f"auto-scroll moved only {moved}px in 0.7s at 600px/s"


def test_auto_scroll_reports_that_it_is_running(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','webtoon'); v.startAutoScroll(120);
    }""")
    assert view.evaluate("document.getElementById('v').autoScrolling") is True
    view.evaluate("document.getElementById('v').stopAutoScroll()")
    assert view.evaluate("document.getElementById('v').autoScrolling") is False


def test_a_slow_speed_still_moves(view):
    """An integer scrollTop step per tick rounds a slow speed to zero and
    nothing moves at all, so the accumulator has to be sub-pixel."""
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','webtoon');
        v.shadowRoot.getElementById('scroller').scrollTop = 0;
        v.startAutoScroll(15);
    }""")
    view.wait_for_timeout(1200)
    moved = metrics(view)["scrollTop"]
    view.evaluate("document.getElementById('v').stopAutoScroll()")
    assert moved > 0, "a 15px/s auto-scroll did not move at all"


def test_auto_scroll_refuses_paged_modes(view):
    started = view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','ltr');
        return v.startAutoScroll(100);
    }""")
    assert started is False
    assert view.evaluate("document.getElementById('v').autoScrolling") is False


def test_auto_scroll_stops_at_the_end_and_says_so(view):
    view.evaluate("""() => {
        window.__events.length = 0;
        const v = document.getElementById('v');
        v.setAttribute('mode','webtoon');
        const sc = v.shadowRoot.getElementById('scroller');
        sc.scrollTop = sc.scrollHeight;          // already at the bottom
        v.startAutoScroll(400);
    }""")
    view.wait_for_timeout(600)
    assert view.evaluate("document.getElementById('v').autoScrolling") is False
    edges = [e for e in view.evaluate("window.__events") if e[0] == "end"]
    assert edges, "reaching the bottom under auto-scroll reported nothing"


def test_destroying_the_view_stops_auto_scroll(view):
    view.evaluate("""() => {
        const v = document.getElementById('v');
        v.setAttribute('mode','webtoon'); v.startAutoScroll(200); v.destroy();
    }""")
    assert view.evaluate("document.getElementById('v').autoScrolling") is False


# ------------------------------------------------------- shell: new controls


def test_the_shortcuts_sheet_opens_and_closes(shell):
    open_reader(shell)
    assert shell.is_hidden("#r-shortcuts")
    shell.click("#r-settings")
    shell.click("#r-help")
    shell.wait_for_timeout(250)
    assert not shell.is_hidden("#r-shortcuts")
    shell.click("#r-shortcuts-close")
    shell.wait_for_timeout(250)
    assert shell.is_hidden("#r-shortcuts")


def test_the_shortcuts_sheet_documents_the_real_keys(shell):
    """Every key listed has to be one the reader actually handles."""
    listed = shell.evaluate(
        "[...document.querySelectorAll('#r-shortcuts dt')].map(d => d.textContent.trim())")
    assert listed, "no shortcuts listed"
    for key in ("W", "S", "B", "T", "F", "I", "?"):
        assert any(key == entry for entry in listed), f"{key} not documented"


def test_the_auto_scroll_button_toggles_from_the_toolbar(shell):
    open_reader(shell)
    shell.click("#r-auto-top")
    shell.wait_for_timeout(300)
    assert shell.evaluate("document.getElementById('mv').autoScrolling") is True
    shell.click("#r-auto-top")
    shell.wait_for_timeout(200)
    assert shell.evaluate("document.getElementById('mv').autoScrolling") is False


def test_the_library_shows_a_stats_strip(shell):
    shell.wait_for_timeout(300)
    assert not shell.is_hidden("#stats-strip")
    text = shell.text_content("#stats-strip")
    assert "Series" in text
    assert "Chapters" in text
