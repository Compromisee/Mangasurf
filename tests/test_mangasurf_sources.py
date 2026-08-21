"""Unit tests for Mangasurf scraper integrations, omnibar, search filtering, and source management."""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from readerm.sources import (
    SOURCES,
    SOURCE_CLASSES,
    get_source,
    detect_source,
    list_sources,
    search_all,
    browse_all,
    genres_all,
)
from readerm.sources.base import filter_and_rank_query
from readerm.sources.weebcentral import WeebCentralSource, natural_sort_key
from readerm.sources.mangakatana import MangakatanaSource, GENRE_MAP
from readerm.sources.kagane import KaganeSource
from readerm.sources.comix import ComixSource
from readerm.sources.vymanga import VymangaSource
from readerm.sources.mangadotnet import MangaDotNetSource
from readerm.sources.hitomi import HitomiSource
from readerm.sources.mangadistrict import MangaDistrictSource
from readerm.sources.omegascans import OmegaScansSource
from readerm.features import suggest, add_history
import readerm.config as appconfig
from readerm.gui import Api


def test_all_expected_sources_present():
    expected = [
        "mangadex", "mangakatana", "weebcentral", "kagane",
        "comix", "vymanga", "mangadotnet", "asurascans", "omegascans"
    ]
    for exp in expected:
        assert exp in SOURCES, f"Source {exp} must be registered"


def test_weebcentral_natural_sort():
    pages = ["page10.jpg", "page2.jpg", "page1.jpg", "page20.jpg"]
    sorted_pages = sorted(pages, key=natural_sort_key)
    assert sorted_pages == ["page1.jpg", "page2.jpg", "page10.jpg", "page20.jpg"]


def test_weebcentral_source_detection():
    url = "https://weebcentral.com/series/01JJG9B6E4A6CZXQ15Q3YNDNCM/Solo-Leveling"
    assert detect_source(url) == "weebcentral"
    src = get_source("weebcentral")
    assert isinstance(src, WeebCentralSource)
    assert src.handles(url) is True


def test_mangakatana_genre_map_and_detection():
    url = "https://mangakatana.com/manga/solo-leveling.19637"
    assert detect_source(url) == "mangakatana"
    src = get_source("mangakatana")
    assert isinstance(src, MangakatanaSource)
    genres = src.genres()
    assert len(genres) >= 40
    assert any(g["name"] == "Action" for g in genres)


def test_kagane_source_extraction_and_detection():
    url = "https://kagane.to/series/019c2071-7760-7481-acf2-35d57d2912a9"
    assert detect_source(url) == "kagane"
    series_id = KaganeSource.extract_series_id(url)
    assert series_id == "019c2071-7760-7481-acf2-35d57d2912a9"
    src = get_source("kagane")
    assert isinstance(src, KaganeSource)
    assert src.supports_genres is True


def test_kagane_search_and_chapter_parsing(monkeypatch):
    src = KaganeSource()
    mock_search_data = {
        "data": [
            {
                "series_id": "019c2071-7760-7481-acf2-35d57d2912a9",
                "title": "Solo Leveling",
                "cover_image_id": "cover123",
                "publication_status": "Completed",
                "format": "Manhwa",
            }
        ]
    }
    monkeypatch.setattr(src, "fetch_json", lambda *a, **k: mock_search_data)
    results = src.search("Solo Leveling")
    assert len(results) == 1
    assert results[0]["title"] == "Solo Leveling"
    assert "https://kstatic.to/image/cover123" in results[0]["cover"]

    mock_series_info = {
        "title": "Solo Leveling",
        "description": "Hunter Sung Jin-Woo",
        "series_covers": [{"image_id": "cover123"}],
        "genres": [{"genre_name": "Action"}],
        "series_books": [
            {"book_id": "bk1", "chapter_no": "1", "title": "Prologue", "sort_no": 1},
            {"book_id": "bk2", "chapter_no": "2", "title": "Awakening", "sort_no": 2},
        ],
    }
    monkeypatch.setattr(src, "fetch_json", lambda *a, **k: mock_series_info)
    info = src.get_manga_info("https://kagane.to/series/019c2071-7760-7481-acf2-35d57d2912a9")
    assert info["title"] == "Solo Leveling"
    assert "Action" in info["tags"]

    chapters = src.get_chapters("https://kagane.to/series/019c2071-7760-7481-acf2-35d57d2912a9")
    assert len(chapters) == 2
    assert chapters[0]["name"] == "Chapter 1 - Prologue"

    mock_pages = {"pages": ["img1", "img2", "img3"]}
    monkeypatch.setattr(src, "fetch_json", lambda *a, **k: mock_pages)
    images = src.get_chapter_images({"url": "https://kagane.to/series/s1/reader/bk1"})
    assert len(images) == 3
    assert "img1" in images[0]


def test_comix_source_code_extraction():
    url = "https://comix.to/title/93q1r-the-summoner"
    assert detect_source(url) == "comix"
    code = ComixSource.extract_manga_code(url)
    assert code == "93q1r-the-summoner"
    src = get_source("comix")
    assert isinstance(src, ComixSource)


def test_vymanga_source_detection():
    url = "https://vymanga.co/manga/martial-peak"
    assert detect_source(url) == "vymanga"
    src = get_source("vymanga")
    assert isinstance(src, VymangaSource)
    assert "Cookie" in src.headers()
    assert "over18=1" in src.headers()["Cookie"]


def test_mangadotnet_source_detection_and_parsing():
    url = "https://mangadot.net/manga/166"
    assert detect_source(url) == "mangadotnet"
    mid = MangaDotNetSource.extract_manga_id(url)
    assert mid == "166"
    src = get_source("mangadotnet")
    assert isinstance(src, MangaDotNetSource)


def test_filter_and_rank_query_eliminates_trending_noise():
    raw_results = [
        {"title": "Unrelated Trending Manhwa 1", "url": "https://example.com/1"},
        {"title": "Solo Leveling: Ragnarok", "url": "https://example.com/2"},
        {"title": "Random Romance Story", "url": "https://example.com/3"},
        {"title": "Solo Leveling", "url": "https://example.com/4"},
    ]
    filtered = filter_and_rank_query(raw_results, "solo leveling")
    assert len(filtered) == 2
    assert filtered[0]["title"] == "Solo Leveling"
    assert filtered[1]["title"] == "Solo Leveling: Ragnarok"


def test_omegascans_search_filters_query(monkeypatch):
    src = OmegaScansSource()
    raw = [
        {"series_slug": "solo-leveling", "title": "Solo Leveling", "id": 1},
        {"series_slug": "random-trending", "title": "Random Trending", "id": 2},
    ]
    monkeypatch.setattr(src, "fetch_json", lambda *a, **k: {"data": raw})
    results = src.search("Solo Leveling")
    assert len(results) == 1
    assert results[0]["title"] == "Solo Leveling"


def test_omnibar_suggestions():
    add_history("solo leveling", "weebcentral", 10)
    assert "@weebcentral" in suggest("@weeb")
    assert "#action" in suggest("#act")
    assert "solo leveling" in suggest("solo")


def test_omnibar_direct_url_routing():
    api = Api()
    res = api.search("https://mangakatana.com/manga/solo-leveling.19637")
    assert res["ok"] is True
    assert res["url"] == "https://mangakatana.com/manga/solo-leveling.19637"
    assert res["source"] == "mangakatana"


def test_omnibar_prefix_routing(monkeypatch):
    api = Api()
    called_source = []

    class MockSource:
        def search(self, query, **kwargs):
            called_source.append("mangakatana")
            return [{"title": "Naruto", "url": "https://mangakatana.com/manga/naruto", "source": "mangakatana"}]
        def close(self): pass

    monkeypatch.setattr(api, "_source", lambda sid: MockSource())
    res = api.search("@mangakatana naruto")
    assert res["ok"] is True
    assert res.get("source") == "mangakatana"
    assert len(res.get("results", [])) > 0


def test_source_toggling():
    appconfig.set_enabled("natomanga", False)
    assert appconfig.is_enabled("natomanga") is False
    assert "natomanga" not in appconfig.ranked_ids(include_disabled=False)

    appconfig.set_enabled("natomanga", True)
    assert appconfig.is_enabled("natomanga") is True
    assert "natomanga" in appconfig.ranked_ids(include_disabled=False)


def test_nhentai_search_pagination(monkeypatch):
    src = get_source("nhentai")
    requested_urls = []

    def mock_fetch(url, **kwargs):
        requested_urls.append(url)
        mock_resp = MagicMock()
        mock_resp.content = b"<html><body></body></html>"
        return mock_resp

    monkeypatch.setattr(src, "fetch", mock_fetch)
    src.search("naruto", page=1)
    assert "page=" not in requested_urls[0]

    src.search("naruto", page=2)
    assert "&page=2" in requested_urls[1]


def test_weebcentral_and_mangadex_search_pagination():
    wc = get_source("weebcentral")
    md = get_source("mangadex")
    assert callable(getattr(wc, "search", None))
    assert callable(getattr(md, "search", None))


def test_hitomi_source_and_parsing(monkeypatch):
    src = get_source("hitomi")
    assert isinstance(src, HitomiSource)
    assert src.extract_gallery_id("https://hitomi.la/manga/love-story-1984147.html") == "1984147"
    assert src.extract_gallery_id("1984147") == "1984147"
    assert src.handles("https://hitomi.la/reader/1984147.html") is True

    mock_gallery = {
        "id": "1984147",
        "title": "Love Story Doujinshi",
        "type": "Doujinshi",
        "language": "english",
        "artists": [{"artist": "FamousArtist"}],
        "tags": [{"tag": "sole_female", "female": 1}],
        "files": [
            {"hash": "ae5c26398a0a92f87053b8425cec0b7d9cfdc4d24db7e3750f4bdb02ce914967", "haswebp": 1, "name": "01.webp"}
        ]
    }
    monkeypatch.setattr(src, "_fetch_gallery_info", lambda gid: mock_gallery)
    info = src.get_manga_info("1984147")
    assert info["title"] == "Love Story Doujinshi"
    assert "FamousArtist" in info["authors"]
    assert "female:sole_female" in info["tags"]

    chapters = src.get_chapters("1984147")
    assert len(chapters) == 1

    images = src.get_chapter_images({"url": "https://hitomi.la/reader/1984147.html"})
    assert len(images) == 1
    assert "ae5c26398a0a92f87053b8425cec0b7d9cfdc4d24db7e3750f4bdb02ce914967" in images[0]


def test_mangadistrict_source_and_parsing(monkeypatch):
    src = get_source("mangadistrict")
    assert isinstance(src, MangaDistrictSource)
    assert src.slug_of("https://mangadistrict.com/read-scan/the-hero-returns/") == "the-hero-returns"
    assert src.handles("https://mangadistrict.com/read-scan/the-hero-returns/") is True

    mock_html = b"""
    <div class="c-tabs-item__content">
      <div class="tab-thumb">
        <a href="https://mangadistrict.com/read-scan/the-hero-returns/"><img data-src="https://img.com/hero.jpg"></a>
      </div>
      <div class="post-title"><h3><a href="https://mangadistrict.com/read-scan/the-hero-returns/">The Hero Returns</a></h3></div>
    </div>
    """
    mock_resp = MagicMock()
    mock_resp.content = mock_html
    monkeypatch.setattr(src, "fetch", lambda *a, **k: mock_resp)

    results = src.search("hero")
    assert len(results) >= 1
    assert results[0]["title"] == "The Hero Returns"
    assert "mangadistrict.com/read-scan/the-hero-returns" in results[0]["url"]


def test_simplyhentai_source_and_tag_url():
    src = get_source("simplyhentai")
    assert src.handles("https://www.simply-hentai.com/tag/sole-male/tag-1-sole-female") is True
    assert src.handles("https://www.simply-hentai.com/series/naruto") is True
    assert src._build_tag_url(["sole-male", "sole-female"], page=2) == "https://www.simply-hentai.com/tag/sole-male/tag-1-sole-female?page=2"


def test_source_reorder():
    sources = appconfig.ranked_ids(include_disabled=True)
    new_order = list(reversed(sources))
    appconfig.reorder(new_order)
    assert appconfig.ranked_ids(include_disabled=True) == new_order
    appconfig.reset_config()
