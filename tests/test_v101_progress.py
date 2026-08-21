"""ReaderM 1.0.1 — the reader's progress bar.

Reported: "progressbar in reader not accurate and when scrolling first really
fast forward then gets stuck in middle, fix percentages".

Root cause, measured before the fix: `fraction` was
``scrollTop / (scrollHeight - clientHeight)``. In a lazy-loaded strip
scrollHeight *grows* all through the chapter -- an 80vh placeholder becomes a
1200px image and adds height below you -- so the same physical position
reported a different number a moment later.

On a 40-page strip, parked at scrollTop 4000 and not touched, the fraction
fell from 0.1411 to 0.1376 on its own: the bar slid backwards. Scrolling to
the bottom reported 89%.

The fix counts pages instead of pixels. The page count is known when the
chapter opens and never changes, so only the position *within* the current
page depends on geometry.

These tests drive the real custom element in Chromium. Asserting on source
text would not have caught any of it.
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

READER = os.path.join(ROOT, "mangasurf", "reader")

PAGE_COUNT = 40


def png(width, height, shade):
    def chunk(tag, data):
        payload = tag + data
        return (struct.pack(">I", len(data)) + payload
                + struct.pack(">I", zlib.crc32(payload) & 0xffffffff))
    raw = b"".join(b"\x00" + bytes((shade, shade, shade)) * width
                   for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


#: Deliberately taller than the .pending placeholder, which is the shape that
#: makes the strip grow as it loads -- exactly what broke the old maths.
IMAGE = png(800, 1200, 90)

#: A last page shorter than the viewport -- a credits page or an end card.
#: It cannot fill the screen, so the "how far into this page" term can never
#: reach 1 and the chapter would finish below 100% without the bottom snap.
SHORT_IMAGE = png(800, 120, 150)

HTML = """<!doctype html><html data-theme="midnight"><head>
<link rel="stylesheet" href="/app/theme.css">
<link rel="stylesheet" href="/app/style.css">
<script type="module" src="/app/manga-view.js"></script>
<style>html,body{margin:0;height:100%%} manga-view{height:100vh;display:block}</style>
</head><body>
<manga-view id="mv" mode="webtoon" fit="contain"></manga-view>
<script type="module">
  const mv = document.getElementById('mv');
  await customElements.whenDefined('manga-view');
  await mv.open({ pages: %s });
  window.__ready = true;
</script>
</body></html>"""


@pytest.fixture(scope="module")
def origin():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=READER, **kw)

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/img/"):
                blob = SHORT_IMAGE if "short" in self.path else IMAGE
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                return
            if self.path in ("/book", "/book-short-ending"):
                names = [f"/img/{i}.png" for i in range(PAGE_COUNT)]
                if self.path.endswith("short-ending"):
                    names = names[:10] + ["/img/short.png"]
                pages = json.dumps(names)
                body = (HTML % pages).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    class Server(socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

        def handle_error(self, *a):
            pass

    httpd = Server(("127.0.0.1", 0), Handler)
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


SETTLE = """() => {
    const mv = document.getElementById('mv');
    const el = mv.shadowRoot.getElementById('scroller');
    el.scrollTop = el.scrollHeight;
}"""


@pytest.fixture()
def view(browser, origin):
    page = browser.new_page(viewport={"width": 900, "height": 800})
    page.errors = []
    page.on("pageerror", lambda exc: page.errors.append(str(exc)))
    page.goto(origin + "/book", wait_until="load")
    page.wait_for_function("window.__ready === true", timeout=25000)
    # Force every image to load so the geometry is final, then return to the
    # top. Without this the strip keeps growing and no measurement is stable.
    for _ in range(4):
        page.evaluate(SETTLE)
        page.wait_for_timeout(400)
    page.evaluate("document.getElementById('mv').shadowRoot"
                  ".getElementById('scroller').scrollTop = 0")
    page.wait_for_timeout(300)
    yield page
    page.close()


def scroll_to(page, top):
    page.evaluate("t => document.getElementById('mv').shadowRoot"
                  ".getElementById('scroller').scrollTop = t", top)
    page.wait_for_timeout(150)


def read(page):
    return page.evaluate("""() => {
        const mv = document.getElementById('mv');
        const el = mv.shadowRoot.getElementById('scroller');
        return { fraction: mv.fraction, index: mv.index, total: mv.length,
                 top: el.scrollTop, height: el.scrollHeight,
                 client: el.clientHeight };
    }""")


def test_the_bottom_of_the_book_is_one_hundred_percent(view):
    """It reported 89%. A chapter you have finished must say so."""
    for _ in range(4):
        view.evaluate(SETTLE)
        view.wait_for_timeout(300)
    got = read(view)
    assert got["fraction"] == pytest.approx(1.0, abs=0.001), got
    assert round(got["fraction"] * 100) == 100
    assert got["index"] == got["total"] - 1


def test_the_progress_does_not_drift_while_standing_still(view):
    """The bug in one line: park, touch nothing, watch the number move."""
    scroll_to(view, 12000)
    readings = []
    for _ in range(4):
        view.wait_for_timeout(350)
        readings.append(view.evaluate("document.getElementById('mv').fraction"))
    assert max(readings) - min(readings) < 0.002, readings


def test_progress_only_ever_increases_as_you_scroll_forward(view):
    """A bar that slides backwards is the visible symptom."""
    seen = []
    for top in range(0, 30000, 2500):
        scroll_to(view, top)
        seen.append(round(view.evaluate("document.getElementById('mv').fraction"), 4))
    assert seen == sorted(seen), seen


@pytest.mark.parametrize("asked", [0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0])
def test_a_saved_position_comes_back_to_the_same_place(view, asked):
    """Position is stored as a fraction and restored through setFraction, so
    the two must be inverses. Before the fix they used different units and
    0.50 came back as 0.456."""
    view.evaluate("f => document.getElementById('mv').setFraction(f)", asked)
    view.wait_for_timeout(900)          # let the settle pass finish
    got = view.evaluate("document.getElementById('mv').fraction")
    assert got == pytest.approx(asked, abs=0.03), f"asked {asked}, got {got}"


def test_the_reported_page_matches_what_is_on_screen(view):
    """index must name a page the viewport is actually showing."""
    scroll_to(view, 18000)
    view.wait_for_timeout(200)
    got = view.evaluate("""() => {
        const mv = document.getElementById('mv');
        const el = mv.shadowRoot.getElementById('scroller');
        const img = mv.shadowRoot.querySelector(`img[data-index="${mv.index}"]`);
        return { index: mv.index, top: el.scrollTop,
                 bottom: el.scrollTop + el.clientHeight,
                 pageTop: img.offsetTop,
                 pageBottom: img.offsetTop + img.offsetHeight };
    }""")
    assert got["pageTop"] <= got["bottom"], got
    assert got["pageBottom"] >= got["top"], got


def test_percentages_are_whole_and_bounded(view):
    for top in (0, 5000, 15000, 30000, 10 ** 6):
        scroll_to(view, top)
        percent = view.evaluate(
            "Math.round(document.getElementById('mv').fraction * 100)")
        assert 0 <= percent <= 100, (top, percent)


def test_a_fast_flick_does_not_strand_the_reader(view):
    """Reported as "gets stuck in middle". Several big jumps in quick
    succession, then the position must match the pixels."""
    for _ in range(6):
        view.evaluate("""() => {
            const el = document.getElementById('mv').shadowRoot
                .getElementById('scroller');
            el.scrollTop += 6000;
        }""")
        view.wait_for_timeout(50)
    view.wait_for_timeout(700)
    got = read(view)
    # The reported page must be the one filling most of the screen.
    #
    # An earlier version of this test used the viewport's bottom edge and
    # failed by one: at scrollTop 36000 with an 800px viewport, page 26 covers
    # 450px of the screen and page 27 covers 350px, so the bottom-edge rule
    # names the page you can barely see. The element uses the midpoint, which
    # is right; the test was wrong.
    expected = view.evaluate("""() => {
        const mv = document.getElementById('mv');
        const el = mv.shadowRoot.getElementById('scroller');
        const top = el.scrollTop, bottom = top + el.clientHeight;
        let best = 0, most = -1;
        for (const img of mv.shadowRoot.querySelectorAll('img.pg')) {
            const a = img.offsetTop, b = a + img.offsetHeight;
            const visible = Math.max(0, Math.min(b, bottom) - Math.max(a, top));
            if (visible > most) { most = visible; best = Number(img.dataset.index); }
        }
        return best;
    }""")
    assert got["index"] == expected, got
    assert got["fraction"] > 0.3, got      # it did move a long way


def test_a_chapter_ending_on_a_short_page_still_reaches_one_hundred(browser, origin):
    """A credits page shorter than the viewport cannot fill the screen, so the
    "how far into this page" term never reaches 1 and the arithmetic alone
    ends the chapter below 100%. Measured: a 135px last page in an 800px
    viewport. The bottom snap is what makes this correct, and without this
    test that snap was unverified -- a mutation removing it passed.
    """
    page = browser.new_page(viewport={"width": 900, "height": 800})
    try:
        page.goto(origin + "/book-short-ending", wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=25000)
        for _ in range(6):
            page.evaluate(SETTLE)
            page.wait_for_timeout(300)
        got = page.evaluate("""() => {
            const mv = document.getElementById('mv');
            const el = mv.shadowRoot.getElementById('scroller');
            const imgs = [...mv.shadowRoot.querySelectorAll('img.pg')];
            const last = imgs[imgs.length - 1];
            return { fraction: mv.fraction, index: mv.index, total: mv.length,
                     lastHeight: last.offsetHeight, client: el.clientHeight };
        }""")
        assert got["lastHeight"] < got["client"], got     # the premise holds
        assert round(got["fraction"] * 100) == 100, got
        assert got["index"] == got["total"] - 1, got
    finally:
        page.close()


# Measured redundancy, recorded so the next reader does not "simplify" it:
# there are two bottom snaps, one in `fraction` and one in `#emitRelocate`.
# Removing EITHER alone leaves this suite green, because the page-based
# arithmetic reaches 1.0 on its own for ordinary pages and the other snap
# still covers the short-last-page case. Removing BOTH fails
# test_a_chapter_ending_on_a_short_page_still_reaches_one_hundred. They are
# kept as a pair because they answer different questions -- "how far through"
# and "which page am I on" -- and those two disagreeing is exactly the bug
# reported ("fix percentages"): 100% on screen next to a counter reading
# "10 / 11".


def test_no_script_errors_along_the_way(view):
    scroll_to(view, 9000)
    view.evaluate("document.getElementById('mv').setFraction(0.6)")
    view.wait_for_timeout(500)
    assert view.errors == []
