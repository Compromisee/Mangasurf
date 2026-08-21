"""ReaderM 1.0.1 — LAN streaming and the read-only local API.

Two gaps this release closes, both found by probing a running server rather
than by reading code:

* **Books could not be read from a phone.** ``reader_open`` hands the
  front-end URLs on the local asset server, which is bound to 127.0.0.1 on
  purpose. On a phone that address is the *phone*. Pointing it at the host's
  LAN address does not help either -- measured, the asset server answers a
  non-loopback caller with 403. The bytes are now proxied through the Flask
  server's ``/stream`` routes, which honour Range so a big CBZ opens without
  being downloaded whole.

* **Nothing could ask this install anything.** ``/local/*`` is a read-only
  description of the library: paths, books, positions, covers, sources,
  shelves, stats. Documented for other programs in MD/AGENT.md.

The rule that matters most here: a locked shelf must stay hidden through
*every* one of those surfaces. A privacy screen a local script can walk
around is not one.
"""
import importlib
import json
import os
import struct
import sys
import threading
import time
import zipfile
import zlib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

flask = pytest.importorskip("flask")
requests = pytest.importorskip("requests")


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


IMAGE = png(40, 60, 120)


@pytest.fixture()
def live(tmp_path, monkeypatch):
    """A real library on disk, behind a real Flask server."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    import readerm.paths
    import readerm.library
    import readerm.passlock
    import readerm.shelves
    import readerm.reader.books
    import readerm.reader.api
    import readerm.localapi
    import readerm.gui
    import readerm.server

    for module in (readerm.paths, readerm.library, readerm.passlock,
                   readerm.shelves, readerm.reader.books, readerm.reader.api,
                   readerm.localapi, readerm.gui, readerm.server):
        importlib.reload(module)

    library, shelves = readerm.library, readerm.shelves
    books_root = tmp_path / "books"

    def make(name, url, packaged=False):
        folder = books_root / name
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (folder / f"{i:03}.png").write_bytes(IMAGE)
        (folder / "cover.png").write_bytes(IMAGE)
        outputs = []
        if packaged:
            archive = folder / f"{name}.cbz"
            with zipfile.ZipFile(archive, "w") as zf:
                for i in range(8):
                    zf.writestr(f"{i:03}.jpg", IMAGE)
            outputs = [str(archive)]
        library.record_chapter(url, name, "Chapter 1", pages=3,
                               directory=str(folder))
        if outputs:
            library.record_outputs(url, outputs)
        return library._key(url), str(folder), (outputs[0] if outputs else "")

    public = make("Public Series", "https://site.test/public", packaged=True)
    secret = make("Secret Series", "https://site.test/secret")

    shelves.create("Private")
    shelves.add_book("private", secret[0])
    shelves.set_lock("private", "hunter2")

    api = readerm.gui.Api()
    readerm.reader.api.ReaderApi._unlocked_shelves = set()
    app = readerm.server.create_app(token="tok", api=api)

    import werkzeug.serving

    server = werkzeug.serving.make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    base = f"http://127.0.0.1:{server.port}"
    session = requests.Session()
    session.params = {"token": "tok"}

    # Opening a book is what opts its folder into being served -- the same
    # gate the desktop reader goes through.
    session.post(f"{base}/api/reader_open", json={"args": [public[1]]},
                 timeout=10)

    yield {"base": base, "get": lambda p, **kw: session.get(base + p,
                                                            timeout=10, **kw),
           "session": session, "public": public, "secret": secret,
           "api": api, "shelves": shelves, "localapi": readerm.localapi,
           "mod": readerm.reader.api}
    server.shutdown()


# ──────────────────────────────────────────────────────── streaming


def test_a_page_streams_over_http(live):
    page = os.path.join(live["public"][1], "000.png")
    got = live["get"]("/stream/page", params={"token": "tok", "path": page})
    assert got.status_code == 200
    assert got.content[:4] == b"\x89PNG"
    assert got.headers["Content-Type"].startswith("image/")


def test_a_packaged_book_streams(live):
    got = live["get"]("/stream/book", params={"token": "tok",
                                              "path": live["public"][2]})
    assert got.status_code == 200
    assert got.content[:2] == b"PK"
    assert got.headers.get("Accept-Ranges") == "bytes"


def test_ranges_work_so_a_big_cbz_can_be_seeked(live):
    """Without this the engine downloads the whole archive before showing
    page one. An 88 MB chapter is a long wait for the first image."""
    path = live["public"][2]
    whole = live["get"]("/stream/book", params={"token": "tok", "path": path})
    part = live["get"]("/stream/book", params={"token": "tok", "path": path},
                       headers={"Range": "bytes=0-99"})
    assert part.status_code == 206
    assert len(part.content) == 100
    assert part.content == whole.content[:100]
    assert part.headers["Content-Range"] == f"bytes 0-99/{len(whole.content)}"


def test_a_suffix_range_returns_the_real_tail(live):
    """`bytes=-50` is how a zip reader finds the central directory, so
    getting it wrong means a CBZ that never opens."""
    path = live["public"][2]
    whole = live["get"]("/stream/book", params={"token": "tok", "path": path})
    tail = live["get"]("/stream/book", params={"token": "tok", "path": path},
                       headers={"Range": "bytes=-50"})
    assert tail.status_code == 206
    assert tail.content == whole.content[-50:]


def test_streaming_refuses_a_file_nobody_allowed(live):
    for path in ("/etc/passwd", os.path.join(ROOT, "pyproject.toml")):
        got = live["get"]("/stream/page", params={"token": "tok", "path": path})
        assert got.status_code == 404, path


def test_streaming_needs_the_token(live):
    page = os.path.join(live["public"][1], "000.png")
    got = requests.get(live["base"] + "/stream/page",
                       params={"path": page}, timeout=10)
    assert got.status_code == 401


def test_a_locked_book_cannot_be_streamed(live):
    """reader_open refuses it, so its folder is never allowed."""
    page = os.path.join(live["secret"][1], "000.png")
    got = live["get"]("/stream/page", params={"token": "tok", "path": page})
    assert got.status_code == 404


# ──────────────────────────────────────────────────── the local API


ENDPOINTS = ["info", "paths", "books", "reading", "covers", "sources",
             "shelves", "stats"]


@pytest.mark.parametrize("name", ENDPOINTS)
def test_every_endpoint_answers_with_an_object_and_ok(live, name):
    """One field to branch on, for all of them."""
    got = live["get"](f"/local/{name}")
    assert got.status_code == 200, name
    body = got.json()
    assert isinstance(body, dict), name
    assert body.get("ok") is True, name


def test_an_unknown_endpoint_lists_the_real_ones(live):
    got = live["get"]("/local/nope")
    assert got.status_code == 404
    assert sorted(got.json()["endpoints"]) == sorted(ENDPOINTS)


def test_the_local_api_needs_the_token(live):
    got = requests.get(live["base"] + "/local/books", timeout=10)
    assert got.status_code == 401


def test_info_names_every_other_endpoint(live):
    """So a consumer can discover the API from the API instead of from a
    document that goes stale."""
    body = live["get"]("/local/info").json()
    for name in ENDPOINTS:
        assert name in body["endpoints"], name
    assert "page" in body["endpoints"] and "book" in body["endpoints"]


def test_paths_are_absolute_everywhere(live):
    """A consumer runs in its own working directory."""
    paths = live["get"]("/local/paths").json()
    assert os.path.isabs(paths["data_dir"])
    for name, entry in paths["files"].items():
        assert os.path.isabs(entry["path"]), name
    for book in live["get"]("/local/books").json()["books"]:
        for field in ("directory", "cover"):
            if book[field]:
                assert os.path.isabs(book[field]), (book["title"], field)
        for out in book["outputs"]:
            assert os.path.isabs(out)


def test_books_carry_a_stable_key_not_just_a_title(live):
    books = live["get"]("/local/books").json()["books"]
    assert books
    for book in books:
        assert book["key"], book


def test_chapters_are_opt_in(live):
    """A 900-chapter series is a lot of JSON for someone who wanted a path."""
    plain = live["get"]("/local/books").json()["books"][0]
    assert "chapters" not in plain
    full = live["get"]("/local/books", params={"token": "tok", "chapters": "1"}) \
        .json()["books"][0]
    assert isinstance(full["chapters"], list)


def test_sources_are_actually_listed(live):
    """An earlier version called a function that does not exist inside a bare
    `except`, so it silently returned [] and looked like a build with no
    sources at all."""
    body = live["get"]("/local/sources").json()
    assert body["count"] >= 10, body["count"]
    assert all(s["id"] and s["name"] for s in body["sources"])


def test_reading_reports_page_and_percent(live):
    live["api"].reader_save_position(live["public"][2], index=3, total=10,
                                     title="Public Series")
    rows = live["get"]("/local/reading").json()["reading"]
    assert rows
    row = rows[0]
    assert row["page"] == 4 and row["pages"] == 10
    assert row["percent"] == round(row["fraction"] * 100)
    assert row["finished"] is False


def test_stats_add_up(live):
    stats = live["get"]("/local/stats").json()
    assert stats["series"] == len(live["get"]("/local/books").json()["books"])
    assert stats["locked_shelves"] >= 1


# ─────────────────────────────────────── locked shelves stay locked


def test_a_locked_book_is_absent_from_books(live):
    titles = [b["title"] for b in live["get"]("/local/books").json()["books"]]
    assert titles == ["Public Series"]


def test_a_locked_book_is_absent_from_covers(live):
    titles = [c["title"] for c in live["get"]("/local/covers").json()["covers"]]
    assert "Secret Series" not in titles


def test_a_locked_book_is_absent_from_reading(live):
    live["api"].reader_save_position(
        os.path.join(live["secret"][1], "000.png"), index=1, total=3,
        title="Secret Series")
    titles = [r["title"] for r in live["get"]("/local/reading").json()["reading"]]
    assert "Secret Series" not in titles


def test_the_shelf_tree_shows_the_padlock_but_not_the_contents(live):
    shelves = live["get"]("/local/shelves").json()["shelves"]
    assert len(shelves) == 1
    node = shelves[0]
    assert node["locked"] is True
    assert node["books"] == []
    assert node["book_count"] == 1          # honest about how much is hidden


def test_no_payload_leaks_a_passcode_or_its_verifier(live):
    blob = json.dumps([live["get"](f"/local/{n}").json() for n in ENDPOINTS])
    for secret in ("hunter2", '"hash"', '"salt"', '"iterations"'):
        assert secret not in blob, secret


def test_unlocking_reveals_the_book_again(live):
    assert live["api"].shelf_unlock("private", "hunter2")["ok"] is True
    titles = [b["title"] for b in live["get"]("/local/books").json()["books"]]
    assert "Secret Series" in titles


# ────────────────────────────────────────────── offline, no server


def test_the_same_data_is_available_without_http(live):
    """`readerm api <name>` and `from readerm import localapi`."""
    localapi = live["localapi"]
    for name in ENDPOINTS:
        payload = json.loads(localapi.dump(name))
        assert payload not in (None,), name
    info = json.loads(localapi.dump("info"))
    assert info["ok"] is True and info["app"] in ("ReaderM", "Mangasurf")


def test_an_unknown_endpoint_offline_explains_itself(live):
    payload = json.loads(live["localapi"].dump("nope"))
    assert payload["ok"] is False
    assert sorted(payload["endpoints"]) == sorted(ENDPOINTS)


def test_the_api_version_is_declared(live):
    """Consumers branch on it, so it has to exist and be an integer."""
    info = json.loads(live["localapi"].dump("info"))
    assert isinstance(info["api_version"], int)


# ─────────────────────────────────────────────────── the front-end


def test_the_reader_rewrites_loopback_urls_when_served_over_a_network():
    """reader_open returns 127.0.0.1 URLs. On a phone that is the phone."""
    import re
    import shutil
    import subprocess

    if not shutil.which("node"):
        pytest.skip("node is not available")

    source = open(os.path.join(ROOT, "readerm/reader/app/app.js"),
                  encoding="utf-8").read()
    start = source.index("function streamUrl(")
    end = source.index("\n}", start) + 2
    body = source[start:end]

    script = f"""
        const cases = [];
        const run = (host, url) => {{
            const location = {{ hostname: host,
                origin: `http://${{host}}:8577`,
                href: `http://${{host}}:8577/index.html` }};
            {body}
            return streamUrl(url);
        }};
        const P = 'http://127.0.0.1:39551/page?path=%2Fb%2F1.jpg&t=x';
        const B = 'http://127.0.0.1:39551/book?path=%2Fb%2FA.cbz&t=x';
        console.log(JSON.stringify({{
            loopback: run('127.0.0.1', P),
            lanPage: run('192.168.1.9', P),
            lanBook: run('192.168.1.9', B),
            remote: run('192.168.1.9', 'https://cdn.test/x.jpg'),
            empty: run('192.168.1.9', ''),
        }}));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)

    # On loopback nothing changes.
    assert got["loopback"].startswith("http://127.0.0.1:39551/page")
    # On a LAN the bytes come through this origin instead.
    assert got["lanPage"] == \
        "http://192.168.1.9:8577/stream/page?path=%2Fb%2F1.jpg"
    assert got["lanBook"] == \
        "http://192.168.1.9:8577/stream/book?path=%2Fb%2FA.cbz"
    # Anything already remote is left alone.
    assert got["remote"] == "https://cdn.test/x.jpg"
    assert got["empty"] == ""


# ───────────────────────────────────────────────────── the document


def test_agent_md_exists_and_describes_the_real_endpoints():
    """A document that names endpoints which do not exist is worse than none."""
    from readerm import localapi

    text = open(os.path.join(ROOT, "MD", "AGENT.md"), encoding="utf-8").read()
    for name in localapi.ENDPOINTS:
        assert f"/local/{name}" in text, name
    assert "/stream/page" in text and "/stream/book" in text


def test_quickrun_only_promises_commands_that_exist():
    """It previously advertised `readerm server`, which was parsed as a URL
    to download."""
    from readerm.cli import DELEGATED

    text = open(os.path.join(ROOT, "MD", "QUICKRUN.md"), encoding="utf-8").read()
    for command in ("server", "opds"):
        assert command in DELEGATED, command
        assert f"readerm {command}" in text or f"readerm.{command}" in text


def test_every_markdown_doc_except_the_readme_lives_in_md():
    at_root = [f for f in os.listdir(ROOT) if f.endswith(".md")]
    assert at_root == ["README.md"], at_root
    assert os.path.isdir(os.path.join(ROOT, "MD"))


def test_every_relative_markdown_link_resolves():
    """Moving the docs into MD/ broke links in both directions: the README
    needed an MD/ prefix, and files already inside MD/ were given one they
    must not have. A bulk rewrite got the second half wrong, so this walks
    every link and opens it."""
    import glob
    import re

    broken = []
    docs = [os.path.join(ROOT, "README.md")] + glob.glob(
        os.path.join(ROOT, "MD", "*.md"))
    for doc in docs:
        base = os.path.dirname(doc)
        text = open(doc, encoding="utf-8").read()
        for target in re.findall(r"\]\(([^)#]+\.md)[^)]*\)", text):
            if target.startswith(("http://", "https://")):
                continue
            if not os.path.isfile(os.path.join(base, target)):
                broken.append(f"{os.path.relpath(doc, ROOT)} -> {target}")
    assert broken == [], broken
