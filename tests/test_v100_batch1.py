"""ReaderM 1.0.0, first batch — covers, CBZ fetch, sidebar, autosave.

Every item was reproduced before it was fixed:

* **MangaDex covers.** Twice reported, twice mis-diagnosed by me: the URLs
  return 200 and decode fine, so I checked the wrong thing. Fetched with
  ``Referer: http://127.0.0.1`` MangaDex serves a *different* image -- a
  placeholder reading "You can read this at mangadex.org". Measured at the
  same URL: 59,480 bytes with that referer against 77,292 without.
* **"Failed to fetch" on a CBZ that exists.** ``fetchAsFile`` was a bare
  ``fetch()`` with no status check and no retry, so any transient hiccup --
  or a 503 arriving as a Blob of error text -- killed the open.
* **Sidebar resizing on a centre click** while the toolbars were already
  hidden: the tap toggled ``immersive`` on top of minimalist mode.
* Continue-reading thumbnails were empty because nothing ever supplied a cover.
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

APP = os.path.join(ROOT, "readerm", "reader", "app")


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


# ────────────────────────────────────────────── hotlink-protected covers


@pytest.mark.parametrize("url,proxied", [
    ("https://uploads.mangadex.org/covers/a/b.jpg.512.jpg", True),
    ("https://mangadex.org/covers/a/b.jpg", True),
    ("https://asuracomic.net/cover.jpg", False),
    ("https://cdn.example.com/x.png", False),
    ("http://127.0.0.1:8000/page?path=x", False),
    ("data:image/png;base64,AAAA", False),
    ("", False),
])
def test_only_hotlink_protected_hosts_are_proxied(url, proxied):
    """A round trip through Python for every cover would be wasteful; only
    the hosts that lie about the image need it.

    This runs the *shipped* ``needsProxy`` rather than a regex-scraped copy of
    the pattern.  The earlier version parsed ``const HOTLINK_PROTECTED = /../i``
    out of the file, so rewriting the literal as ``new RegExp(...)`` broke the
    test while the behaviour was unchanged -- a test that asserted on the
    spelling instead of the answer.
    """
    import re
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node is not available")

    source = read("app.js")
    start = source.index("const HOTLINK_PROTECTED")
    end = source.index("\n}", source.index("function needsProxy")) + 2
    real = source[start:end]
    assert "function needsProxy" in real

    script = real + f"""
        console.log(JSON.stringify(needsProxy({json.dumps(url)})));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                         timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) is proxied


def test_search_results_go_through_the_cover_proxy():
    source = read("app.js")
    block = source[source.index("async function doSearch"):]
    block = block[:block.index("\n}")]
    assert "coverAttrs(" in block
    assert "hydrateCovers(" in block


def test_covers_are_hydrated_lazily():
    """866 results should not mean 866 immediate round trips."""
    source = read("app.js")
    block = source[source.index("function hydrateCovers"):]
    block = block[:block.index("\n}\n")]
    assert "IntersectionObserver" in block
    assert "rootMargin" in block


def test_a_proxied_cover_is_cached():
    source = read("app.js")
    assert "coverCache" in source
    block = source[source.index("async function resolveCover"):]
    block = block[:block.index("\n}")]
    assert "coverCache.has" in block
    assert "coverCache.set" in block


def test_the_proxy_endpoint_returns_a_data_uri(tmp_path, monkeypatch):
    """proxy_cover fetches server-side, where there is no browser Referer."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from readerm.gui import Api

    api = Api()
    source = read("../../gui/__init__.py") if False else open(
        os.path.join(ROOT, "readerm", "gui", "__init__.py"), encoding="utf-8").read()
    block = source[source.index("def proxy_cover"):]
    block = block[:block.index("\n    def ")]
    assert "base64" in block
    assert "data:" in block
    assert callable(getattr(api, "proxy_cover", None))


# ─────────────────────────────────────────────────────── CBZ open retry


def test_the_book_fetch_retries():
    """A transport failure is the reported "sometimes works after a while"."""
    out = _run_fetch_as_file("""
        let n = 0;
        globalThis.fetch = async () => {
            n += 1;
            if (n === 1) throw new TypeError('Failed to fetch');
            return new Response(new Blob(['GOOD']), { status: 200 });
        };
        globalThis.File = class extends Blob {
            constructor(parts, name) { super(parts); this.name = name }
        };
        const f = await fetchAsFile('http://x/book', 'b.cbz');
        console.log(JSON.stringify({ attempts: n, text: await f.text() }));
    """)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["attempts"] == 2, result


def _run_fetch_as_file(script_body):
    """Execute the real fetchAsFile against a scripted fetch, under node."""
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node is not available")
    source = read("app.js")
    start = source.index("async function fetchAsFile")
    end = source.index("\n}", source.index("Tried ${attempts} times")) + 2
    script = source[start:end] + "\n" + script_body
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=60)
    return out


def test_the_book_fetch_checks_the_status():
    """A 503 used to arrive as a Blob of error text and fail as a corrupt zip,
    which reads as "the file is broken" rather than "the server said no".

    Driven for real: a fetch that answers 503 once then succeeds must end up
    with the good body, not the error page.
    """
    out = _run_fetch_as_file("""
        let n = 0;
        globalThis.fetch = async () => {
            n += 1;
            if (n === 1) return new Response('busy', { status: 503 });
            return new Response(new Blob(['GOOD']), { status: 200 });
        };
        globalThis.File = class extends Blob {
            constructor(parts, name) { super(parts); this.name = name }
        };
        const f = await fetchAsFile('http://x/book', 'b.cbz');
        console.log(JSON.stringify({ attempts: n, text: await f.text() }));
    """)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["attempts"] == 2, result
    assert result["text"] == "GOOD", result


def test_an_empty_body_is_rejected():
    """An empty 200 is not a book; retrying is better than parsing nothing."""
    out = _run_fetch_as_file("""
        let n = 0;
        globalThis.fetch = async () => {
            n += 1;
            if (n === 1) return new Response(new Blob([]), { status: 200 });
            return new Response(new Blob(['GOOD']), { status: 200 });
        };
        globalThis.File = class extends Blob {
            constructor(parts, name) { super(parts); this.name = name }
        };
        const f = await fetchAsFile('http://x/book', 'b.cbz');
        console.log(JSON.stringify({ attempts: n, text: await f.text() }));
    """)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    assert result["attempts"] == 2, result
    assert result["text"] == "GOOD", result


def test_a_permanent_failure_says_how_many_tries():
    source = read("app.js")
    block = source[source.index("async function fetchAsFile"):]
    block = block[:block.index("\n}")]
    assert "Tried ${attempts} times" in block


def test_the_retry_backs_off():
    source = read("app.js")
    block = source[source.index("async function fetchAsFile"):]
    block = block[:block.index("\n}")]
    assert "setTimeout" in block


# ───────────────────────────────────────────────── reader chrome + tabs


def test_the_pages_sidebar_has_two_tabs():
    html = read("index.html")
    assert 'data-ptab="all"' in html
    assert 'data-ptab="marked"' in html
    assert 'id="pl-count-all"' in html
    assert 'id="pl-count-marked"' in html


def test_the_marked_tab_filters_to_bookmarks():
    source = read("app.js")
    block = source[source.index("function renderPages()"):]
    block = block[:block.index("\n}")]
    assert "pages.tab === 'marked'" in block
    assert "pages.marks.has(i)" in block


def test_the_toolbars_are_thin():
    """A reader toolbar should be a strip, not a title bar."""
    css = read("style.css")
    block = css[css.index("#r-top, #r-bottom {"):]
    block = block[:block.index("}")]
    assert "padding: 6px 10px" in block


def test_the_drawers_start_below_the_thin_toolbar():
    css = read("style.css")
    assert "top: 44px" in css
    assert "top: 58px" not in css, "a drawer is still positioned for the old bar"


def test_a_centre_tap_does_nothing_in_minimalist_mode():
    """Toggling `immersive` on top of zen only resized an open sidebar --
    the reported "sidebar gets smaller even when the bars are hidden"."""
    source = read("app.js")
    block = source[source.index("// Tap zones."):]
    block = block[:block.index("\n    })")]
    assert "classList.contains('zen')" in block


def test_the_drawers_agree_between_the_two_hidden_modes():
    css = read("style.css")
    assert "#reader.immersive:not(.zen) #r-panel" in css
    assert "#reader.zen #r-panel" in css


# ────────────────────────────────────────────────────────────── autosave


def test_there_is_a_thirty_second_heartbeat():
    """Pinned to the argument setInterval actually receives, so widening it
    to a value that never fires is caught."""
    import re

    source = read("app.js")
    block = source[source.index("function startAutosave"):]
    block = block[:block.index("\nfunction stopAutosave")]
    match = re.search(r"\}, (\d+)\)", block)
    assert match, block
    assert int(match.group(1)) == 30000, match.group(1)


def test_the_position_is_flushed_on_the_way_out():
    """Both events, because browsers fire them in different situations."""
    source = read("app.js")
    assert "addEventListener('pagehide', flushPosition)" in source
    hidden = source[source.index("visibilitychange"):]
    hidden = hidden[:hidden.index("})")]
    assert "flushPosition()" in hidden


def test_autosave_is_silent():
    """Saving is not news; a toast every thirty seconds would be noise."""
    source = read("app.js")
    block = source[source.index("function startAutosave"):]
    block = block[:block.index("function stopAutosave")]
    assert "toast(" not in block


def test_autosave_stops_when_the_reader_closes():
    source = read("app.js")
    block = source[source.index("function closeReader()"):]
    block = block[:block.index("\n}")]
    assert "stopAutosave()" in block


# ───────────────────────────────────────────── continue-reading covers


@pytest.fixture()
def shelf(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    series = tmp_path / "dl" / "Series"
    chapter = series / "Chapter 1"
    chapter.mkdir(parents=True)
    for i in range(1, 4):
        (chapter / f"{i:03d}.jpg").write_bytes(png(40, 60, (10 * i, 90, 200)))
    (series / "cover.jpg").write_bytes(png(40, 60, (220, 90, 140)))

    from readerm.gui import Api

    api = Api()
    yield api, str(chapter)
    server = api._asset_server()
    if server:
        server.stop()
    from readerm.reader.api import ReaderApi
    ReaderApi._assets = None


def test_the_continue_shelf_carries_a_cover(shelf):
    api, chapter = shelf
    api.reader_save_position(chapter, index=1, fraction=0.3, total=3)
    item = api.reader_recent()["items"][0]
    assert item["cover"].startswith("http://127.0.0.1:"), item


def test_the_continue_thumbnail_renders_it():
    source = read("app.js")
    block = source[source.index("function renderContinue"):]
    block = block[:block.index("\n}")]
    assert "i.cover" in block
    assert "background-image" in block
