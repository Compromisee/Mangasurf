"""Unit tests for Mangasurf v1.6.3 quick fixes."""

import pytest
from readerm.sources import (
    get_source,
    ChikariSource,
    KuraMangaSource,
    KuraHentaiSource,
    HiperdexSource,
    MadaraDexSource,
    MangaKSource,
)


def test_madaradex_title_cleaning():
    """Item 4: MadaraDex titles are clean series names without 18+ badge."""
    src = MadaraDexSource()
    res = src.browse(limit=5)
    assert len(res) > 0
    for r in res:
        assert not r["title"].startswith("18+ ")
        assert not r["title"].startswith("18+Uncensored")
        assert len(r["title"]) > 1


def test_hiperdex_multi_page_chapter_images():
    """Item 3: Hiperdex extracts all pages for a chapter."""
    src = HiperdexSource()
    res = src.browse(limit=1)
    if res:
        chapters = src.get_chapters(res[0]["url"])
        assert len(chapters) > 0
        pages = src.get_chapter_images(chapters[0])
        assert isinstance(pages, list)
        assert len(pages) > 1, "Hiperdex must return multiple chapter pages"


def test_mangak_browse_and_chapters():
    """Item 5: MangaK browse, search, and chapters extraction."""
    src = MangaKSource()
    b_res = src.browse(limit=3)
    assert len(b_res) > 0

    s_res = src.search("rebirth", limit=3)
    assert len(s_res) > 0
    chapters = src.get_chapters(s_res[0]["url"])
    assert len(chapters) > 0


def test_kuramanga_and_hiperdex_covers_proxy():
    """Item 1: KuraManga and Hiperdex have cover_needs_referer enabled."""
    km = KuraMangaSource()
    hd = HiperdexSource()
    assert km.cover_needs_referer is True
    assert hd.cover_needs_referer is True
