"""v3.0.0 — the Foliate-based reader.

Covers the asset server (which is the only thing standing between the reader
and the filesystem), the book/page discovery layer, the reading-position and
annotation stores, and the browser-side manga renderer.

The renderer tests drive a real Chromium through Playwright rather than
asserting on attributes, because the two worst bugs found while building it —
a strip that would not scroll and a drawer that swallowed toolbar clicks —
were both invisible to anything that did not lay the page out for real.
"""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
import zlib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

READER = os.path.join(ROOT, "readerm", "reader")
APP = os.path.join(READER, "app")
FOLIATE = os.path.join(READER, "foliate")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------- vendoring


def test_the_foliate_engine_is_vendored():
    for name in ("view.js", "comic-book.js", "epub.js", "paginator.js",
                 "fixed-layout.js", "search.js", "overlayer.js", "progress.js"):
        assert os.path.isfile(os.path.join(FOLIATE, name)), name


def test_the_mit_licence_is_kept_with_the_vendored_code():
    """Foliate-js is MIT; the licence has to travel with it."""
    licence = read(os.path.join(FOLIATE, "LICENSE"))
    assert "MIT License" in licence
    assert "John Factotum" in licence


def test_attribution_is_recorded():
    notice = read(os.path.join(READER, "VENDOR.md"))
    assert "foliate-js" in notice
    assert "MIT" in notice
    # the exact upstream commit, so the fork can be re-based deliberately
    assert re.search(r"\b[0-9a-f]{40}\b", notice)


def test_every_relative_import_in_the_engine_resolves():
    """A missing vendored file is a blank reader, not an error message."""
    missing = []
    for name in os.listdir(FOLIATE):
        if not name.endswith(".js"):
            continue
        source = read(os.path.join(FOLIATE, name))
        for ref in re.findall(r"from '(\./[^']+)'|import\('(\./[^']+)'\)", source):
            target = ref[0] or ref[1]
            if not target.endswith((".js", ".mjs")):
                continue
            if not os.path.isfile(os.path.join(FOLIATE, target)):
                missing.append(f"{name} -> {target}")
    assert missing == [], missing


def test_pdf_source_maps_are_not_shipped():
    """7.7 MB of debug maps have no place in a packaged reader."""
    maps = []
    for dirpath, _, filenames in os.walk(FOLIATE):
        maps += [f for f in filenames if f.endswith(".map")]
    assert maps == [], maps


# ------------------------------------------------------------ asset server


@pytest.fixture()
def server():
    from readerm.reader.assets import AssetServer

    srv = AssetServer()
    srv.start()
    yield srv
    srv.stop()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def test_the_reader_is_served_over_http_not_file(server):
    status, body, headers = _get(server.url("/engine/view.js"))
    assert status == 200
    assert b"export" in body
    assert headers["Content-Type"].startswith("text/javascript")


def test_javascript_is_never_served_as_text_plain(server):
    """Windows reads MIME types from the registry and has been seen calling
    .js text/plain, which makes the browser refuse the module outright."""
    status, _, headers = _get(server.url("/engine/view.js"))
    assert status == 200
    assert "text/plain" not in headers["Content-Type"]


def test_requests_without_the_token_are_refused(server):
    status, body, _ = _get(f"http://127.0.0.1:{server.port}/engine/view.js")
    assert status == 403
    assert b"forbidden" in body


def test_a_wrong_token_is_refused(server):
    status, _, _ = _get(f"http://127.0.0.1:{server.port}/engine/view.js?t=wrong")
    assert status == 403


def test_the_token_is_long_enough_to_not_be_guessed(server):
    assert len(server.token) >= 22


def test_nothing_is_served_until_it_is_allowed(server, tmp_path):
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"\xff\xd8\xffhidden")
    status, body, _ = _get(server.url(f"/page?path={secret}"))
    assert status == 403
    assert b"outside the library" in body


def test_allowing_a_folder_makes_its_files_readable(server, tmp_path):
    page = tmp_path / "01.jpg"
    page.write_bytes(b"\xff\xd8\xff" + b"x" * 100)
    server.allow(str(tmp_path))
    status, body, headers = _get(server.url(f"/page?path={page}"))
    assert status == 200
    assert len(body) == 103
    assert headers["Content-Type"] == "image/jpeg"


@pytest.mark.parametrize("attack", [
    "/app/../../../../etc/passwd",
    "/app/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/app//etc/passwd",
    "/app/....//....//etc/passwd",
])
def test_path_traversal_is_refused(server, attack):
    """http.server does not normalise URLs the way Werkzeug does, so this
    check has to be real rather than inherited from the framework."""
    status, _, _ = _get(server.url(attack))
    assert status in (403, 404)


def test_traversal_is_refused_even_when_the_target_exists(server):
    """The status-code test above passes for a weak reason: /etc/passwd is not
    reachable from the asset root anyway, so a missing guard still 404s.
    This aims at a file that genuinely sits above the asset root -- with the
    guard removed the request succeeds and leaks it.
    """
    target = os.path.join(READER, "assets.py")          # one level above app/
    assert os.path.isfile(target)
    status, body, _ = _get(server.url("/app/../assets.py"))
    assert status == 403, f"leaked {len(body)} bytes from above the asset root"
    assert b"AssetServer" not in body


@pytest.mark.parametrize("rel,safe", [
    ("app/index.html", True),
    ("foliate/view.js", True),
    ("../assets.py", False),
    ("a/../../b", False),
    ("/etc/passwd", False),
    ("\\windows\\system32", False),
    ("", False),
])
def test_is_safe_relative_judges_paths_directly(rel, safe):
    """Unit-level, so the rule is pinned regardless of what happens to exist."""
    from readerm.reader.assets import is_safe_relative

    assert is_safe_relative(rel) is safe


def test_the_page_route_only_serves_images(server, tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("not an image")
    server.allow(str(tmp_path))
    status, body, _ = _get(server.url(f"/page?path={doc}"))
    assert status == 415
    assert b"not an image" in body


def test_range_requests_work_so_the_engine_can_seek_inside_a_zip(server, tmp_path):
    book = tmp_path / "book.cbz"
    book.write_bytes(b"PK\x03\x04" + bytes(range(256)) * 20)
    server.allow(str(tmp_path))
    status, body, headers = _get(server.url(f"/book?path={book}"),
                                 {"Range": "bytes=10-19"})
    assert status == 206
    assert len(body) == 10
    assert headers["Content-Range"].startswith("bytes 10-19/")
    assert headers["Accept-Ranges"] == "bytes"


def test_a_suffix_range_returns_the_tail(server, tmp_path):
    """Zip central directories live at the end of the file."""
    book = tmp_path / "book.cbz"
    book.write_bytes(b"PK\x03\x04" + b"z" * 5000)
    server.allow(str(tmp_path))
    status, body, headers = _get(server.url(f"/book?path={book}"),
                                 {"Range": "bytes=-100"})
    assert status == 206
    assert len(body) == 100
    assert headers["Content-Range"] == "bytes 4904-5003/5004"


def test_the_server_binds_only_to_loopback(server):
    from readerm.reader.assets import LOOPBACK

    assert LOOPBACK == "127.0.0.1"
    assert server.url("/").startswith("http://127.0.0.1:")


def test_a_symlink_cannot_escape_an_allowed_folder(server, tmp_path):
    if not hasattr(os, "symlink"):
        pytest.skip("no symlinks on this platform")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.jpg").write_bytes(b"\xff\xd8\xffnope")
    inside = tmp_path / "inside"
    inside.mkdir()
    try:
        os.symlink(outside / "secret.jpg", inside / "link.jpg")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted here")
    server.allow(str(inside))
    status, _, _ = _get(server.url(f"/page?path={inside / 'link.jpg'}"))
    assert status == 403


def test_ping_needs_no_token(server):
    status, body, _ = _get(f"http://127.0.0.1:{server.port}/_ping")
    assert status == 200
    assert body == b"ok"


# ------------------------------------------------------------------- books


@pytest.fixture()
def library_dir(tmp_path):
    series = tmp_path / "Series"
    for chapter, pages in [("Chapter 1", 3), ("Chapter 2", 12), ("Chapter 10", 2)]:
        folder = series / chapter
        folder.mkdir(parents=True)
        for i in range(1, pages + 1):
            (folder / f"{i}.jpg").write_bytes(b"\xff\xd8\xff")
        (folder / "cover.jpg").write_bytes(b"\xff\xd8\xffcover")
    raw = series / "Chapter 1" / "raw"
    raw.mkdir()
    (raw / "1.jpg").write_bytes(b"\xff\xd8\xffraw")
    return series


def test_chapter_folders_are_found_in_natural_order(library_dir):
    from readerm.reader import books

    names = [os.path.basename(p) for p in books.chapter_folders(str(library_dir))]
    assert names == ["Chapter 1", "Chapter 2", "Chapter 10"]


def test_raw_folders_are_skipped(library_dir):
    from readerm.reader import books

    found = books.chapter_folders(str(library_dir))
    assert not any(os.path.basename(p) == "raw" for p in found)


def test_pages_sort_numerically_not_alphabetically(library_dir):
    from readerm.reader import books

    pages = books.pages_of(str(library_dir / "Chapter 2"))
    names = [os.path.basename(p) for p in pages]
    assert names[:3] == ["1.jpg", "2.jpg", "3.jpg"]
    assert names[-1] == "12.jpg"
    assert names.index("2.jpg") < names.index("10.jpg")


def test_cover_files_are_not_pages(library_dir):
    from readerm.reader import books

    pages = books.pages_of(str(library_dir / "Chapter 1"))
    assert len(pages) == 3
    assert not any("cover" in os.path.basename(p) for p in pages)


def test_a_folder_holding_only_a_cover_is_not_a_chapter(tmp_path):
    """A series folder usually has cover.jpg sitting next to the chapter
    folders. Counting that as a chapter puts a phantom one-page entry at the
    top of every series.
    """
    from readerm.reader import books

    series = tmp_path / "Series"
    (series / "Chapter 1").mkdir(parents=True)
    (series / "Chapter 1" / "1.jpg").write_bytes(b"\xff\xd8\xff")
    (series / "cover.jpg").write_bytes(b"\xff\xd8\xffseries cover")

    found = [os.path.basename(p) for p in books.chapter_folders(str(series))]
    assert found == ["Chapter 1"], found


def test_pages_are_absolute_paths(library_dir):
    from readerm.reader import books

    for page in books.pages_of(str(library_dir / "Chapter 1")):
        assert os.path.isabs(page)
        assert os.path.isfile(page)


def test_cbr_is_reported_as_unopenable_with_a_reason(tmp_path):
    """unrar is not bundled; saying so beats failing silently in the browser."""
    from readerm.reader import books

    book = tmp_path / "x.cbr"
    book.write_bytes(b"Rar!")
    info = books.describe(str(book))
    assert info["readable"] is False
    assert "unrar" in info["reason"]


@pytest.mark.parametrize("ext", [".cbz", ".epub", ".pdf", ".mobi", ".azw3", ".fb2"])
def test_supported_formats_are_readable(tmp_path, ext):
    from readerm.reader import books

    book = tmp_path / f"book{ext}"
    book.write_bytes(b"data")
    assert books.describe(str(book))["readable"] is True


def test_packaged_outputs_come_before_loose_folders(library_dir, tmp_path):
    from readerm.reader import books

    packaged = tmp_path / "Series.cbz"
    with zipfile.ZipFile(packaged, "w") as zf:
        zf.writestr("1.jpg", b"\xff\xd8\xff")
    entry = {"directory": str(library_dir), "outputs": [str(packaged)]}
    items = books.entry_items(entry)
    assert items[0]["kind"] == "file"
    assert [i["kind"] for i in items[1:]] == ["folder"] * 3


def test_an_empty_folder_is_not_offered_as_readable(tmp_path):
    from readerm.reader import books

    empty = tmp_path / "Empty"
    empty.mkdir()
    assert books.describe(str(empty))["readable"] is False


# ---------------------------------------------------- positions and marks


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import readerm.reader.api as api

    monkeypatch.setattr(api, "READING_PATH", str(tmp_path / "reading.json"))
    monkeypatch.setattr(api, "ANNOTATIONS_PATH", str(tmp_path / "annotations.json"))
    return api


def test_a_reading_position_survives_a_round_trip(store, tmp_path):
    book = str(tmp_path / "Chapter 1")
    store.save_position(book, index=4, fraction=0.63, total=20, mode="webtoon")
    got = store.get_position(book)
    assert got["index"] == 4
    assert got["fraction"] == 0.63
    assert got["mode"] == "webtoon"


def test_positions_are_keyed_the_way_the_platform_compares_paths(store):
    """os.path.normcase folds case on Windows and is a no-op on POSIX, so the
    expectation has to follow the platform rather than assert one behaviour."""
    store.save_position("/Books/Chapter 1", index=2)
    lookup = store.get_position("/books/chapter 1")
    if os.path.normcase("/A") == os.path.normcase("/a"):
        assert lookup.get("index") == 2          # Windows: same book
    else:
        assert lookup == {}                       # POSIX: genuinely different


def test_the_same_path_written_two_ways_is_one_entry(store, tmp_path):
    """A trailing slash or a '.' segment must not create a second position."""
    book = str(tmp_path / "Chapter 1")
    store.save_position(book, index=3)
    store.save_position(os.path.join(book, "."), index=7)
    assert store.get_position(book)["index"] == 7
    assert len(store.load_positions()) == 1


def test_clearing_one_position_leaves_the_others(store):
    store.save_position("/a", index=1)
    store.save_position("/b", index=2)
    assert store.clear_positions("/a") == 1
    assert store.get_position("/a") == {}
    assert store.get_position("/b")["index"] == 2


def test_bookmarks_and_notes_get_distinct_ids(store):
    """A millisecond timestamp collided when both were added in one tick,
    and deleting the bookmark then removed the note as well."""
    path = "/book"
    mark = store.save_annotation(path, "bookmark", {"index": 1})
    note = store.save_annotation(path, "note", {"index": 1, "text": "hi"})
    assert mark["id"] != note["id"]


def test_deleting_a_bookmark_leaves_notes_alone(store):
    path = "/book"
    mark = store.save_annotation(path, "bookmark", {"index": 1})
    store.save_annotation(path, "note", {"index": 1, "text": "keep me"})
    assert store.delete_annotation(path, "bookmark", mark["id"]) is True
    saved = store.load_annotations(path)
    assert saved["bookmarks"] == []
    assert len(saved["notes"]) == 1


def test_many_annotations_in_one_tick_all_get_unique_ids(store):
    ids = {store.save_annotation("/b", "bookmark", {"index": i})["id"]
           for i in range(50)}
    assert len(ids) == 50


# --------------------------------------------------------------- reader API


@pytest.fixture()
def reader_api(store, tmp_path):
    from readerm.reader.api import ReaderApi

    api = ReaderApi()
    yield api
    if ReaderApi._assets is not None:
        ReaderApi._assets.stop()
        ReaderApi._assets = None


def test_opening_a_chapter_folder_returns_page_urls(reader_api, library_dir):
    result = reader_api.reader_open(str(library_dir / "Chapter 1"))
    assert result["ok"] is True
    assert result["kind"] == "pages"
    assert result["count"] == 3
    assert all(u.startswith("http://127.0.0.1:") for u in result["pages"])


def test_the_returned_page_urls_actually_serve_bytes(reader_api, library_dir):
    result = reader_api.reader_open(str(library_dir / "Chapter 1"))
    status, body, headers = _get(result["pages"][0])
    assert status == 200
    assert body.startswith(b"\xff\xd8\xff")
    assert headers["Content-Type"] == "image/jpeg"


def test_opening_a_missing_path_fails_cleanly(reader_api):
    result = reader_api.reader_open("/no/such/place")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_next_and_previous_chapter_walk_in_natural_order(reader_api, library_dir):
    nxt = reader_api.reader_open_next(str(library_dir / "Chapter 1"))
    assert nxt["title"] == "Chapter 2"
    prev = reader_api.reader_open_previous(str(library_dir / "Chapter 2"))
    assert prev["title"] == "Chapter 1"


def test_walking_past_the_last_chapter_says_so(reader_api, library_dir):
    result = reader_api.reader_open_next(str(library_dir / "Chapter 10"))
    assert result["ok"] is False
    assert "last chapter" in result["error"]


def test_a_saved_position_comes_back_when_the_chapter_is_reopened(reader_api, library_dir):
    chapter = str(library_dir / "Chapter 2")
    reader_api.reader_save_position(chapter, index=5, fraction=0.5, total=12)
    assert reader_api.reader_open(chapter)["position"]["fraction"] == 0.5


def test_the_chapter_list_reports_page_counts(reader_api, library_dir):
    chapters = reader_api.reader_chapters(directory=str(library_dir))["chapters"]
    assert [c["pages"] for c in chapters] == [3, 12, 2]


def test_reader_endpoints_are_on_the_gui_api():
    """The CLI, TUI, phone server and OPDS catalog all use this one object."""
    from readerm.gui import Api

    for name in ("reader_open", "reader_library", "reader_save_position",
                 "reader_chapters", "reader_info"):
        assert callable(getattr(Api, name, None)), name


def test_reading_preferences_are_in_the_settings_defaults():
    from readerm.gui import DEFAULT_SETTINGS

    for key in ("reader_mode", "reader_theme", "reader_fit", "reader_spread"):
        assert key in DEFAULT_SETTINGS, key


# ------------------------------------------------------------------ themes


def test_theme_definitions_moved_to_the_stylesheet():
    """v3.1.0 moved the palettes from themes.js into theme.css so a theme is
    one attribute on <html>. The palette checks that used to live here are
    now in test_v310.py, where they read the *rendered* page rather than the
    source text."""
    js = read(os.path.join(APP, "themes.js"))
    assert "THEME_ORDER" in js
    assert "createMatrix" in js
    assert os.path.isfile(os.path.join(APP, "theme.css"))


def test_the_reader_still_exposes_a_theme_list():
    js = read(os.path.join(APP, "themes.js"))
    names = re.findall(r"^\s{4}([a-z]+):\s*\{ label:", js, re.M)
    assert len(names) >= 8, names
    assert "midnight" in names


# ------------------------------------------------------------- packaging


def test_the_spec_bundles_the_reader():
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    assert '("readerm/reader/app", "readerm/reader/app")' in spec
    assert '("readerm/reader/foliate", "readerm/reader/foliate")' in spec


def test_the_old_front_end_is_gone():
    assert not os.path.exists(os.path.join(ROOT, "readerm", "gui", "web"))


def test_the_gui_window_loads_the_reader_over_http():
    """file:// would break every ES module import in the engine."""
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    assert "reader_info()" in source
    body = source[source.index("def run_gui"):]
    assert "webview.create_window" in body
    window = body[body.index("webview.create_window"):]
    window = window[:window.index(")")]
    assert "target" in window


def test_modules_using_relative_imports_keep_the_package_guard():
    """Repo convention: a module run directly must still resolve `from .`."""
    offenders = []
    for name in os.listdir(READER):
        path = os.path.join(READER, name)
        if not name.endswith(".py"):
            continue
        source = read(path)
        if re.search(r"^from \.", source, re.M) and "__package__" not in source:
            offenders.append(name)
    assert offenders == [], offenders


def test_the_version_is_a_sane_three_part_number():
    """Was `startswith("3.")`. The 1.0.0 renumbering made that fail without
    anything being broken, so it now checks the shape rather than the value
    -- the part that a release can actually get wrong."""
    import readerm

    parts = readerm.__version__.split(".")
    assert len(parts) == 3, readerm.__version__
    assert all(p.isdigit() for p in parts), readerm.__version__


def test_the_packaged_metadata_agrees_with_the_module():
    import re

    pyproject = read(os.path.join(ROOT, "pyproject.toml"))
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    import readerm

    assert declared == readerm.__version__


# ------------------------------------------------- phone server + reader


def _server_client():
    """A Flask test client for the LAN phone server."""
    pytest.importorskip("flask")
    from readerm import server as phone

    api = object()
    buffer = phone.EventBuffer()
    log = phone.ServerLog()
    app = phone.create_app("t" * 20, api, buffer, log)
    app.config["TESTING"] = True
    return app.test_client()


def test_the_phone_server_serves_the_reader_engine():
    """The engine sits beside the app directory, not inside it. Serving it
    through the generic asset route 404'd the whole of foliate/ in a real
    frozen build while every app/ file returned 200 -- a reader that loads
    and then never boots.
    """
    client = _server_client()
    for name in ("foliate/view.js", "foliate/comic-book.js",
                 "foliate/vendor/zip.js"):
        response = client.get(f"/{name}")
        assert response.status_code == 200, name
        assert len(response.data) > 200, name


def test_the_phone_server_serves_the_reader_app():
    client = _server_client()
    for name in ("app.js", "manga-view.js", "themes.js", "style.css"):
        assert client.get(f"/{name}").status_code == 200, name


def test_the_engine_route_still_refuses_traversal():
    client = _server_client()
    for attack in ("foliate/../../../etc/passwd",
                   "foliate/../server.py"):
        assert client.get(f"/{attack}").status_code in (403, 404), attack


def test_the_phone_page_is_the_reader():
    """With a valid token the phone gets the same reader the desktop uses."""
    client = _server_client()
    body = client.get("/?token=" + "t" * 20).data.decode("utf-8")
    assert "manga-view" in body
    assert 'type="module"' in body
    assert "/bridge.js" in body, "the pywebview shim was not injected"


def test_the_phone_page_still_demands_a_token():
    client = _server_client()
    assert client.get("/").status_code == 401
