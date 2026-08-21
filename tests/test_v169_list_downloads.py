"""Unit tests for Mangasurf v1.6.9 list and bulk downloading."""

import pytest
from readerm.gui import Api
from readerm.sources.chikari import ChikariSource


def test_chikari_get_list_series():
    """Verify Chikari scraper extracts all series from a list URL."""
    src = ChikariSource()
    list_url = "https://chikari.moe/lists/461-my-manhwa-list"
    data = src.get_list_series(list_url)
    assert isinstance(data, dict)
    assert data.get("title") == "My Manhwa list" or "list" in data.get("title", "").lower()
    series = data.get("series", [])
    assert len(series) > 0
    assert "url" in series[0]
    assert "title" in series[0]


def test_gui_api_download_list_and_search_routing():
    """Verify Gui Api routes list URLs and bulk enqueues them."""
    api = Api()
    api.set_queue_paused(True)

    try:
        list_url = "https://chikari.moe/lists/461-my-manhwa-list"

        # Search with list URL returns is_list
        res = api.search(list_url)
        assert res.get("ok") is True
        assert res.get("is_list") is True
        assert len(res.get("results", [])) > 0

        # Download entire list
        dl_res = api.download_list(list_url)
        assert dl_res.get("ok") is True
        assert dl_res.get("enqueued", 0) > 0

        # Verify queue contains the series
        q = api.get_queue()
        assert len(q.get("items", [])) > 0
    finally:
        api.queue_clear()
        api.set_queue_paused(False)
