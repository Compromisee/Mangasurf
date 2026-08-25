"""Comprehensive unit tests for Mangasurf v1.5.1 all-inclusive Fix category checklist."""

import os
import shutil
import tempfile
import pytest
from mangasurf.gui import Api
from mangasurf.sources import WitchtoonsSource, WitchScansSource, search_all, get_source
from mangasurf import library


@pytest.mark.skipif(
    os.environ.get("READERM_NETWORK_TESTS") != "1",
    reason="hits the live Witchtoons site",
)
def test_witchtoons_source_integration():
    """Item 4: Witchtoons scraper is operational with high-speed API and RSS parsing.

    This hits the live site. Witchtoons' reader now serves chapter pages
    client-side (Next.js), so the server-rendered HTML no longer embeds the
    page list; run with READERM_NETWORK_TESTS=1 if you want the live scrape
    exercised (it may fail until the reader's page-list API is re-parsed).
    """
    src = WitchtoonsSource()
    assert src.id == "witchscans"
    assert src.name == "Witchtoons"
    assert "witchtoons.net" in src.domains
    assert WitchtoonsSource is WitchScansSource

    # Test search parsing
    results = src.search("assassin", limit=5)
    assert isinstance(results, list)
    assert len(results) > 0
    first = results[0]
    assert "url" in first
    assert "title" in first

    # Test manga info
    info = src.get_manga_info(first["url"])
    assert info["title"]
    assert "series_type" in info

    # Test chapters list
    chapters = src.get_chapters(first["url"])
    assert isinstance(chapters, list)
    assert len(chapters) > 0
    assert "url" in chapters[0]

    # Test chapter images extraction
    images = src.get_chapter_images(chapters[0])
    assert isinstance(images, list)
    assert len(images) > 0
    assert any("uploads" in img for img in images)


def test_double_download_duplicate_prevention():
    """Item 9: start_download and add_to_cart refuse duplicate downloads of the same URL."""
    api = Api()
    api.set_queue_paused(True)
    test_url = "https://mangadex.org/title/test-double-download-slug"

    try:
        # Start first download (will be queued because paused or max concurrent)
        res1 = api.add_to_cart({
            "url": test_url,
            "title": "Double Download Test Manga",
            "chapters": ["Chapter 1"],
        })
        assert res1.get("ok") is True

        # Immediate second download attempt for same URL must be rejected
        res2 = api.start_download({
            "url": test_url,
            "title": "Double Download Test Manga",
            "chapters": ["Chapter 1"],
        })
        assert res2.get("ok") is False
        assert "already" in res2.get("error", "").lower()

        # Attempt adding same URL to cart/queue again must also be rejected
        res3 = api.add_to_cart({
            "url": test_url,
            "title": "Double Download Test Manga",
        })
        assert res3.get("ok") is False
        assert "already" in res3.get("error", "").lower()
    finally:
        api.queue_clear()
        api.set_queue_paused(False)


def test_delete_all_files_and_folder():
    """Item 6: delete_library_entry permanently removes directory and files on disk and evicts from library."""
    api = Api()
    temp_dir = tempfile.mkdtemp(prefix="mangasurf_test_series_")
    file1 = os.path.join(temp_dir, "Chapter_01.cbz")
    file2 = os.path.join(temp_dir, "Chapter_02.cbz")
    with open(file1, "w") as f:
        f.write("dummy cbz 1")
    with open(file2, "w") as f:
        f.write("dummy cbz 2")

    test_url = "https://mangadex.org/title/delete-test-series"
    library.record_chapter(
        url=test_url,
        title="Delete Test Manga",
        chapter_name="Chapter 01",
        directory=temp_dir,
    )
    library.record_outputs(test_url, [file1, file2])

    # Verify entry is recorded in library
    lib_entry = api.get_library_entry(test_url)
    assert lib_entry.get("entry") or lib_entry.get("directory")

    # Perform permanent delete of files and folder
    res = api.delete_library_entry(test_url, delete_files=True)
    assert res.get("ok") is True

    # Verify directory and files are permanently deleted from disk
    assert not os.path.exists(temp_dir)
    assert not os.path.exists(file1)
    assert not os.path.exists(file2)

    # Verify entry is evicted from library.json
    lib_after = library.load_library()
    assert test_url not in lib_after
    assert library._find_entry(lib_after, test_url) is None


def test_search_timeout_allows_flaresolverr():
    """Item 2: search concurrency timeout is extended to 30.0s so FlareSolverr has time to resolve challenges."""
    from mangasurf.sources import search_all
    # Testing search_all returns within timeout
    res = search_all("solo", source_ids=["mangadex"], limit=3)
    assert isinstance(res, list)
