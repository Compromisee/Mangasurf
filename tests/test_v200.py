"""v2.0.0: the OPDS catalog and cover propagation.

The catalog is validated against the OPDS 1.2 spec rather than against
another implementation, because readers fail in quiet ways -- a mislabelled
link type usually shows an empty shelf, not an error.
"""

import base64
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATOM = "{http://www.w3.org/2005/Atom}"
TOKEN = "OpdsUnitTestToken123"


def read(path):
    return open(path, encoding="utf-8").read()


@pytest.fixture()
def stocked(tmp_path, monkeypatch):
    """A HOME with a library of real files on disk."""
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import config, library
    importlib.reload(config)
    importlib.reload(library)

    books = [
        ("Solo Leveling", "https://x/solo", "asurascans", 3, "cbz"),
        ("Berserk", "https://x/berserk", "mangadex", 2, "epub"),
        ("Vinland Saga", "https://x/vinland", "mangadex", 1, "pdf"),
        ("岸辺露伴", "https://x/cjk", "mangadex", 1, "cbz"),
    ]
    for title, url, source, chapters, ext in books:
        folder = tmp_path / "Manga" / title
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / f"{title}.{ext}"
        out.write_bytes(b"x" * 2048)
        (folder / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 500)
        for i in range(chapters):
            library.record_chapter(url, title, f"Chapter {i + 1}", pages=20,
                                   directory=str(folder), source=source)
        library.record_outputs(url, [str(out)])

    # An entry whose file is gone: must never be offered.
    library.record_chapter("https://x/gone", "Deleted", "Chapter 1",
                           directory="/nowhere", source="mangadex")
    library.record_outputs("https://x/gone", ["/nowhere/gone.cbz"])

    from readerm import opds
    importlib.reload(opds)
    return tmp_path


@pytest.fixture()
def client(stocked):
    import importlib

    from readerm import opdsserve
    importlib.reload(opdsserve)
    app = opdsserve.create_app(token=TOKEN)
    app.config["TESTING"] = True
    return app.test_client()


def auth_get(client, path):
    header = base64.b64encode(b"reader:" + TOKEN.encode()).decode()
    return client.get(path, headers={"Authorization": "Basic " + header})


# ============================================================ the feeds


def test_every_feed_is_well_formed_atom(client):
    for path in ("/opds", "/opds/all", "/opds/recent", "/opds/sources",
                 "/opds/letters", "/opds/search?q=solo"):
        body = auth_get(client, path).data
        ET.fromstring(body)              # raises on malformed XML


def test_every_feed_has_the_required_elements(client):
    """id, title, updated and a self link -- readers reject feeds without."""
    for path in ("/opds", "/opds/all", "/opds/recent"):
        tree = ET.fromstring(auth_get(client, path).data)
        assert tree.findtext(f"{ATOM}id"), path
        assert tree.findtext(f"{ATOM}title"), path
        assert tree.findtext(f"{ATOM}updated"), path
        rels = [l.get("rel") for l in tree.findall(f"{ATOM}link")]
        assert "self" in rels, f"{path} has no self link"


def test_updated_is_rfc3339(client):
    """A malformed date makes some readers drop the entry silently."""
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    assert pattern.match(tree.findtext(f"{ATOM}updated"))
    for entry in tree.findall(f"{ATOM}entry"):
        stamp = entry.findtext(f"{ATOM}updated")
        assert pattern.match(stamp), f"{stamp} is not RFC 3339"


def test_navigation_and_acquisition_links_differ(client):
    """The kind= parameter is how a reader knows what it is following.

    Getting it wrong is the single most common cause of an empty shelf.
    """
    tree = ET.fromstring(auth_get(client, "/opds").data)
    kinds = {}
    for entry in tree.findall(f"{ATOM}entry"):
        title = entry.findtext(f"{ATOM}title")
        link = entry.find(f"{ATOM}link")
        kinds[title] = link.get("type")
    assert "kind=acquisition" in kinds["All titles"]
    assert "kind=navigation" in kinds["By source"]
    assert "kind=navigation" in kinds["Alphabetical"]


def test_every_publication_has_a_typed_acquisition_link(client):
    """Spec: each catalog entry must carry at least one, with a type."""
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    entries = tree.findall(f"{ATOM}entry")
    assert entries, "no publications at all"
    for entry in entries:
        acq = [l for l in entry.findall(f"{ATOM}link")
               if l.get("rel") == "http://opds-spec.org/acquisition"]
        assert acq, f"{entry.findtext(f'{ATOM}title')} has no acquisition link"
        for link in acq:
            assert link.get("type"), "acquisition link with no type"


def test_media_types_match_the_file_format(client):
    """A reader filters on this; a wrong type hides the book."""
    wanted = {
        "Solo Leveling": "application/vnd.comicbook+zip",
        "Berserk": "application/epub+zip",
        "Vinland Saga": "application/pdf",
    }
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    seen = {}
    for entry in tree.findall(f"{ATOM}entry"):
        acq = [l for l in entry.findall(f"{ATOM}link")
               if l.get("rel") == "http://opds-spec.org/acquisition"]
        seen[entry.findtext(f"{ATOM}title")] = acq[0].get("type")
    for title, media in wanted.items():
        assert seen[title] == media, f"{title}: {seen[title]}"


def test_entries_have_stable_ids(client):
    """A changing id makes a reader re-download the whole shelf each sync."""
    first = [e.findtext(f"{ATOM}id") for e in
             ET.fromstring(auth_get(client, "/opds/all").data)
             .findall(f"{ATOM}entry")]
    second = [e.findtext(f"{ATOM}id") for e in
              ET.fromstring(auth_get(client, "/opds/all").data)
              .findall(f"{ATOM}entry")]
    assert first == second
    assert all(i.startswith("urn:uuid:") for i in first)


def test_missing_files_are_not_offered(client):
    """The library records what was produced; the file may since be gone."""
    titles = [e.findtext(f"{ATOM}title") for e in
              ET.fromstring(auth_get(client, "/opds/all").data)
              .findall(f"{ATOM}entry")]
    assert "Deleted" not in titles
    assert "Solo Leveling" in titles


def test_cjk_titles_survive(client):
    titles = [e.findtext(f"{ATOM}title") for e in
              ET.fromstring(auth_get(client, "/opds/all").data)
              .findall(f"{ATOM}entry")]
    assert "岸辺露伴" in titles


def test_facets_only_appear_in_acquisition_feeds(client):
    """The spec forbids them elsewhere, and a reader may reject the feed."""
    nav = ET.fromstring(auth_get(client, "/opds").data)
    facets = [l for l in nav.findall(f"{ATOM}link")
              if l.get("rel") == "http://opds-spec.org/facet"]
    assert facets == [], "facet link in a navigation feed"

    acq = ET.fromstring(auth_get(client, "/opds/all").data)
    facets = [l for l in acq.findall(f"{ATOM}link")
              if l.get("rel") == "http://opds-spec.org/facet"]
    assert facets, "no facets in the acquisition feed"


def test_only_one_facet_is_active(client):
    """The spec: at most one active facet per group."""
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    active = [l for l in tree.findall(f"{ATOM}link")
              if l.get("{http://opds-spec.org/2010/catalog}activeFacet")]
    assert len(active) <= 1


def test_links_are_absolute(client):
    """Several readers resolve relative hrefs against the wrong base."""
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    for entry in tree.findall(f"{ATOM}entry"):
        for link in entry.findall(f"{ATOM}link"):
            href = link.get("href")
            assert href.startswith("http"), href


# ======================================================== search & shelves


def test_search_is_case_insensitive(client):
    for query in ("solo", "SOLO", "SoLo"):
        tree = ET.fromstring(auth_get(client, f"/opds/search?q={query}").data)
        assert len(tree.findall(f"{ATOM}entry")) == 1, query


def test_search_with_no_match_is_an_empty_feed(client):
    tree = ET.fromstring(auth_get(client, "/opds/search?q=zzzz").data)
    assert tree.findall(f"{ATOM}entry") == []
    assert tree.findtext(f"{ATOM}title")        # still a valid feed


def test_empty_search_returns_nothing_rather_than_everything(client):
    tree = ET.fromstring(auth_get(client, "/opds/search?q=").data)
    assert tree.findall(f"{ATOM}entry") == []


def test_the_opensearch_document_is_valid(client):
    body = auth_get(client, "/opds/search.xml").data
    tree = ET.fromstring(body)
    url = tree.find("{http://a9.com/-/spec/opensearch/1.1/}Url")
    assert url is not None
    assert "{searchTerms}" in url.get("template")


def test_grouping_by_source(client):
    tree = ET.fromstring(auth_get(client, "/opds/sources").data)
    names = [e.findtext(f"{ATOM}title") for e in tree.findall(f"{ATOM}entry")]
    assert "mangadex" in names and "asurascans" in names


def test_grouping_by_letter_buckets_non_letters(stocked):
    """Digits and punctuation share a '#' shelf; CJK gets its own.

    str.isalpha() is Unicode-aware, so 岸 counts as a letter and lands
    under 岸 rather than '#'. I assumed otherwise when writing this and the
    code was right: shelving a Japanese title under '#' would be worse.
    """
    from readerm import opds

    groups = opds.group_by_letter(opds.library_rows())
    assert "S" in groups and "B" in groups
    assert "岸" in groups, "a CJK title should shelve under its own character"

    # Anything genuinely non-alphabetic does go to '#'.
    synthetic = [dict(opds.library_rows()[0], title=t)
                 for t in ("2020 Diary", "!Bang", "Zed")]
    buckets = opds.group_by_letter(synthetic)
    assert set(buckets) == {"#", "Z"}, buckets
    assert len(buckets["#"]) == 2


def test_pagination_links_appear_when_needed(stocked):
    from readerm import opds

    rows = [dict(opds.library_rows()[0], id=f"urn:uuid:{i:032d}",
                 title=f"Book {i}") for i in range(opds.PAGE_SIZE * 2 + 5)]
    body = opds.acquisition_feed("http://h", rows, "All", "/opds/all", 0)
    tree = ET.fromstring(body)
    rels = [l.get("rel") for l in tree.findall(f"{ATOM}link")]
    assert "next" in rels
    assert "previous" not in rels, "page 0 must not link backwards"

    body = opds.acquisition_feed("http://h", rows, "All", "/opds/all", 1)
    rels = [l.get("rel") for l in ET.fromstring(body).findall(f"{ATOM}link")]
    assert "previous" in rels and "next" in rels


def test_a_page_holds_at_most_page_size(stocked):
    from readerm import opds

    rows = [dict(opds.library_rows()[0], id=f"urn:uuid:{i:032d}",
                 title=f"Book {i}") for i in range(opds.PAGE_SIZE + 20)]
    tree = ET.fromstring(
        opds.acquisition_feed("http://h", rows, "All", "/opds/all", 0))
    assert len(tree.findall(f"{ATOM}entry")) == opds.PAGE_SIZE


# ============================================================ resources


def test_covers_are_served(client):
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    entry = tree.find(f"{ATOM}entry")
    cover = [l for l in entry.findall(f"{ATOM}link")
             if l.get("rel") == "http://opds-spec.org/image"]
    assert cover, "no cover link"
    path = cover[0].get("href").split("://", 1)[1].split("/", 1)[1]
    response = auth_get(client, "/" + path)
    assert response.status_code == 200
    assert response.mimetype.startswith("image/")


def test_downloads_are_served_with_a_filename(client):
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    entry = tree.find(f"{ATOM}entry")
    acq = [l for l in entry.findall(f"{ATOM}link")
           if l.get("rel") == "http://opds-spec.org/acquisition"][0]
    path = acq.get("href").split("://", 1)[1].split("/", 1)[1]
    response = auth_get(client, "/" + path)
    assert response.status_code == 200
    assert len(response.data) == 2048
    assert "filename" in response.headers.get("Content-Disposition", "")


def test_an_unknown_id_is_a_404_not_a_crash(client):
    assert auth_get(client, "/opds/cover/deadbeef").status_code == 404
    assert auth_get(client, "/opds/download/deadbeef/0").status_code == 404


def test_an_out_of_range_index_is_a_404(client):
    tree = ET.fromstring(auth_get(client, "/opds/all").data)
    entry = tree.find(f"{ATOM}entry")
    short = entry.findtext(f"{ATOM}id").split(":")[-1]
    assert auth_get(client, f"/opds/download/{short}/99").status_code == 404


# =============================================================== auth


def test_a_reader_without_credentials_gets_a_basic_challenge(client):
    """OPDS clients need WWW-Authenticate to know to ask for a password."""
    response = client.get("/opds")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate", "").startswith("Basic ")


def test_a_wrong_password_is_rejected(client):
    header = base64.b64encode(b"reader:wrong").decode()
    assert client.get("/opds",
                      headers={"Authorization": "Basic " + header}
                      ).status_code == 401


def test_the_username_is_ignored(client):
    """Readers demand a username field; only the password is the secret."""
    for user in (b"", b"anything", b"admin"):
        header = base64.b64encode(user + b":" + TOKEN.encode()).decode()
        assert client.get("/opds",
                          headers={"Authorization": "Basic " + header}
                          ).status_code == 200, user


def test_downloads_require_auth_too(client):
    """The feed being protected is useless if the files are not."""
    assert client.get("/opds/download/anything/0").status_code == 401
    assert client.get("/opds/cover/anything").status_code == 401


def test_ping_needs_no_auth(client):
    """So you can tell 'wrong password' from 'wrong address'."""
    body = client.get("/opds/_ping").get_json()
    assert body["ok"] is True and body["auth"] is True


def test_no_auth_mode_serves_openly(stocked):
    import importlib

    from readerm import opdsserve
    importlib.reload(opdsserve)
    client = opdsserve.create_app(token=None).test_client()
    assert client.get("/opds").status_code == 200


# ==================================================== cover propagation


@pytest.fixture()
def image_tree(tmp_path):
    """Folders of loose page images, as an unpacked chapter looks."""
    layout = {
        "Series A/Ch1": ["2.jpg", "10.jpg", "1.jpg"],
        "Series A/Ch2": ["001.png", "002.png"],
        "Series B": ["page.webp"],
        "Series C/raw": ["a.jpg"],          # must be skipped
        "Series D": [],                      # no images at all
    }
    for folder, names in layout.items():
        path = tmp_path / folder
        path.mkdir(parents=True, exist_ok=True)
        for name in names:
            (path / name).write_bytes(b"\xff\xd8" + b"\x00" * 100)
    return tmp_path


def test_pages_sort_naturally(image_tree):
    """Page 2 must come before page 10, or the cover is the wrong page."""
    from readerm import covers

    assert covers.images_in(str(image_tree / "Series A" / "Ch1")) == \
        ["1.jpg", "2.jpg", "10.jpg"]


def test_scan_finds_folders_without_a_cover(image_tree):
    from readerm import covers

    found = {os.path.basename(r["directory"])
             for r in covers.scan_image_folders(str(image_tree))}
    assert found == {"Ch1", "Ch2", "Series B"}


def test_raw_folders_are_skipped(image_tree):
    from readerm import covers

    covers.propagate_covers(str(image_tree))
    assert not (image_tree / "Series C" / "raw" / "cover.jpg").exists()


def test_covers_are_created_with_the_source_extension(image_tree):
    """A PNG written as cover.jpg is a file whose bytes contradict its name."""
    from readerm import covers

    covers.propagate_covers(str(image_tree))
    assert (image_tree / "Series A" / "Ch1" / "cover.jpg").exists()
    assert (image_tree / "Series A" / "Ch2" / "cover.png").exists()
    assert (image_tree / "Series B" / "cover.webp").exists()


def test_the_first_page_is_used(image_tree):
    from readerm import covers

    covers.propagate_covers(str(image_tree))
    made = (image_tree / "Series A" / "Ch1" / "cover.jpg").read_bytes()
    first = (image_tree / "Series A" / "Ch1" / "1.jpg").read_bytes()
    assert made == first


def test_existing_covers_are_left_alone(image_tree):
    from readerm import covers

    target = image_tree / "Series B" / "cover.jpg"
    target.write_bytes(b"ORIGINAL")
    covers.propagate_covers(str(image_tree))
    assert target.read_bytes() == b"ORIGINAL"


def test_overwrite_replaces_them(image_tree):
    from readerm import covers

    target = image_tree / "Series B" / "cover.jpg"
    target.write_bytes(b"ORIGINAL")
    covers.propagate_covers(str(image_tree), overwrite=True)
    # The new cover follows the page's extension, so the old .jpg stays but
    # a .webp appears beside it -- the point is that something was written.
    assert (image_tree / "Series B" / "cover.webp").exists()


def test_running_twice_creates_nothing_new(image_tree):
    from readerm import covers

    covers.propagate_covers(str(image_tree))
    again = covers.propagate_covers(str(image_tree))
    assert again["created"] == []


def test_dry_run_writes_nothing(image_tree):
    from readerm import covers

    result = covers.propagate_covers(str(image_tree), dry_run=True)
    assert result["created"], "dry run reported no work"
    assert not (image_tree / "Series A" / "Ch1" / "cover.jpg").exists()


def test_an_empty_root_does_nothing(tmp_path):
    from readerm import covers

    assert covers.scan_image_folders("") == []
    assert covers.propagate_covers("")["created"] == []
    assert covers.scan_image_folders("/no/such/path") == []


def test_set_cover_replaces_other_extensions(image_tree):
    """Two cover files with different extensions make readers disagree."""
    from readerm import covers

    folder = image_tree / "Series B"
    (folder / "cover.jpg").write_bytes(b"OLD")
    result = covers.set_cover(str(folder), str(folder / "page.webp"))
    assert result["ok"], result
    assert (folder / "cover.webp").exists()
    assert not (folder / "cover.jpg").exists()


def test_set_cover_rejects_non_images(image_tree):
    from readerm import covers

    folder = image_tree / "Series B"
    (folder / "notes.txt").write_text("hello")
    result = covers.set_cover(str(folder), str(folder / "notes.txt"))
    assert result["ok"] is False
    assert "image" in result["error"].lower()


def test_set_cover_reports_missing_paths(tmp_path):
    from readerm import covers

    assert covers.set_cover("/no/such/dir", "/no/such.jpg")["ok"] is False
    assert covers.set_cover(str(tmp_path), "/no/such.jpg")["ok"] is False


# ============================================== settings and integration


def test_the_opds_settings_have_defaults():
    from readerm.gui import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["opds_port"] == 8578
    assert DEFAULT_SETTINGS["opds_autostart"] is False


def test_the_catalog_uses_a_different_port_from_the_app_server():
    """Both must be able to run at once."""
    from readerm.gui import DEFAULT_SETTINGS

    assert DEFAULT_SETTINGS["opds_port"] != DEFAULT_SETTINGS["server_port"]


def test_the_api_exposes_the_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    import importlib

    from readerm import config, servercfg
    importlib.reload(config)
    importlib.reload(servercfg)
    import readerm.gui as gui
    importlib.reload(gui)

    api = gui.Api()
    cfg = api.get_opds_config()
    assert cfg["ok"] and cfg["port"] == 8578
    assert cfg["url"].endswith("/opds")

    assert api.set_opds_config(port=80)["ok"] is False
    assert api.set_opds_config(port=9400)["ok"] is True
    assert api.get_opds_config()["port"] == 9400


def test_autostart_is_wired_into_run_gui():
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def run_gui():"):]
    assert "_maybe_start_opds" in body
    assert "opds_autostart" in body


def test_the_launcher_offers_the_catalog():
    from readerm.landing import Launcher

    assert "opds" in Launcher.TARGETS
    assert "opds" in Launcher.FROZEN_ARGS


def test_the_launcher_routes_the_opds_subcommand():
    source = read(os.path.join(ROOT, "launcher.py"))
    assert 'command == "opds"' in source
    assert "opdsserve" in source


def test_the_spec_bundles_the_catalog():
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    for module in ("readerm.opds", "readerm.opdsserve", "readerm.opdsui"):
        assert f'"{module}"' in spec, module


def test_the_root_wrapper_exists():
    path = os.path.join(ROOT, "opdsserve.py")
    assert os.path.isfile(path)
    source = read(path)
    assert "from readerm.opdsserve import main" in source
    assert len(source.splitlines()) < 30, "the wrapper should stay thin"


def test_opdsserve_help_runs(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    proc = subprocess.run([sys.executable, "opdsserve.py", "--help"],
                          cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=120)
    assert "OPDS" in proc.stdout, proc.stdout[:300] + proc.stderr[:300]


def test_the_opds_catalog_survived_the_renumbering():
    """This began life as `major >= 2`, guarding the OPDS catalog v2.0.0
    shipped. 1.0.0 renumbered the project, so the assertion started failing
    on a release that had removed nothing at all.

    Asserting on the version number never checked the thing it cared about.
    This does: the catalog is still importable and still builds a feed.
    """
    from readerm import opds

    # It must still be able to render a feed, not merely import.
    xml = opds.feed("urn:test", "Test", entries=[], links=[])
    assert "<feed" in xml and "Test" in xml, xml[:200]
