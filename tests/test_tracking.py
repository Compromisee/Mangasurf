"""Tests for reading progress, watchlist, notes and disk maintenance."""

import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)

    import readerm.library as library
    import readerm.tracking as tracking

    for module in (tracking, library):
        importlib.reload(module)
    yield home


CHAPTERS = [{"name": f"Chapter {i}"} for i in range(1, 11)]


# ======================================================= reading progress


def test_mark_and_unmark_read():
    from readerm.tracking import mark_read, read_chapters

    mark_read("u", "Chapter 1")
    assert "Chapter 1" in read_chapters("u")
    mark_read("u", "Chapter 1", read=False)
    assert "Chapter 1" not in read_chapters("u")


def test_mark_many_and_progress():
    from readerm.tracking import mark_many, progress_for

    mark_many("u", [c["name"] for c in CHAPTERS[:4]])
    progress = progress_for("u", CHAPTERS)
    assert progress["read"] == 4
    assert progress["total"] == 10
    assert progress["percent"] == 40.0
    assert progress["unread"] == 6
    assert progress["last_read"] == "Chapter 4"


def test_next_unread():
    from readerm.tracking import mark_many, next_unread

    mark_many("u", ["Chapter 1", "Chapter 2"])
    assert next_unread("u", CHAPTERS)["name"] == "Chapter 3"


def test_next_unread_returns_none_when_finished():
    from readerm.tracking import mark_many, next_unread

    mark_many("u", [c["name"] for c in CHAPTERS])
    assert next_unread("u", CHAPTERS) is None


def test_progress_on_empty_chapter_list():
    from readerm.tracking import progress_for

    assert progress_for("u", [])["percent"] == 0.0


def test_clear_progress_for_one_series():
    from readerm.tracking import clear_progress, mark_read, read_chapters

    mark_read("a", "Chapter 1")
    mark_read("b", "Chapter 1")
    clear_progress("a")
    assert read_chapters("a") == set()
    assert read_chapters("b") == {"Chapter 1"}


def test_urls_are_normalised():
    from readerm.tracking import mark_read, read_chapters

    mark_read("https://x.test/m/1/", "Chapter 1")
    assert "Chapter 1" in read_chapters("https://x.test/m/1")


# ============================================================= watchlist


def test_watch_and_unwatch():
    from readerm.tracking import get_watchlist, is_watched, unwatch, watch

    watch("u", "Title", 100, source="mangadex")
    assert is_watched("u")
    assert get_watchlist()[0]["title"] == "Title"
    assert unwatch("u") is True
    assert not is_watched("u")


def test_record_check_reports_new_chapters():
    from readerm.tracking import get_watchlist, record_check, watch

    watch("u", "Title", 100)
    assert record_check("u", 105) == 5
    entry = get_watchlist()[0]
    assert entry["new_chapters"] == 5
    assert entry["latest_count"] == 105
    # the known count is untouched until acknowledged
    assert entry["known_chapters"] == 100


def test_record_check_ignores_shrinking_counts():
    from readerm.tracking import record_check, watch

    watch("u", "Title", 100)
    assert record_check("u", 90) == 0


def test_acknowledge_clears_the_new_flag():
    from readerm.tracking import acknowledge, get_watchlist, record_check, watch

    watch("u", "Title", 100)
    record_check("u", 110)
    acknowledge("u")
    entry = get_watchlist()[0]
    assert entry["new_chapters"] == 0
    assert entry["known_chapters"] == 110


def test_watch_preserves_the_original_added_date():
    from readerm.tracking import get_watchlist, watch

    first = watch("u", "Title", 10)["added"]
    second = watch("u", "Title", 20)["added"]
    assert first == second
    assert get_watchlist()[0]["known_chapters"] == 20


def test_record_check_on_unwatched_series_is_safe():
    from readerm.tracking import record_check

    assert record_check("missing", 10) == 0


def test_check_updates_uses_the_source_layer(monkeypatch):
    from readerm import tracking

    tracking.watch("https://mangadex.org/title/x", "Watched", 10)

    class FakeSource:
        id = "mangadex"

        def get_chapters(self, url):
            return [{"name": f"Chapter {i}"} for i in range(15)]

        def close(self):
            pass

    monkeypatch.setattr("readerm.sources.source_for_url",
                        lambda url, **kw: FakeSource())
    updates = tracking.check_updates()
    assert len(updates) == 1
    assert updates[0]["new"] == 5
    assert updates[0]["total"] == 15


def test_check_updates_skips_failing_sources(monkeypatch):
    from readerm import tracking

    tracking.watch("https://mangadex.org/title/x", "Broken", 10)

    def boom(url, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("readerm.sources.source_for_url", boom)
    assert tracking.check_updates() == []


# =========================================================== notes/ratings


def test_notes_and_ratings():
    from readerm.tracking import get_note, set_note

    set_note("u", "A good read", rating=4, tags=["fav"])
    note = get_note("u")
    assert note["note"] == "A good read"
    assert note["rating"] == 4
    assert note["tags"] == ["fav"]


def test_rating_is_clamped():
    from readerm.tracking import get_note, set_note

    set_note("a", rating=99)
    set_note("b", rating=-5)
    assert get_note("a")["rating"] == 5
    assert get_note("b")["rating"] == 0


def test_rated_listing_is_sorted():
    from readerm.tracking import rated, set_note

    set_note("a", rating=3)
    set_note("b", rating=5)
    set_note("c", rating=1)
    assert [r["rating"] for r in rated(minimum=2)] == [5, 3]


def test_missing_note_returns_a_blank_default():
    from readerm.tracking import get_note

    assert get_note("nothing")["rating"] == 0


# ======================================================= disk maintenance


def test_scan_duplicates_finds_identical_files(tmp_path):
    from readerm.tracking import scan_duplicates

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    payload = b"same-bytes" * 200
    (tmp_path / "a" / "x.jpg").write_bytes(payload)
    (tmp_path / "b" / "y.jpg").write_bytes(payload)
    (tmp_path / "a" / "z.jpg").write_bytes(b"different")

    groups = scan_duplicates(str(tmp_path))
    assert len(groups) == 1
    assert len(groups[0]["files"]) == 2
    assert groups[0]["wasted"] == len(payload)


def test_scan_duplicates_ignores_same_size_different_content(tmp_path):
    from readerm.tracking import scan_duplicates

    (tmp_path / "a.bin").write_bytes(b"A" * 100)
    (tmp_path / "b.bin").write_bytes(b"B" * 100)
    assert scan_duplicates(str(tmp_path)) == []


def test_disk_usage_sorts_largest_first(tmp_path):
    from readerm.tracking import disk_usage

    (tmp_path / "Small").mkdir()
    (tmp_path / "Big").mkdir()
    (tmp_path / "Small" / "a").write_bytes(b"x" * 100)
    (tmp_path / "Big" / "b").write_bytes(b"y" * 5000)

    rows = disk_usage(str(tmp_path))
    assert [r["name"] for r in rows] == ["Big", "Small"]
    assert rows[0]["bytes"] == 5000


def test_disk_usage_on_missing_directory():
    from readerm.tracking import disk_usage

    assert disk_usage("/definitely/not/here") == []


def test_find_orphans_detects_missing_files(tmp_path):
    from readerm import library
    from readerm.tracking import find_orphans

    library.record_chapter("https://x.test/m/1", "Gone", "Chapter 1",
                           directory=str(tmp_path / "missing"))
    library.record_outputs("https://x.test/m/1", [str(tmp_path / "nope.cbz")])

    orphans = find_orphans()
    assert len(orphans) == 1
    assert orphans[0]["title"] == "Gone"
    assert orphans[0]["directory_gone"] is True


def test_find_orphans_ignores_healthy_entries(tmp_path):
    from readerm import library
    from readerm.tracking import find_orphans

    output = tmp_path / "ok.cbz"
    output.write_bytes(b"data")
    library.record_chapter("https://x.test/m/2", "Fine", "Chapter 1",
                           directory=str(tmp_path))
    library.record_outputs("https://x.test/m/2", [str(output)])
    assert find_orphans() == []
