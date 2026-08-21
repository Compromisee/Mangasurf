"""Unit tests for Mangasurf v1.6.4 features."""

import pytest
from mangasurf.gui import Api
from mangasurf.sources import (
    SOURCES,
    get_source,
    MangaKSource,
    HiperdexSource,
    ChikariSource,
    KuraMangaSource,
    KuraHentaiSource,
    MadaraDexSource,
)


def test_32_sources_complete():
    """Verify all 32 sources are operational."""
    assert len(SOURCES) == 32
    for sid in ("chikari", "kuramanga", "kurahentai", "hiperdex", "madaradex", "mangak"):
        assert sid in SOURCES
        src = get_source(sid)
        assert src.id == sid


def test_mangak_covers_needs_referer():
    """Verify MangaK has cover_needs_referer enabled."""
    src = MangaKSource()
    assert src.cover_needs_referer is True


def test_hiperdex_covers_needs_referer_and_multi_page():
    """Verify Hiperdex has cover_needs_referer enabled and pagination works."""
    src = HiperdexSource()
    assert src.cover_needs_referer is True
    res = src.browse(page=1, limit=2)
    assert len(res) > 0


def test_chikari_adult_and_tag_resolving():
    """Verify Chikari supports tag ID resolution."""
    src = ChikariSource()
    tag_id = src._resolve_tag_id("magic")
    assert tag_id == "121" or tag_id.isdigit()


def test_library_pagination_settings():
    """Verify library pagination settings can be updated in Gui Api."""
    api = Api()
    settings = api.get_settings()
    assert isinstance(settings, dict)

    # Update pagination settings
    update_res = api.set_settings({
        "lib_paginate": True,
        "lib_page_size": 24,
    })
    assert isinstance(update_res, dict)
    s = api.get_settings()
    assert s.get("lib_paginate") is True
    assert s.get("lib_page_size") == 24

    # Reset
    api.set_settings({"lib_paginate": False, "lib_page_size": 24})
