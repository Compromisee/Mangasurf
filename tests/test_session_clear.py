"""\"Clear library for this session\" is a view-only reset.

It must empty every reader of library.json without ever deleting the file or
the folders on disk: downloads keep being recorded, and a restart brings the
full library back. These tests pin that contract.
"""
import os

from mangasurf import library


def _isolate(tmp_path, monkeypatch):
    """Point the library files at a throwaway dir so tests never touch real data."""
    monkeypatch.setattr(library, "DIR", str(tmp_path))
    monkeypatch.setattr(library, "LIBRARY_PATH", str(tmp_path / "library.json"))
    monkeypatch.setattr(library, "BOOKMARKS_PATH", str(tmp_path / "bookmarks.json"))


def test_set_session_clear_toggles_flag(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert library.session_cleared() is False
    library.set_session_clear(True)
    assert library.session_cleared() is True
    library.set_session_clear(False)
    assert library.session_cleared() is False


def test_cleared_library_loads_empty_but_disk_is_untouched(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    library.record_chapter("https://x.example/manga", "Title", "Chapter 1", pages=3)
    assert os.path.exists(library.LIBRARY_PATH)
    assert len(library.load_library()) == 1

    # Clear for the session: the view is empty...
    library.set_session_clear(True)
    assert library.load_library() == {}

    # ...but the file on disk is still there, untouched.
    assert os.path.exists(library.LIBRARY_PATH)
    assert len(library._load(library.LIBRARY_PATH, {})) == 1

    # Downloads still save (they write straight to disk) and the recorded
    # per-manga lookups still work, so "downloaded" highlighting is unaffected.
    library.record_chapter("https://x.example/manga", "Title", "Chapter 2", pages=5)
    assert library.downloaded_chapters("https://x.example/manga") == {"Chapter 1", "Chapter 2"}

    # Restoring the session brings everything back.
    library.set_session_clear(False)
    assert len(library.load_library()) == 1


def test_session_clear_resets_on_reload(tmp_path, monkeypatch):
    """The flag is process memory: a fresh import defaults to cleared=False."""
    _isolate(tmp_path, monkeypatch)
    library.set_session_clear(True)
    assert library.session_cleared() is True
    # Simulate a restart by resetting the module-level flag.
    library.set_session_clear(False)
    assert library.session_cleared() is False
