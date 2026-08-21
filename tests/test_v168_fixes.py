"""Comprehensive unit tests for Mangasurf v1.6.8 release fixes."""

import os
import tempfile
import pytest
from mangasurf.gui import Api
from mangasurf.sources import (
    WitchScansSource,
    KuraMangaSource,
    KuraHentaiSource,
    HiperdexSource,
    MangaKSource,
)
from mangasurf.library import record_chapter, record_outputs, load_library


def test_witchtoons_different_series_routing():
    """Verify Witchtoons get_manga_info routes to the correct distinct series titles."""
    src = WitchScansSource()
    url1 = "https://witchtoons.net/series/comic/the-ss-class-freshman-of-the-super-magic-academy"
    info1 = src.get_manga_info(url1)
    assert "Freshman" in info1["title"] or "Magic" in info1["title"]
    assert "Assassin" not in info1["title"]

    url2 = "https://witchtoons.net/series/comic/blitz-magic-scaling"
    info2 = src.get_manga_info(url2)
    assert "Blitz" in info2["title"]


def test_delete_file_never_deletes_parent_root_directory():
    """Verify delete_library_entry deletes specific series files and preserves root directories."""
    api = Api()
    root_dir = tempfile.mkdtemp(prefix="mangasurf_root_manga_")
    
    # Create two different manga files in the root folder
    manga_file1 = os.path.join(root_dir, "Solo_Leveling_01.cbz")
    manga_file2 = os.path.join(root_dir, "Berserk_01.cbz")
    with open(manga_file1, "w") as f:
        f.write("content 1")
    with open(manga_file2, "w") as f:
        f.write("content 2")

    # Set root_dir as output_dir in settings
    api.set_settings({"output_dir": root_dir})

    test_url1 = "https://mangadex.org/title/test-solo"
    record_chapter(test_url1, "Solo Leveling", "Ch 1", directory=root_dir)
    record_outputs(test_url1, [manga_file1])

    test_url2 = "https://mangadex.org/title/test-berserk"
    record_chapter(test_url2, "Berserk", "Ch 1", directory=root_dir)
    record_outputs(test_url2, [manga_file2])

    # Delete first series with delete_files=True
    res = api.delete_library_entry(test_url1, delete_files=True)
    assert res.get("ok") is True

    # VERIFY: First file is deleted, BUT root_dir and second file are 100% PRESERVED!
    assert not os.path.exists(manga_file1)
    assert os.path.isdir(root_dir)
    assert os.path.exists(manga_file2)


def test_kuramanga_multi_page_ids():
    """Verify KuraManga search returns distinct items on page 1 and page 2."""
    src = KuraMangaSource()
    res1 = src.search("magic", limit=6, page=1)
    res2 = src.search("magic", limit=6, page=2)
    assert len(res1) > 0
    assert len(res2) > 0
    assert res1[0]["title"] != res2[0]["title"]
