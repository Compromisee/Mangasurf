"""Tests for chapter-range filenames, library relocation and chapter filters."""

import importlib
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    import mangasurf.library as library
    importlib.reload(library)
    yield home


# ============================================ chapter range labels


@pytest.mark.parametrize("names,expected", [
    (["Chapter 5"], "005"),
    (["Chapter 1", "Chapter 2"], "001-002"),
    ([f"Chapter {i}" for i in range(1, 51)], "001-050"),
    (["Chapter 10", "Chapter 10.5", "Chapter 11"], "010-011"),
    ([], ""),
])
def test_chapter_range_label(names, expected):
    from mangasurf.utils import chapter_range_label

    assert chapter_range_label(names) == expected


def test_range_label_collapses_gaps_into_runs():
    from mangasurf.utils import chapter_range_label

    names = ["Chapter 1", "Chapter 2", "Chapter 3",
             "Chapter 7", "Chapter 8", "Chapter 20"]
    assert chapter_range_label(names) == "001-003, 007-008, 020"


def test_range_label_truncates_when_too_fragmented():
    """A filename must not grow unbounded for a scattered selection."""
    from mangasurf.utils import chapter_range_label

    names = [f"Chapter {i}" for i in (1, 3, 5, 7, 9, 11, 13)]
    label = chapter_range_label(names)
    assert label == "001-013 (7 chapters)"
    assert len(label) < 40


def test_range_label_is_order_independent():
    from mangasurf.utils import chapter_range_label

    forward = chapter_range_label(["Chapter 1", "Chapter 2", "Chapter 3"])
    reverse = chapter_range_label(["Chapter 3", "Chapter 1", "Chapter 2"])
    assert forward == reverse == "001-003"


def test_chapter_bounds():
    from mangasurf.utils import chapter_bounds

    assert chapter_bounds([f"Chapter {i}" for i in (4, 1, 9)]) == ("001", "009")
    assert chapter_bounds([]) == ("", "")


# ================================================ filename templates


def _packaged_names(bundle, chapter_count=6, **template_overrides):
    """Run _package with a stub packager and collect the filenames it builds."""
    from mangasurf.downloader import DownloadEngine, DownloadOptions

    options = DownloadOptions(url="https://mangakatana.com/manga/x.1",
                              bundle=bundle, **template_overrides)
    engine = DownloadEngine.__new__(DownloadEngine)
    engine.opt = options
    engine.emit = lambda *a, **k: None

    ordered = [(f"/raw/Chapter {i}", f"Chapter {i}")
               for i in range(1, chapter_count + 1)]
    built = []

    import mangasurf.downloader as downloader
    real = downloader.PACKAGERS
    downloader.PACKAGERS = {
        "cbz": lambda dirs, path, title: built.append(os.path.basename(path)) or path
    }
    try:
        engine._package("cbz", ordered, "/out", "Naruto")
    finally:
        downloader.PACKAGERS = real
    return built


def test_single_file_is_named_by_its_chapter_range():
    """Previously a "download all" CBZ was just "Naruto.cbz" -- it never said
    which chapters were inside."""
    names = _packaged_names(bundle=0, chapter_count=50)
    assert names == ["Naruto - Chapters 001-050.cbz"]


def test_bundled_files_are_named_by_their_ranges():
    names = _packaged_names(bundle=2, chapter_count=6)
    assert names == [
        "Naruto - Chapters 001-002.cbz",
        "Naruto - Chapters 003-004.cbz",
        "Naruto - Chapters 005-006.cbz",
    ]


def test_per_chapter_files_are_named_by_chapter():
    names = _packaged_names(bundle=1, chapter_count=3)
    assert names == ["Naruto - Chapter 001.cbz",
                     "Naruto - Chapter 002.cbz",
                     "Naruto - Chapter 003.cbz"]


def test_custom_template_still_wins():
    names = _packaged_names(bundle=0, chapter_count=4,
                            name_single="{title} v{start}-{end} [{count}]")
    assert names == ["Naruto v001-004 [4].cbz"]


def test_template_can_use_the_chapters_placeholder():
    names = _packaged_names(bundle=0, chapter_count=3,
                            name_single="{chapters} - {title}")
    assert names == ["001-003 - Naruto.cbz"]


def test_bad_template_falls_back_instead_of_crashing():
    names = _packaged_names(bundle=0, chapter_count=3,
                            name_single="{nonexistent_field}")
    assert names == ["Naruto - Chapters 001-003.cbz"]


def test_legacy_templates_are_migrated():
    """A stored "{title}" from an older version would otherwise keep
    overriding the improved default."""
    import mangasurf.gui as gui
    importlib.reload(gui)

    gui.save_settings({"name_single": "{title}",
                       "name_range": "{title} - Chapters {start}-{end}",
                       "output_dir": "/keep/me"})

    settings = gui.load_settings()
    assert settings["name_single"] == "{title} - Chapters {chapters}"
    assert settings["name_range"] == "{title} - Chapters {chapters}"
    assert settings["output_dir"] == "/keep/me"      # untouched


def test_migration_leaves_custom_templates_alone():
    import mangasurf.gui as gui
    importlib.reload(gui)

    gui.save_settings({"name_single": "MY OWN {title}"})
    assert gui.load_settings()["name_single"] == "MY OWN {title}"


def test_a_pre_1_4_11_settings_file_is_migrated():
    """Settings used to live in their own settings.json. On upgrade they must
    fold into config.json without losing the per-source config already there.
    """
    import json

    import mangasurf.config as appconfig
    import mangasurf.gui as gui
    importlib.reload(appconfig)
    importlib.reload(gui)

    os.makedirs(appconfig.DIR, exist_ok=True)
    with open(appconfig.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"sources": {"mangadex": {"enabled": True, "rank": 0}}}, f)
    with open(appconfig.LEGACY_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"theme": "nord", "accent": "rose",
                   "name_single": "MY OWN {title}"}, f)

    settings = gui.load_settings()
    assert settings["theme"] == "nord"
    assert settings["accent"] == "rose"
    assert settings["name_single"] == "MY OWN {title}"

    with open(appconfig.CONFIG_PATH, encoding="utf-8") as f:
        stored = json.load(f)
    assert stored["settings"]["theme"] == "nord"
    assert "mangadex" in stored["sources"], "source config must survive"


# ==================================================== relocation


def _library_with_moved_folder():
    """Record an entry, then move its folder. Returns (url, new_dir)."""
    from readerm import library

    old_root, new_root = tempfile.mkdtemp(), tempfile.mkdtemp()
    manga_dir = os.path.join(old_root, "Naruto")
    os.makedirs(manga_dir)
    output = os.path.join(manga_dir, "Naruto - Chapters 001-004.cbz")
    with open(output, "wb") as f:
        f.write(b"PK\x03\x04")

    url = "https://x.test/m/1"
    library.record_chapter(url, "Naruto", "Chapter 1", pages=10,
                           directory=manga_dir, source="mangakatana")
    library.record_outputs(url, [output])
    shutil.move(manga_dir, os.path.join(new_root, "Naruto"))
    return url, new_root


def test_verify_detects_a_moved_folder():
    from readerm import library

    _library_with_moved_folder()
    report = library.verify_entries()
    assert len(report["missing"]) == 1
    assert report["missing"][0]["directory_ok"] is False


def test_find_moved_entries_proposes_a_match():
    from readerm import library

    url, new_root = _library_with_moved_folder()
    proposals = library.find_moved_entries([new_root])
    assert len(proposals) == 1
    assert proposals[0]["url"] == url
    assert proposals[0]["new"] == os.path.join(new_root, "Naruto")


def test_find_moved_entries_writes_nothing():
    """Proposals must be inert until applied, so a wrong guess is harmless."""
    from readerm import library

    _library_with_moved_folder()
    before = library.load_library()
    library.find_moved_entries([tempfile.mkdtemp()])
    assert library.load_library() == before


def test_relocation_rewrites_directory_and_outputs():
    from readerm import library

    url, new_root = _library_with_moved_folder()
    library.apply_relocations(library.find_moved_entries([new_root]))

    entry = library.get_entry(url)
    assert entry["directory"] == os.path.join(new_root, "Naruto")
    assert os.path.isdir(entry["directory"])
    assert all(os.path.isfile(p) for p in entry["outputs"])
    assert library.verify_entries()["missing"] == []


def test_relocate_rejects_a_missing_folder():
    from readerm import library

    url, _new_root = _library_with_moved_folder()
    result = library.relocate_entry(url, "/definitely/not/here")
    assert result["ok"] is False


def test_relocate_rejects_an_unknown_url():
    from readerm import library

    result = library.relocate_entry("https://nope", tempfile.mkdtemp())
    assert result["ok"] is False
    assert "Not in library" in result["error"]


def test_relocation_keeps_chapters_and_metadata():
    """Re-linking must not lose download history."""
    from readerm import library

    url, new_root = _library_with_moved_folder()
    before = library.get_entry(url)["chapters"]
    library.apply_relocations(library.find_moved_entries([new_root]))
    after = library.get_entry(url)
    assert after["chapters"] == before
    assert after["title"] == "Naruto"
    assert after["source"] == "mangakatana"


def test_healthy_entries_are_not_proposed():
    from readerm import library

    root = tempfile.mkdtemp()
    manga_dir = os.path.join(root, "Bleach")
    os.makedirs(manga_dir)
    library.record_chapter("https://x.test/m/2", "Bleach", "Chapter 1",
                           directory=manga_dir)
    assert library.find_moved_entries([root]) == []


def test_rescan_updates_the_output_dir_setting():
    import mangasurf.gui as gui
    importlib.reload(gui)

    url, new_root = _library_with_moved_folder()
    api = gui.Api()
    result = api.rescan_output_dir(new_root)
    assert result["ok"] is True
    assert result["relocated"] == 1
    assert result["still_missing"] == 0
    assert gui.load_settings()["output_dir"] == new_root


# ============================================ chapter min/max UI


def read(path):
    return open(path, encoding="utf-8").read()
