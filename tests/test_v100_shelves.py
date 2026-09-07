"""ReaderM 1.0.0 — library shelves: folders, tags and pins.

The interesting part of this feature is not that folders exist; it is that a
lock has to be enforced in *every* place a title can surface. Locking a shelf
originally hid its books from the tree and from nowhere else:

* the main grid is fed by ``reader_library`` and still listed them -- visible
  in the screenshots, next to the padlock;
* the continue-reading row is built from ``reading.json``, which is keyed by
  file path and had never heard of a shelf;
* ``reader_open`` accepted any path, so a remembered path opened the book.

Each of those is measured below rather than asserted from the source.
"""
import os
import sys
import zipfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A private data dir, so a test never touches a real library.

    The modules read their paths once at import time, so pointing HOME at a
    fresh directory is not enough on its own -- they have to be reloaded, the
    way tests/test_tracking.py already does it. A first version of this
    fixture only patched the path constants and left stale module objects
    behind, which made nine tests pass alone and fail in the suite.
    """
    import importlib

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    import mangasurf.paths
    import mangasurf.library
    import mangasurf.shelves
    import mangasurf.reader.api
    import mangasurf.reader.books
    import mangasurf.gui

    for module in (mangasurf.paths, mangasurf.library,
                   mangasurf.shelves, mangasurf.reader.books, mangasurf.reader.api,
                   mangasurf.gui):
        importlib.reload(module)

    instance = mangasurf.gui.Api()
    return {"api": instance, "library": mangasurf.library,
            "shelves": mangasurf.shelves, "root": tmp_path / "books",
            "mod": mangasurf.reader.api}


def make_book(env, name, url):
    folder = env["root"] / name
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"{name}.cbz"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"0" * 64)
    env["library"].record_chapter(url, name, "Chapter 1", pages=1,
                                  directory=str(folder))
    env["library"].record_outputs(url, [str(archive)])
    return env["library"]._key(url), str(archive)


# ───────────────────────────────────────────────────────── the store


def test_a_shelf_is_created_and_listed(env):
    shelves = env["shelves"]
    assert shelves.create("Manga")["ok"]
    names = [s["name"] for s in shelves.load_shelves()]
    assert names == ["Manga"]


def test_two_shelves_cannot_share_a_name_in_one_place(env):
    shelves = env["shelves"]
    shelves.create("Manga")
    assert shelves.create("manga")["ok"] is False


def test_the_same_name_is_fine_in_different_parents(env):
    """Otherwise "Finished" could only exist once in the whole library."""
    shelves = env["shelves"]
    shelves.create("Manga")
    shelves.create("Comics")
    assert shelves.create("Finished", parent="manga")["ok"]
    assert shelves.create("Finished", parent="comics")["ok"]


def test_a_shelf_cannot_contain_itself(env):
    shelves = env["shelves"]
    shelves.create("Manga")
    assert shelves.set_parent("manga", "manga")["ok"] is False


def test_a_shelf_cannot_move_inside_its_own_child(env):
    """That would detach the subtree from the root and strand every book on
    it -- unreachable in a tree that only walks down from the top."""
    shelves = env["shelves"]
    shelves.create("Manga")
    shelves.create("Ongoing", parent="manga")
    assert shelves.set_parent("manga", "ongoing")["ok"] is False


def test_deleting_a_shelf_promotes_its_children(env):
    shelves = env["shelves"]
    shelves.create("Manga")
    shelves.create("Ongoing", parent="manga")
    shelves.delete("manga")
    remaining = shelves.load_shelves()
    assert [s["id"] for s in remaining] == ["ongoing"]
    assert remaining[0]["parent"] == ""


def test_deleting_a_shelf_keeps_the_books(env):
    """A shelf is a view onto the library, not a container that owns files."""
    shelves = env["shelves"]
    key, _ = make_book(env, "Series", "https://site.test/a")
    shelves.create("Manga")
    shelves.add_book("manga", key)
    shelves.delete("manga")
    titles = [b["title"] for b in env["api"].reader_library()["books"]]
    assert titles == ["Series"]


def test_tags_are_trimmed_and_deduplicated(env):
    shelves = env["shelves"]
    shelves.create("Manga")
    shelves.set_tags("manga", ["Action", "action ", " Shounen", ""])
    assert shelves.get("manga")["tags"] == ["Action", "Shounen"]


def test_tags_can_be_given_as_a_comma_string(env):
    """The dialog hands over one text field, not a list."""
    shelves = env["shelves"]
    shelves.create("Manga")
    shelves.set_tags("manga", "action, ongoing")
    assert shelves.get("manga")["tags"] == ["action", "ongoing"]


def test_pinned_shelves_sort_first(env):
    shelves = env["shelves"]
    shelves.create("Zeta")
    shelves.create("Alpha")
    shelves.update("zeta", pinned=True)
    order = [s["name"] for s in shelves.tree()["shelves"]]
    assert order == ["Zeta", "Alpha"]


def test_a_book_lives_on_one_shelf_at_a_time(env):
    shelves = env["shelves"]
    shelves.create("A")
    shelves.create("B")
    shelves.add_book("a", "k")
    shelves.move_book("k", "b")
    assert shelves.shelf_of("k") == "b"



# ─────────────────────────────────────────────────────────── the tree


def test_folders_arrive_collapsed(env):
    """The user asked for it in as many words: "dont expand folders"."""
    shelves = env["shelves"]
    shelves.create("Manga")
    shelves.create("Ongoing", parent="manga")
    assert shelves.tree()["shelves"][0]["expanded"] is False


def test_books_not_on_a_shelf_come_back_as_unfiled(env):
    shelves = env["shelves"]
    shelves.create("Manga")
    shelves.add_book("manga", "filed")
    data = shelves.tree([{"key": "filed", "title": "A"},
                         {"key": "loose", "title": "B"}])
    assert [b["title"] for b in data["unfiled"]] == ["B"]


def test_the_tree_survives_a_cycle_in_the_stored_file(env):
    """Hand-edited JSON should not hang the app."""
    import json

    shelves = env["shelves"]
    shelves.create("A")
    shelves.create("B")
    data = json.load(open(shelves.SHELVES_PATH))
    for shelf in data:
        shelf["parent"] = "b" if shelf["id"] == "a" else "a"
    json.dump(data, open(shelves.SHELVES_PATH, "w"))
    assert shelves.tree()["shelves"] == []          # unreachable, but no hang
