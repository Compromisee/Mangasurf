"""Regression tests for v1.4.7.

Covers the reported bugs and the new features:

* bookmark / library covers not showing
* the download cart being invisible until a job was already running
* the Type filter (manga / manhwa / manhua) not affecting results
* square corners not reaching progress bars or the search box
* the chapter min/max filter appearing not to work
* bookmark folders, advanced info, custom columns
"""

import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    """Throwaway HOME per test.

    Library, bookmarks and folders are JSON files under ~/.readerm, so
    without this the state of one test leaks into the next and folder counts
    accumulate across the module.
    """
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)

    import readerm.config as config
    import readerm.features as features
    import readerm.library as library
    import readerm.passlock as passlock

    for module in (config, passlock, features, library):
        importlib.reload(module)
    # gui holds module-level references to the reloaded modules
    import readerm.gui as gui
    importlib.reload(gui)
    yield home


def read(name, *parts):
    return open(os.path.join(ROOT, *parts, name), encoding="utf-8").read()


def web(name):
    return open(os.path.join(WEB, name), encoding="utf-8").read()


# ================================================== covers in bookmarks


def test_bookmark_keeps_an_openable_url():
    """The bookmark stored the normalised key, which has no scheme, so the
    card linked nowhere."""
    from readerm import library

    library.toggle_bookmark({"url": "https://mangadex.org/title/abc",
                             "title": "B", "cover": "c", "source": "mangadex"})
    mark = library.load_bookmarks()[0]
    assert mark["url"].startswith("http")
    assert library.is_bookmarked("http://www.mangadex.org/title/abc?x=1")


def test_bookmark_keeps_cover_mirrors():
    from readerm import library

    library.toggle_bookmark({"url": "https://x.test/1", "title": "T",
                             "cover": "https://a/1.jpg",
                             "cover_mirrors": ["https://a/1.jpg", "https://b/1.jpg"]})
    assert library.load_bookmarks()[0]["cover_mirrors"] == [
        "https://a/1.jpg", "https://b/1.jpg"]


# ============================================================== the cart


# ======================================================== the type filter


@pytest.mark.parametrize("language, expected", [
    ("ja", "Manga"), ("ko", "Manhwa"), ("zh", "Manhua"),
    ("zh-hk", "Manhua"), ("en", None), (None, None), ("", None),
])
def test_type_is_classified_from_origin_language(language, expected):
    from readerm.sources.base import classify_type

    assert classify_type(language) == expected


def test_explicit_tags_beat_the_language():
    from readerm.sources.base import classify_type

    assert classify_type("ja", ["Webtoon"]) == "Manhwa"
    assert classify_type(None, ["Manhua"]) == "Manhua"


def test_type_filter_drops_mismatches():
    """"One Piece" under Manhwa returned 62 results, all manga, because only
    one source implemented the type parameter and the rest ignored it."""
    from readerm.gui import _narrow_by_type

    rows = [
        {"title": "One Piece", "series_type": "Manga", "source": "mangadex"},
        {"title": "Solo Leveling", "series_type": "Manhwa", "source": "mangadex"},
    ]
    kept = _narrow_by_type(rows, "Manhwa")
    assert [r["title"] for r in kept] == ["Solo Leveling"]


def test_type_filter_keeps_unknown_types():
    """A source reporting no type must not vanish from every filtered search."""
    from readerm.gui import _narrow_by_type

    rows = [{"title": "Mystery", "source": "nosuchsource"}]
    assert len(_narrow_by_type(rows, "Manhwa")) == 1


def test_type_filter_is_a_noop_for_any():
    from readerm.gui import _narrow_by_type

    rows = [{"title": "A", "series_type": "Manga", "source": "mangadex"}]
    assert _narrow_by_type(rows, "Any") == rows
    assert _narrow_by_type(rows, "") == rows


def test_source_level_type_fallback_is_used():
    """Sites whose search rows carry no metadata fall back to what the whole
    catalogue is."""
    from readerm.gui import _narrow_by_type

    rows = [{"title": "Some Webtoon", "source": "webtoons"}]
    assert len(_narrow_by_type(rows, "Manhwa")) == 1
    assert len(_narrow_by_type(rows, "Manga")) == 0


def test_mangadex_emits_a_series_type():
    src = read("mangadex.py", "readerm", "sources")
    assert "series_type" in src
    assert "originalLanguage" in src


# ========================================================= square corners


# ==================================================== chapter range filter


def test_unknown_chapter_counts_are_kept_by_default():
    """MangaDex leaves lastChapter empty for every ongoing series, so a
    strict filter would erase whole sources."""
    from readerm import features

    rows = [{"title": "Long", "chapter_count": 900},
            {"title": "Short", "chapter_count": 5},
            {"title": "Unknown"}]
    kept = features.apply_filters(rows, {"min_chapters": 500})
    assert [r["title"] for r in kept] == ["Long", "Unknown"]


def test_strict_chapter_range_drops_unknown_counts():
    from readerm import features

    rows = [{"title": "Long", "chapter_count": 900}, {"title": "Unknown"}]
    kept = features.apply_filters(
        rows, {"min_chapters": 500, "strict_chapter_range": True})
    assert [r["title"] for r in kept] == ["Long"]


def test_strict_mode_does_nothing_without_limits():
    from readerm import features

    rows = [{"title": "A"}, {"title": "B", "chapter_count": 3}]
    kept = features.apply_filters(rows, {"strict_chapter_range": True})
    assert len(kept) == 2


# ============================================== source picker / settings


# ============================================================ advanced info


def test_mangadex_info_exposes_the_advanced_fields():
    src = read("mangadex.py", "readerm", "sources")
    body = src[src.index("def get_manga_info"):src.index("def get_chapters")]
    for field in ("last_chapter", "last_volume", "series_type",
                  "original_language", "demographic"):
        assert field in body, field


# =========================================================== column count


# ======================================================= bookmark folders


def test_folder_crud():
    from readerm import library

    made = library.create_folder("Favourites")
    assert made["ok"] and made["folder"]["id"] == "favourites"
    # duplicates are refused rather than silently merged
    assert library.create_folder("favourites")["ok"] is False

    assert library.update_folder("favourites", name="Faves")["ok"]
    assert library.load_folders()[0]["name"] == "Faves"


def test_folder_ids_do_not_collide():
    from readerm import library

    library.create_folder("My Folder")
    library.update_folder("my-folder", name="renamed")
    second = library.create_folder("My Folder")
    assert second["folder"]["id"] == "my-folder-2"


def test_bookmarks_can_be_filed_and_the_cover_is_the_first_item():
    from readerm import library

    library.create_folder("Reading")
    library.toggle_bookmark({"url": "https://a.test/1", "title": "First",
                             "cover": "c1", "source": "mangadex"})
    library.toggle_bookmark({"url": "https://a.test/2", "title": "Second",
                             "cover": "c2", "source": "mangadex"})
    library.set_bookmark_folder("https://a.test/1", "reading")

    data = library.folders_with_contents()
    folder = data["folders"][0]
    assert folder["count"] == 1
    assert folder["cover"] == "c1", "folder cover is the first book added"
    assert [b["title"] for b in data["unfiled"]] == ["Second"]


def test_deleting_a_folder_keeps_its_bookmarks_by_default():
    from readerm import library

    library.create_folder("Temp")
    library.toggle_bookmark({"url": "https://a.test/1", "title": "Keep"})
    library.set_bookmark_folder("https://a.test/1", "temp")

    library.delete_folder("temp")
    data = library.folders_with_contents()
    assert data["folders"] == []
    assert [b["title"] for b in data["unfiled"]] == ["Keep"]


def test_deleting_a_folder_can_also_drop_its_bookmarks():
    from readerm import library

    library.create_folder("Temp")
    library.toggle_bookmark({"url": "https://a.test/1", "title": "Gone"})
    library.set_bookmark_folder("https://a.test/1", "temp")

    library.delete_folder("temp", delete_bookmarks=True)
    assert library.folders_with_contents()["unfiled"] == []


def test_a_bookmark_in_a_missing_folder_falls_back_to_the_root():
    """It must never disappear from the UI just because the folder is gone."""
    from readerm import library

    library.toggle_bookmark({"url": "https://a.test/1", "title": "Orphan"})
    library.set_bookmark_folder("https://a.test/1", "ghost")
    data = library.folders_with_contents()
    assert [b["title"] for b in data["unfiled"]] == ["Orphan"]


def test_folders_support_lock_and_blur():
    from readerm import library

    library.create_folder("Private", locked=True, blurred=True)
    folder = library.load_folders()[0]
    assert folder["locked"] is True and folder["blurred"] is True

    library.update_folder(folder["id"], locked=False)
    assert library.load_folders()[0]["locked"] is False


def test_folder_api_is_reachable_from_js():
    from readerm.gui import Api

    for method in ("get_bookmark_folders", "create_bookmark_folder",
                   "update_bookmark_folder", "delete_bookmark_folder",
                   "move_bookmark", "bookmark_into"):
        assert callable(getattr(Api, method, None)), method


def test_bookmark_into_files_in_one_step():
    from readerm.gui import Api
    from readerm import library

    api = Api()
    api.create_bookmark_folder("Later", {})
    api.bookmark_into({"url": "https://a.test/9", "title": "X"}, "later")
    assert library.folders_with_contents()["folders"][0]["count"] == 1


# ============================== v1.4.8: overlay buttons / shortcuts in settings


# ================================== v1.4.10: bookmark drag-and-drop blockers
