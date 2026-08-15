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


def test_source_reorder():
    sources = appconfig.ranked_ids(include_disabled=True)
    new_order = list(reversed(sources))
    appconfig.reorder(new_order)
    assert appconfig.ranked_ids(include_disabled=True) == new_order
    appconfig.reset_config()
