"""Unit tests for Mangasurf v1.6.5 comprehensive fixes."""

import os
import tempfile
import zipfile
import pytest
from mangasurf.gui import Api
from mangasurf.sources import (
    get_source,
    ChikariSource,
    KuraMangaSource,
    KuraHentaiSource,
    HiperdexSource,
    MangaKSource,
)
from mangasurf.library import scan_library_folders, load_library


def test_scan_external_series_folder_with_archives():
    """Verify scan_library_folders correctly discovers and indexes a single series folder."""
    temp_dir = tempfile.mkdtemp(prefix="mangasurf_external_manga_")
    series_dir = os.path.join(temp_dir, "Custom Series Alpha")
    os.makedirs(series_dir, exist_ok=True)

    cbz1 = os.path.join(series_dir, "Chapter 01.cbz")
    cbz2 = os.path.join(series_dir, "Chapter 02.cbz")
    with zipfile.ZipFile(cbz1, "w") as z:
        z.writestr("01.jpg", b"fake image 1")
    with zipfile.ZipFile(cbz2, "w") as z:
        z.writestr("01.jpg", b"fake image 2")

    res = scan_library_folders([series_dir])
    assert res.get("ok") is True
    assert res.get("discovered") >= 1

    lib = load_library()
    found = any("Custom Series Alpha" in v.get("title", "") for v in lib.values())
    assert found is True


def test_all_cdn_covers_proxy_successfully():
    """Verify all CDN covers proxy via Api.proxy_cover with data URIs."""
    api = Api()
    cdn_urls = [
        "https://shadowabyss.com/manhwa/dungeonodyssey/cover/cover.webp",
        "https://hentai.shadowabyss.com/hentai/27290/cover/cover.webp",
        "https://cloud-7.r2d2storage.com/2025/03/Wireless-Onahole.jpg",
        "https://rx.resmk.org/covers/6cf075bd55c8.webp",
    ]
    for u in cdn_urls:
        res = api.proxy_cover(u)
        assert res.get("ok") is True, f"Failed proxying {u}: {res.get('error')}"
        assert res.get("data", "").startswith("data:image/")


def test_hiperdex_browse_multi_page():
    """Verify Hiperdex browse supports page 2+ pagination."""
    src = HiperdexSource()
    res1 = src.browse(page=1, limit=2)
    res2 = src.browse(page=2, limit=2)
    assert len(res1) > 0
    assert len(res2) > 0


def test_chikari_custom_tags_resolution():
    """Verify Chikari resolves custom tags to tag IDs."""
    src = ChikariSource()
    tag_id = src._resolve_tag_id("male lead")
    assert tag_id == "58" or tag_id.isdigit()
