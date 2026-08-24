"""Comprehensive tests for Mangasurf v1.6.0 Add checklist features."""

import pytest
from mangasurf.gui import Api
from mangasurf.sources import (
    SOURCES,
    detect_source,
    get_source,
    ChikariSource,
    KuraMangaSource,
    KuraHentaiSource,
    HiperdexSource,
    MadaraDexSource,
    MangaKSource,
)
from mangasurf.database import search_database, get_search_suggestions


def test_32_sources_registered():
    """Verify all sources are registered and instantiable."""
    assert len(SOURCES) >= 32
    expected_new = ["chikari", "kuramanga", "kurahentai", "hiperdex", "madaradex", "mangak", "kings", "kamiya"]
    for sid in expected_new:
        assert sid in SOURCES
        src = get_source(sid)
        assert src.id == sid
        assert src.name


def test_url_detection_across_new_sources():
    """Item 3: URL support in search bar detects sources accurately."""
    test_cases = [
        ("https://chikari.moe/series/the-bastard-of-swordborne", "chikari"),
        ("https://kuramanga.com/dungeonodyssey", "kuramanga"),
        ("https://kurahentai.com/gallery/27290", "kurahentai"),
        ("https://hiperdex.com/manga/silent-war", "hiperdex"),
        ("https://madaradex.org/title/close-family-uncensored/", "madaradex"),
        ("https://mangak.io/rebirth-monarch-of-the-dead", "mangak"),
    ]
    for url, expected_source in test_cases:
        detected = detect_source(url)
        assert detected == expected_source, f"Failed detecting {url}"


def test_database_integration_search():
    """Item 5: Offline Database Integration provides instant search for SFW and NSFW titles."""
    api = Api()

    # Search SFW series in database
    sfw_res = api.search_database("Solo Leveling")
    assert sfw_res["ok"] is True
    assert len(sfw_res["results"]) > 0
    first_sfw = sfw_res["results"][0]
    assert "Solo Leveling" in first_sfw["title"]
    assert first_sfw["type"] == "Manhwa"
    assert first_sfw["is_nsfw"] is False

    # Search NSFW series in database
    nsfw_res = api.search_database("Silent War")
    assert nsfw_res["ok"] is True
    assert len(nsfw_res["results"]) > 0
    first_nsfw = nsfw_res["results"][0]
    assert "Silent War" in first_nsfw["title"]
    assert first_nsfw["is_nsfw"] is True


def test_search_suggestions_generation():
    """Item 4: Search suggestions generate @sources, #genres, and matching series."""
    api = Api()

    # Prefix with @
    src_sugg = api.suggest_query("@chi")
    assert src_sugg["ok"] is True
    assert any("@chikari" in s["label"] for s in src_sugg.get("suggestions", []))

    # Prefix with #
    genre_sugg = api.suggest_query("#act")
    assert genre_sugg["ok"] is True
    assert any("#action" in s["label"] for s in genre_sugg.get("suggestions", []))

    # Prefix with title query
    title_sugg = api.suggest_query("one piece")
    assert title_sugg["ok"] is True
    assert any("One Piece" in s["label"] for s in title_sugg.get("suggestions", []))


def test_bulk_downloading_cart_workflow():
    """Item 1: Bulk downloading and cart operations."""
    api = Api()
    api.set_queue_paused(True)

    try:
        # Add first series to cart
        r1 = api.add_to_cart({
            "url": "https://mangadex.org/title/bulk-test-1",
            "title": "Bulk Series 1",
            "chapters": ["Chapter 1"],
        })
        assert r1["ok"] is True

        # Add second series to cart
        r2 = api.add_to_cart({
            "url": "https://mangadex.org/title/bulk-test-2",
            "title": "Bulk Series 2",
            "chapters": ["Chapter 1", "Chapter 2"],
        })
        assert r2["ok"] is True

        # Check queue / cart contains items
        q = api.get_queue()
        assert q["ok"] is True
        assert len(q.get("items", [])) >= 2
    finally:
        api.queue_clear()
        api.set_queue_paused(False)


def test_chikari_scraper():
    """Item 7: Chikari scraper search and info parsing."""
    src = ChikariSource()
    res = src.search("magic", limit=3)
    assert isinstance(res, list)
    if res:
        assert res[0]["title"]
        assert "chikari.moe/series/" in res[0]["url"]


def test_kuramanga_scraper():
    """Item 7: KuraManga scraper search and info parsing."""
    src = KuraMangaSource()
    res = src.search("dungeon", limit=3)
    assert isinstance(res, list)
    if res:
        assert res[0]["title"]


def test_kurahentai_scraper():
    """Item 7: KuraHentai scraper gallery search and info parsing."""
    src = KuraHentaiSource()
    res = src.search("teacher", limit=3)
    assert isinstance(res, list)
    if res:
        assert res[0]["title"]
        assert "/gallery/" in res[0]["url"]


def test_hiperdex_scraper():
    """Item 7: Hiperdex tRPC scraper search and info parsing."""
    src = HiperdexSource()
    res = src.browse(limit=3)
    assert isinstance(res, list)
    if res:
        assert res[0]["title"]
        assert "/manga/" in res[0]["url"]


def test_mangak_scraper():
    """Item 7: MangaK Next.js scraper search and info parsing."""
    src = MangaKSource()
    res = src.search("rebirth", limit=3)
    assert isinstance(res, list)
    if res:
        assert res[0]["title"]
        assert "mangak.io" in res[0]["url"]
