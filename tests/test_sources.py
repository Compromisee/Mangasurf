"""Tests for the multi-source layer.

Offline by default: anything that touches the network is marked ``network``
and skipped unless you opt in.

    python -m pytest tests/                    # offline only
    READERM_NETWORK_TESTS=1 python -m pytest   # include live-site tests
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangasurf.sources import (  # noqa: E402
    SOURCES,
    detect_source,
    get_source,
    list_sources,
    source_for_url,
)
from mangasurf.sources.base import ScrapeError, Source  # noqa: E402
from mangasurf.sources.mangadex import MangaDexSource  # noqa: E402
from mangasurf.sources.mangakatana import MangakatanaSource  # noqa: E402
from mangasurf.sources.natomanga import NatomangaSource  # noqa: E402

NETWORK = pytest.mark.skipif(
    not os.environ.get("READERM_NETWORK_TESTS"),
    reason="set READERM_NETWORK_TESTS=1 to run live-site tests",
)


# --------------------------------------------------------------- registry


def test_every_source_registered():
    assert {
        "mangadex", "mangakatana", "natomanga", "weebcentral",
        "omegascans", "manhwaread", "manhwa18", "webtoons", "nhentai",
    } <= set(SOURCES)


def test_sources_implement_the_interface():
    for cls in SOURCES.values():
        assert issubclass(cls, Source)
        assert cls.id and cls.name and cls.base_url and cls.domains
        for method in ("search", "get_manga_info", "get_chapters",
                       "get_chapter_images"):
            assert getattr(cls, method) is not getattr(Source, method), (
                f"{cls.__name__} must override {method}()"
            )


def test_list_sources_metadata():
    metas = list_sources()
    assert len(metas) == len(SOURCES)
    assert all({"id", "name", "base_url", "sorts"} <= set(m) for m in metas)


@pytest.mark.parametrize("url,expected", [
    ("https://mangadex.org/title/a1c7c817-4e59-43b7-9365-09675a149a6f", "mangadex"),
    ("https://mangakatana.com/manga/naruto.1205", "mangakatana"),
    ("https://www.natomanga.com/manga/naruto", "natomanga"),
    ("https://weebcentral.com/series/XYZ/name", "weebcentral"),
    ("a1c7c817-4e59-43b7-9365-09675a149a6f", "mangadex"),   # bare UUID
    ("https://example.com/manga/x", None),
])
def test_detect_source(url, expected):
    assert detect_source(url) == expected


def test_source_for_url_rejects_unknown_site():
    with pytest.raises(ScrapeError):
        source_for_url("https://example.com/manga/x")


def test_get_source_rejects_unknown_id():
    with pytest.raises(ScrapeError):
        get_source("not-a-real-source")


# ------------------------------------------------------- mangadex covers


def test_cover_url_keeps_the_original_extension():
    """The size suffix goes *after* the full filename, extension included.

    ``abc.png`` -> ``abc.png.512.jpg``. Stripping the ``.png`` first is the
    classic mistake and 404s on the CDN.
    """
    manga_id = "8f3e1818-a015-491d-bd81-3addc4d7d56a"
    file_name = "26dd2770-d383-42e9-a42b-32765a4d99c8.png"
    build = MangaDexSource.cover_url

    assert build(manga_id, file_name, "original") == (
        f"https://uploads.mangadex.org/covers/{manga_id}/{file_name}"
    )
    assert build(manga_id, file_name, "small") == (
        f"https://uploads.mangadex.org/covers/{manga_id}/{file_name}.256.jpg"
    )
    assert build(manga_id, file_name, "medium") == (
        f"https://uploads.mangadex.org/covers/{manga_id}/{file_name}.512.jpg"
    )
    # the wrong way must never be produced
    assert ".png.512.jpg" in build(manga_id, file_name, "medium")
    assert not build(manga_id, file_name, "medium").endswith("8.512.jpg")


def test_cover_url_handles_missing_data():
    assert MangaDexSource.cover_url("", "x.png") is None
    assert MangaDexSource.cover_url("abc", "") is None


def test_covers_from_relationships_expands_all_sizes():
    manga_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    relationships = [
        {"type": "author", "attributes": {"name": "Someone"}},
        {"type": "cover_art", "attributes": {"fileName": "cover.jpg"}},
    ]
    covers = MangaDexSource._covers_from_relationships(manga_id, relationships)
    assert covers["cover"].endswith("/cover.jpg")
    assert covers["cover_small"].endswith("/cover.jpg.256.jpg")
    assert covers["cover_medium"].endswith("/cover.jpg.512.jpg")


def test_covers_from_relationships_without_cover():
    covers = MangaDexSource._covers_from_relationships("id", [{"type": "author"}])
    assert covers["cover"] is None


# ----------------------------------------------------- mangadex chapters


def _chapter(id_="c1", chapter="1", pages=10, external=None, groups=(),
             unavailable=False):
    return {
        "id": id_,
        "attributes": {
            "chapter": chapter, "volume": "1", "title": "", "pages": pages,
            "externalUrl": external, "translatedLanguage": "en",
            "publishAt": "2024-01-01T00:00:00+00:00",
            "isUnavailable": unavailable,
        },
        "relationships": [
            {"type": "scanlation_group", "attributes": {"name": g}} for g in groups
        ],
    }


def test_external_chapters_are_filtered_out():
    """Licensed chapters redirect elsewhere and host zero pages."""
    source = MangaDexSource()
    assert source._parse_chapter(_chapter(external="https://mangaplus.example/1",
                                          pages=0)) is None
    assert source._parse_chapter(_chapter(pages=0)) is None
    assert source._parse_chapter(_chapter(unavailable=True)) is None
    assert source._parse_chapter(_chapter()) is not None


def test_dedupe_prefers_the_most_complete_release():
    source = MangaDexSource()
    chapters = [
        source._parse_chapter(_chapter("a", "1", pages=5, groups=("Group A",))),
        source._parse_chapter(_chapter("b", "1", pages=20, groups=("Group B",))),
    ]
    result = source._dedupe(chapters)
    assert len(result) == 1
    assert result[0]["id"] == "b"
    assert result[0]["alternatives"][0]["id"] == "a"


def test_dedupe_honours_the_preferred_scanlator():
    source = MangaDexSource(scanlator="Group A")
    chapters = [
        source._parse_chapter(_chapter("a", "1", pages=5, groups=("Group A",))),
        source._parse_chapter(_chapter("b", "1", pages=20, groups=("Group B",))),
    ]
    assert source._dedupe(chapters)[0]["id"] == "a"


def test_chapters_are_sorted_oldest_first():
    source = MangaDexSource()
    chapters = [source._parse_chapter(_chapter(f"c{n}", str(n)))
                for n in (10, 2, 1, 30)]
    numbers = [c["number"] for c in source._dedupe(chapters)]
    assert numbers == ["1", "2", "10", "30"]


def test_extract_id_from_various_urls():
    uuid = "a1c7c817-4e59-43b7-9365-09675a149a6f"
    for url in (f"https://mangadex.org/title/{uuid}",
                f"https://mangadex.org/title/{uuid}/one-piece",
                uuid.upper()):
        assert MangaDexSource.extract_id(url) == uuid
    with pytest.raises(ScrapeError):
        MangaDexSource.extract_id("https://mangadex.org/title/not-a-uuid")


# -------------------------------------------------- mangakatana decoding


def test_page_list_ignores_the_decoy_array():
    """Chapter pages ship as two JS arrays; the short one is a decoy."""
    import re
    from mangasurf.sources.mangakatana import _JS_ARRAY, _JS_URL

    html = """
    <script>
      var ytaw=['https://i1.mangakatana.com/token/aaa/0.jpg',];
      var thzq=['https://i1.mangakatana.com/token/bbb/0.jpg',
                'https://i1.mangakatana.com/token/ccc/1.jpg',
                'https://i1.mangakatana.com/token/ddd/2.jpg'];
    </script>
    """
    candidates = [_JS_URL.findall(m.group(1)) for m in _JS_ARRAY.finditer(html)]
    best = max(candidates, key=len)
    assert len(best) == 3
    assert all("/token/" in u for u in best)


def test_pages_sort_numerically_not_lexically():
    urls = [f"https://i1.mangakatana.com/token/x/{n}.jpg" for n in (0, 1, 2, 10, 11)]
    shuffled = [urls[3], urls[0], urls[4], urls[2], urls[1]]
    assert MangakatanaSource._sort_pages(shuffled) == urls


def test_cover_and_banner_urls_are_not_pages():
    assert not MangakatanaSource._looks_like_page(
        "https://mangakatana.com/imgs/cover/04e/07/b57f8.jpg")
    assert not MangakatanaSource._looks_like_page("/relative/path.jpg")
    assert MangakatanaSource._looks_like_page(
        "https://i1.mangakatana.com/token/abc/0.jpg")


# ----------------------------------------------------------- natomanga


def test_slug_extraction():
    assert NatomangaSource.slug_of("https://www.natomanga.com/manga/naruto") == "naruto"
    assert NatomangaSource.slug_of(
        "https://www.natomanga.com/manga/one-piece/chapter-1") == "one-piece"
    with pytest.raises(ScrapeError):
        NatomangaSource.slug_of("https://www.natomanga.com/genre/action")


# --------------------------------------------------------- base helpers


def test_image_sniffing_accepts_octet_stream():
    """Some CDNs mislabel images as application/octet-stream."""
    class FakeResponse:
        headers = {"content-type": "application/octet-stream"}

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 32
    assert Source._is_image(FakeResponse(), jpeg)
    assert Source._is_image(FakeResponse(), png)
    assert Source._is_image(FakeResponse(), webp)
    assert not Source._is_image(FakeResponse(), b"<!DOCTYPE html><html>")
    assert not Source._is_image(FakeResponse(), b"")


def test_image_sniffing_trusts_a_proper_content_type():
    class FakeResponse:
        headers = {"content-type": "image/jpeg"}
    assert Source._is_image(FakeResponse(), b"anything")


@pytest.mark.parametrize("url,expected", [
    ("https://x.com/a/1.jpg", ".jpg"),
    ("https://x.com/a/1.PNG", ".png"),
    ("https://x.com/a/1.webp?token=abc", ".webp"),
    ("https://x.com/a/1", ".jpg"),
    ("https://x.com/a/1.php", ".jpg"),
])
def test_guess_extension(url, expected):
    assert Source.guess_extension(url) == expected


def test_normalize_url_adds_scheme():
    assert Source.normalize_url("mangadex.org/x") == "https://mangadex.org/x"
    assert Source.normalize_url(" https://a.com ") == "https://a.com"


def test_chapter_url_accepts_dict_or_string():
    assert Source._chapter_url({"url": "u"}) == "u"
    assert Source._chapter_url({"id": "i"}) == "i"
    assert Source._chapter_url("plain") == "plain"


def test_retry_after_header_parsing():
    class FakeResponse:
        def __init__(self, headers):
            self.headers = headers
    assert Source._retry_after(FakeResponse({"Retry-After": "5"})) == 5
    assert Source._retry_after(FakeResponse({})) is None
    assert Source._retry_after(FakeResponse({"Retry-After": "99999"})) is None


# ------------------------------------------------------------- download


def test_download_options_carry_source_fields():
    from mangasurf.downloader import DownloadOptions
    opt = DownloadOptions(url="x")
    assert opt.source == ""
    assert opt.language == "en"
    assert opt.data_saver is False


def test_engine_autodetects_the_source():
    from mangasurf.downloader import DownloadEngine, DownloadOptions
    engine = DownloadEngine(DownloadOptions(
        url="https://mangakatana.com/manga/naruto.1205"))
    assert engine.source.id == "mangakatana"
    # legacy alias still points at the same object
    assert engine.scraper is engine.source


def test_engine_respects_an_explicit_source():
    from mangasurf.downloader import DownloadEngine, DownloadOptions
    engine = DownloadEngine(DownloadOptions(url="whatever", source="natomanga"))
    assert engine.source.id == "natomanga"


def test_legacy_scraper_import_still_works():
    from mangasurf.scraper import WeebCentralScraper
    assert WeebCentralScraper().id == "weebcentral"


# --------------------------------------------------------- live network


@NETWORK
@pytest.mark.parametrize("source_id,query", [
    ("mangadex", "oshi no ko"),
    ("mangakatana", "naruto"),
    ("natomanga", "naruto"),
])
def test_live_search_and_chapters(source_id, query):
    source = get_source(source_id)
    try:
        results = source.search(query, limit=3)
        assert results, f"{source_id} returned no search results"
        assert all(r["url"] and r["title"] for r in results)

        info = source.get_manga_info(results[0]["url"])
        assert info["title"]
        assert info["cover"], "no cover resolved"

        chapters = source.get_chapters(results[0]["url"])
        assert chapters, "no chapters found"

        images = source.get_chapter_images(chapters[0])
        assert images, "no page images found"
        assert all(u.startswith("http") for u in images)
    finally:
        source.close()


@NETWORK
def test_live_mangadex_cover_sizes_all_resolve():
    import requests
    source = MangaDexSource()
    try:
        info = source.get_manga_info("a1c7c817-4e59-43b7-9365-09675a149a6f")
        for key in ("cover", "cover_medium", "cover_small"):
            response = requests.get(info[key], headers=source.headers(),
                                    timeout=30, stream=True)
            assert response.status_code == 200, f"{key} -> {response.status_code}"
            assert response.headers["content-type"].startswith("image/")
            response.close()
    finally:
        source.close()


# ===================================== newly added sources (v1.3)


def test_new_sources_are_registered():
    assert {"omegascans", "manhwaread", "manhwa18"} <= set(SOURCES)


def test_manhwa18_is_flagged_adult():
    """The site hosts adult content exclusively, so safe_mode must catch it."""
    assert SOURCES["manhwa18"].adult_only is True
    assert SOURCES["mangadex"].adult_only is False


def test_manhwa18_results_carry_an_adult_rating(monkeypatch):
    """Tagging results lets the existing safe_mode filter drop them without
    any special-casing in the filter code."""
    from mangasurf.features import apply_filters
    from mangasurf.sources.manhwa18 import Manhwa18Source

    source = Manhwa18Source()
    row = source._result("Some Title", "https://manhwa18.cc/webtoon/x",
                         content_rating="pornographic", tags=["Adult"])
    assert apply_filters([row], {"safe_mode": True}) == []
    assert len(apply_filters([row], {"safe_mode": False})) == 1


@pytest.mark.parametrize("url,expected", [
    ("https://omegascans.org/series/affair-agency", "omegascans"),
    ("https://manhwaread.com/manhwa/3xlove/", "manhwaread"),
    ("https://manhwa18.cc/webtoon/some-slug", "manhwa18"),
])
def test_new_sources_detect_their_urls(url, expected):
    assert detect_source(url) == expected


def test_omegascans_slug_extraction():
    from mangasurf.sources.omegascans import OmegaScansSource

    assert OmegaScansSource.slug_of(
        "https://omegascans.org/series/affair-agency") == "affair-agency"
    with pytest.raises(ScrapeError):
        OmegaScansSource.slug_of("https://omegascans.org/browse")


def test_manhwaread_decodes_base64_chapter_data():
    """Pages are blob: URLs at runtime; the real list is base64 JSON in a
    `var chapterData = {...}` block."""
    import base64
    import json

    from mangasurf.sources.manhwaread import _CHAPTER_DATA

    pages = [{"src": "126682/mr_001.jpg"}, {"src": "126682/mr_002.jpg"}]
    encoded = base64.b64encode(json.dumps(pages).encode()).decode()
    html = ('<script>var chapterData = {"base":"https://manread.xyz/7077",'
            f'"data":"{encoded}"}};</script>')

    match = _CHAPTER_DATA.search(html)
    assert match
    payload = json.loads(match.group(1))
    decoded = json.loads(base64.b64decode(payload["data"]).decode())
    built = [f"{payload['base'].rstrip('/')}/{p['src']}" for p in decoded]
    assert built[0] == "https://manread.xyz/7077/126682/mr_001.jpg"


def test_manhwaread_sends_a_referer():
    """manread.xyz answers 403 without one and 200 with the site origin."""
    source = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mangasurf", "sources","manhwaread.py"), encoding="utf-8").read()
    assert "def download_file" in source
    assert "manhwaread.com" in source


@NETWORK
@pytest.mark.parametrize("source_id,query", [
    ("omegascans", "affair"),
    ("manhwaread", "love"),
    ("manhwa18", "secret"),
])
def test_live_new_sources(source_id, query):
    source = get_source(source_id)
    try:
        results = source.search(query, limit=3)
        assert results, f"{source_id} returned nothing"
        assert all(r["title"] and r["url"] for r in results)
        # a title of "Read" means the hover-button text leaked through
        assert all(r["title"].strip().lower() != "read" for r in results)

        info = source.get_manga_info(results[0]["url"])
        assert info["title"] and info["cover"]

        chapters = source.get_chapters(results[0]["url"])
        assert chapters, "no chapters found"
        images = source.get_chapter_images(chapters[0])
        assert images and all(u.startswith("http") for u in images)
    finally:
        source.close()
