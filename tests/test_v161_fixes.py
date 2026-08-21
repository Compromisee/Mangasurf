"""Unit tests for Mangasurf v1.6.2 release fixes."""

import os
import tempfile
import zipfile
import pytest
from readerm.gui import Api
from readerm.covers import existing_cover
from readerm.reader.books import library_books, _resolve_entry_cover
from readerm.sources import KuraMangaSource, KuraHentaiSource


def test_archive_cover_extraction_when_missing():
    """Verify existing_cover automatically extracts page 1 from CBZ archives."""
    temp_dir = tempfile.mkdtemp(prefix="mangasurf_cbz_cover_test_")
    cbz_path = os.path.join(temp_dir, "Chapter_01.cbz")

    # Create dummy CBZ with an internal image
    with zipfile.ZipFile(cbz_path, "w") as z:
        z.writestr("01.jpg", b"fake image bytes content")

    cover = existing_cover(temp_dir)
    assert cover is not None
    assert os.path.isfile(cover)
    assert cover.endswith("cover.jpg")
    with open(cover, "rb") as f:
        assert f.read() == b"fake image bytes content"


def test_kuramanga_kurahentai_cover_needs_referer():
    """Verify KuraManga and KuraHentai have cover_needs_referer enabled."""
    km = KuraMangaSource()
    kh = KuraHentaiSource()
    assert km.cover_needs_referer is True
    assert kh.cover_needs_referer is True


def test_flaresolverr_status_api():
    """Verify flaresolverr status, test, and config methods in Gui Api."""
    api = Api()
    res = api.flaresolverr_status()
    assert res.get("ok") is True
    assert "url" in res
    assert "status" in res

    cfg_res = api.set_flaresolverr_config(url="http://localhost:8191/v1", enabled=True)
    assert cfg_res.get("ok") is True
    assert cfg_res.get("url") == "http://localhost:8191/v1"
