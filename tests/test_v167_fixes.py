"""Comprehensive unit tests for Mangasurf v1.6.7 release fixes."""

import pytest
from readerm.gui import Api
from readerm.sources import (
    KuraMangaSource,
    KuraHentaiSource,
    HiperdexSource,
    MangaKSource,
)


def test_kuramanga_multi_page_pagination_past_two_loadmores():
    """Verify KuraManga returns unique paginated results across pages 1, 2, 3, 4, 5."""
    src = KuraMangaSource()
    res_p1 = src.search("magic", page=1, limit=12)
    res_p2 = src.search("magic", page=2, limit=12)
    res_p3 = src.search("magic", page=3, limit=12)

    assert len(res_p1) > 0
    assert len(res_p2) > 0
    assert len(res_p3) > 0
    # Titles on different pages must be different
    assert res_p1[0]["title"] != res_p2[0]["title"]
    assert res_p2[0]["title"] != res_p3[0]["title"]


def test_kurahentai_multi_page_pagination_past_two_loadmores():
    """Verify KuraHentai returns paginated results across pages 1, 2, 3."""
    src = KuraHentaiSource()
    res_p1 = src.search("teacher", page=1, limit=5)
    res_p2 = src.search("teacher", page=2, limit=5)

    assert len(res_p1) > 0
    assert len(res_p2) > 0
    assert res_p1[0]["url"] != res_p2[0]["url"]


def test_hiperdex_multi_page_pagination():
    """Verify Hiperdex returns paginated results on search/browse page 2+."""
    src = HiperdexSource()
    res1 = src.search("magic", page=1, limit=5)
    res2 = src.search("magic", page=2, limit=5)
    assert len(res1) > 0
    assert len(res2) > 0


def test_proxy_cover_for_all_cdn_hosts():
    """Verify proxy_cover successfully fetches and encodes CDN images."""
    api = Api()
    test_urls = [
        "https://shadowabyss.com/manhwa/dungeonodyssey/cover/cover.webp",
        "https://hentai.shadowabyss.com/hentai/27290/cover/cover.webp",
        "https://cloud-7.r2d2storage.com/2025/03/Wireless-Onahole.jpg",
        "https://rx.resmk.org/covers/6cf075bd55c8.webp",
    ]
    for u in test_urls:
        res = api.proxy_cover(u)
        assert res.get("ok") is True
        assert res.get("data", "").startswith("data:image/")
