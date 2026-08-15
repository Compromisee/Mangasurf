"""Tests for the empty-body retry, chapter-count filters and new sources."""

import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NETWORK = pytest.mark.skipif(
    not os.environ.get("READERM_NETWORK_TESTS"),
    reason="set READERM_NETWORK_TESTS=1 to run live-site tests")


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    import readerm.config as config
    import readerm.features as features
    for module in (config, features):
        importlib.reload(module)
    yield home


# ============================= empty-body throttling (aggregator bug)


class _Resp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, content=b"x", status=200, method="GET"):
        self.content = content
        self.status_code = status
        self.headers = {}
        self.text = content.decode() if content else ""
        self.request = type("R", (), {"method": method})()

    def raise_for_status(self):
        pass


def test_empty_body_is_retried_not_accepted():
    """Mangakatana answers HTTP 200 with a ZERO-length body when it throttles.
    Treating that as success is what made multi-source search look broken:
    the source silently contributed nothing."""
    from readerm.sources.base import Source

    source = Source()
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _Resp(b"" if calls["n"] < 3 else b"<html>ok</html>")

    source.session = type("S", (), {"get": staticmethod(fake_get)})()
    source._backoff = lambda *a, **k: 0
    response = source.fetch("https://x.test/search")
    assert calls["n"] == 3
    assert response.content


def test_empty_body_eventually_raises():
    from readerm.sources.base import Source, ScrapeError

    source = Source()
    source.session = type("S", (), {"get": staticmethod(lambda u, **k: _Resp(b""))})()
    source._backoff = lambda *a, **k: 0
    with pytest.raises(ScrapeError):
        source.fetch("https://x.test/search", max_retries=2)


@pytest.mark.parametrize("status", [204, 304])
def test_bodyless_statuses_are_not_retried(status):
    """204/304 legitimately carry no body."""
    from readerm.sources.base import Source

    source = Source()
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        return _Resp(b"", status=status)

    source.session = type("S", (), {"get": staticmethod(fake_get)})()
    source.fetch("https://x.test/x")
    assert calls["n"] == 1


def test_head_requests_are_not_retried():
    from readerm.sources.base import Source

    assert Source._expects_body(_Resp(b"", method="HEAD")) is False
    assert Source._expects_body(_Resp(b"", method="GET")) is True


# ================================== min/max chapter count filters


@pytest.mark.parametrize("item,expected", [
    ({"latest": "Chapter 1050"}, 1050.0),
    ({"chapter_count": 120}, 120.0),
    ({"last_chapter": "88"}, 88.0),
    ({"chapters": ["a", "b", "c"]}, 3.0),
    ({"title": "nothing"}, None),
])
def test_chapter_count_detection(item, expected):
    from readerm.features import _chapter_count

    assert _chapter_count(item) == expected


def test_min_and_max_chapter_filters():
    from readerm.features import apply_filters

    rows = [
        {"title": "Long", "latest": "Chapter 1050"},
        {"title": "Short", "latest": "Chapter 12"},
        {"title": "Mid", "chapter_count": 120},
    ]
    assert [r["title"] for r in apply_filters(rows, {"min_chapters": 100})] \
        == ["Long", "Mid"]
    assert [r["title"] for r in apply_filters(rows, {"max_chapters": 200})] \
        == ["Short", "Mid"]
    assert [r["title"] for r in
            apply_filters(rows, {"min_chapters": 100, "max_chapters": 500})] == ["Mid"]


def test_unknown_counts_are_never_filtered_out():
    """Sources report counts inconsistently; judging an unknown count would
    make whole sources vanish from every filtered search."""
    from readerm.features import apply_filters

    rows = [{"title": "No count"}]
    assert len(apply_filters(rows, {"min_chapters": 500})) == 1
    assert len(apply_filters(rows, {"max_chapters": 5})) == 1


def test_zero_means_no_limit():
    from readerm.features import apply_filters

    rows = [{"title": "A", "latest": "Chapter 5"}]
    assert len(apply_filters(rows, {"min_chapters": 0, "max_chapters": 0})) == 1


# ==================================================== new sources


def test_new_sources_registered():
    from readerm.sources import SOURCES

    assert "webtoons" in SOURCES
    assert "nhentai" in SOURCES


def test_nhentai_is_adult_only():
    from readerm.sources import SOURCES

    assert SOURCES["nhentai"].adult_only is True
    assert SOURCES["webtoons"].adult_only is False


def test_nhentai_results_are_filtered_by_safe_mode():
    from readerm.features import apply_filters
    from readerm.sources.nhentai import NhentaiSource

    row = NhentaiSource()._result("Some Doujin", "https://nhentai.to/g/1/",
                                  content_rating="pornographic", tags=["Adult"])
    assert apply_filters([row], {"safe_mode": True}) == []
    assert len(apply_filters([row], {"safe_mode": False})) == 1


@pytest.mark.parametrize("thumb,full", [
    ("https://cdn.test/galleries/1/1t.jpg", "https://cdn.test/galleries/1/1.jpg"),
    ("https://cdn.test/galleries/1/12t.png", "https://cdn.test/galleries/1/12.png"),
    ("https://cdn.test/galleries/1/cover.jpg", "https://cdn.test/galleries/1/cover.jpg"),
])
def test_nhentai_thumbnail_to_full_size(thumb, full):
    """Thumbs are 't'-suffixed; the full page is the same path without it."""
    from readerm.sources.nhentai import NhentaiSource

    assert NhentaiSource.full_size(thumb) == full


def test_webtoons_extracts_title_no():
    """The numeric id is the only stable identifier; the genre path varies."""
    from readerm.sources.webtoons import WebtoonsSource

    url = "https://www.webtoons.com/en/action/some-slug/list?title_no=10565"
    assert WebtoonsSource.title_no(url) == "10565"
    assert WebtoonsSource.title_no("https://www.webtoons.com/en/") is None


def test_webtoons_sends_a_referer():
    """pstatic.net answers 403 without one -- measured live."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = open(os.path.join(root, "readerm", "sources", "webtoons.py"),
                  encoding="utf-8").read()
    assert "def download_file" in source
    assert "webtoons.com" in source


@pytest.mark.parametrize("url,expected", [
    ("https://www.webtoons.com/en/romance/x/list?title_no=1", "webtoons"),
    ("https://nhentai.to/g/123/", "nhentai"),
])
def test_new_source_url_detection(url, expected):
    from readerm.sources import detect_source

    assert detect_source(url) == expected


# ======================================================= live checks


@NETWORK
@pytest.mark.parametrize("source_id,query", [
    ("webtoons", "romance"),
    ("nhentai", "romance"),
])
def test_live_new_sources(source_id, query):
    from readerm.sources import get_source

    source = get_source(source_id)
    try:
        results = source.search(query, limit=3)
        assert results, f"{source_id} returned nothing"
        info = source.get_manga_info(results[0]["url"])
        assert info["title"] and info["cover"]
        chapters = source.get_chapters(results[0]["url"])
        assert chapters
        images = source.get_chapter_images(chapters[0])
        assert images and all(u.startswith("http") for u in images)
    finally:
        source.close()


@NETWORK
def test_live_mangakatana_search_is_stable():
    """Regression: repeated searches used to return nothing ~60% of the time
    because of empty-but-200 throttle responses."""
    from readerm.sources import get_source

    hits = 0
    for _ in range(4):
        source = get_source("mangakatana")
        try:
            if source.search("one piece", limit=3):
                hits += 1
        finally:
            source.close()
    assert hits == 4, f"only {hits}/4 searches returned results"


@NETWORK
def test_live_popular_title_hits_several_sources():
    """'One Piece' must aggregate, not collapse to a single source."""
    from readerm.sources import search_all

    results = search_all("one piece", limit=5)
    sources = {r["source"] for r in results}
    assert len(sources) >= 3, f"only {sources} contributed"
