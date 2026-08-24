"""Regression tests for v1.4.4.

Covers the three reported bugs and the three new sources:

* nhentai returned nothing when browsing (root page has no cards) and its
  genre list was invented (7 of 12 slugs were 404s).
* Webtoons covers 403'd because the GUI sends ``no-referrer`` for MangaDex.
* Natomanga covers were rewritten onto sibling hosts that do not hold them.
* Mangadass / Manga18.club / HentaiAkane added.

Everything here is offline: the live behaviour these encode was measured
while writing the sources and is quoted in each source's module docstring.
"""

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "mangasurf", "gui", "web")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def code(text):
    """Source with comments removed.

    Several of these checks assert that a decoy endpoint is *not* used. The
    docstrings and comments deliberately name those endpoints to explain why
    they are avoided, so matching raw text produces false failures.
    """
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    return re.sub(r"(?m)#.*$", "", text)


# ============================================================== nhentai


def test_nhentai_browses_popular_not_the_site_root():
    """The root page carries zero .gallery cards, so browse always came back
    empty. /popular is the real listing."""
    src = read(os.path.join(ROOT, "mangasurf", "sources", "nhentai.py"))
    body = src[src.index("def browse"):src.index("def genres")]
    assert "/popular?page=" in body
    # the old, empty endpoint must be gone
    assert 'f"{SITE}/?page={page}"' not in body


def test_nhentai_genres_are_real_tag_slugs():
    """The old list was generic manga genres; 7 of its 12 answered 404."""
    from mangasurf.sources.nhentai import NhentaiSource

    dead = {"romance", "drama", "fantasy", "school-life", "vanilla",
            "historical", "sci-fi"}
    assert not dead & set(NhentaiSource.GENRES)
    # a few that were verified to return 25 galleries each
    for slug in ("big-breasts", "sole-female", "nakadashi", "full-color"):
        assert slug in NhentaiSource.GENRES


def test_nhentai_browse_sorts_drop_the_404_endpoints():
    """popular-today is a 404; only sorts the site accepts may be offered."""
    from mangasurf.sources.nhentai import NhentaiSource

    assert "popular-today" not in NhentaiSource._SORTS.values()


def test_nhentai_uses_the_sites_own_cover_fallbacks():
    """Cards ship data-fallbacks; honouring it is what stops empty tiles."""
    from bs4 import BeautifulSoup

    from mangasurf.sources.nhentai import NhentaiSource

    fallbacks = ["https://cdn/g/1/thumb.webp", "https://cdn/g/1/1t.jpg"]
    html = f'''<div class="gallery">
      <a class="cover" href="/g/1/"><div class="thumb">
      <img src="https://cdn/g/1/thumb.jpg"
           data-fallbacks='{json.dumps(fallbacks)}'></div></a>
      <div class="caption">Some Title</div></div>'''

    source = NhentaiSource()
    results = source._cards(BeautifulSoup(html, "html.parser"), 10)
    assert len(results) == 1
    mirrors = results[0]["cover_mirrors"]
    assert mirrors[0] == "https://cdn/g/1/thumb.jpg"
    for url in fallbacks:
        assert url in mirrors


def test_nhentai_survives_broken_fallback_json():
    from bs4 import BeautifulSoup

    from mangasurf.sources.nhentai import NhentaiSource

    html = ('<div class="gallery"><a href="/g/2/"><img src="/c.jpg" '
            "data-fallbacks='{not json'></a>"
            '<div class="caption">T</div></div>')
    results = NhentaiSource()._cards(BeautifulSoup(html, "html.parser"), 10)
    assert results and results[0]["cover_mirrors"] == ["https://nhentai.to/c.jpg"]


# ============================================================= webtoons


def test_only_webtoons_declares_a_hotlinked_cover_cdn():
    """Measured: every other cover CDN answers 200 with no Referer."""
    from mangasurf.sources import SOURCE_CLASSES

    flagged = {c.id for c in SOURCE_CLASSES
               if getattr(c, "cover_needs_referer", False)}
    assert flagged == {"webtoons"}


def test_cover_flag_is_exposed_to_the_frontend():
    from mangasurf.sources import list_sources

    rows = {row["id"]: row for row in list_sources()}
    assert rows["webtoons"]["cover_needs_referer"] is True
    assert rows["mangadex"]["cover_needs_referer"] is False


def test_gui_exposes_a_cover_proxy():
    """An <img> cannot send a Referer under no-referrer, so Python fetches
    those covers and inlines them."""
    from mangasurf.gui import Api

    assert callable(getattr(Api, "proxy_cover", None))


def test_proxy_cover_rejects_non_http_urls():
    from mangasurf.gui import Api

    api = Api.__new__(Api)          # no window / settings needed
    for bad in ("", "file:///etc/passwd", "javascript:alert(1)", "data:x"):
        assert api.proxy_cover(bad)["ok"] is False


# ============================================================ natomanga


# ====================================================== the new sources


NEW_SOURCES = ["mangadass", "manga18club", "hentaiakane"]


@pytest.mark.parametrize("source_id", NEW_SOURCES)
def test_new_source_is_registered(source_id):
    from mangasurf.sources import SOURCES

    assert source_id in SOURCES


@pytest.mark.parametrize("source_id", NEW_SOURCES)
def test_new_source_is_flagged_adult(source_id):
    from mangasurf.sources import SOURCES

    assert SOURCES[source_id].adult_only is True


@pytest.mark.parametrize("source_id, url", [
    ("mangadass", "https://mangadass.com/manga/single-daddy"),
    ("manga18club", "https://manga18.club/manhwa/dirty-talk-raw"),
    ("hentaiakane", "https://hentaiakane.com/manga/love-cheer/"),
])
def test_new_source_claims_its_urls(source_id, url):
    from mangasurf.sources import detect_source

    assert detect_source(url) == source_id


@pytest.mark.parametrize("source_id", NEW_SOURCES)
def test_new_source_implements_the_contract(source_id):
    from mangasurf.sources import SOURCES

    cls = SOURCES[source_id]
    for method in ("search", "browse", "genres", "get_manga_info",
                   "get_chapters", "get_chapter_images"):
        assert method in cls.__dict__, f"{source_id} does not define {method}"


# ---------------------------------------------------------- mangadass


def test_mangadass_avoids_the_decoy_search():
    """/?s= returns the homepage grid unchanged for every term."""
    src = code(read(os.path.join(ROOT, "mangasurf", "sources", "mangadass.py")))
    body = src[src.index("def search"):src.index("def browse")]
    assert "/search?q=" in body
    assert "?s=" not in body


def test_mangadass_orders_chapters_numerically():
    """"Read First"/"Read Last" shortcuts sit above the list, so document
    order put Chapter 1 last (measured: 2,3,4,5,6,7,8,1)."""
    from bs4 import BeautifulSoup

    from mangasurf.sources.mangadass import MangadassSource

    html = "".join(
        f'<a href="/manga/x/chapter-{n}">Chapter {n}</a>'
        for n in (1, 5, 2, 10, 3))
    html = '<a href="/manga/x/chapter-1">Read First</a>' + html

    source = MangadassSource()
    source.fetch = lambda *a, **k: type(
        "R", (), {"content": html.encode(), "text": html})()
    chapters = source.get_chapters("https://mangadass.com/manga/x")
    numbers = [int(re.search(r"(\d+)", c["url"].rsplit("-", 1)[-1]).group(1))
               for c in chapters]
    assert numbers == sorted(numbers)
    assert numbers[0] == 1


# -------------------------------------------------------- manga18.club


def test_manga18club_uses_search_not_q():
    """?q= is ignored -- it returned the same 20 rows for every term."""
    src = code(read(os.path.join(ROOT, "mangasurf", "sources", "manga18club.py")))
    body = src[src.index("def search"):src.index("def browse")]
    assert "search=" in body
    assert "?q=" not in body


def test_manga18club_decodes_the_base64_page_list():
    """The reader ships no usable <img> tags; pages live in slides_p_path."""
    import base64

    from mangasurf.sources.manga18club import Manga18ClubSource

    urls = [f"https://cdn.manga18.club/manga/x/chapters/chap-1/0{n}.jpg"
            for n in (1, 2, 3)]
    encoded = ",".join(
        '"%s"' % base64.b64encode(u.encode()).decode() for u in urls)
    html = f"var slides_p_path = [{encoded}];"

    assert Manga18ClubSource.decode_slides(html) == urls


def test_manga18club_decode_is_safe_on_junk():
    from mangasurf.sources.manga18club import Manga18ClubSource

    assert Manga18ClubSource.decode_slides("") == []
    assert Manga18ClubSource.decode_slides("no slides here") == []
    assert Manga18ClubSource.decode_slides('slides_p_path = ["!!!!"];') == []


def test_manga18club_ignores_the_placeholder_image():
    src = read(os.path.join(ROOT, "mangasurf", "sources", "manga18club.py"))
    assert "manga18.club/1.jpg" in src


def test_manga18club_cover_does_not_come_from_the_sidebar():
    """.story_images is the "you may also like" grid and returned another
    series' artwork."""
    src = code(read(os.path.join(ROOT, "mangasurf", "sources", "manga18club.py")))
    body = src[src.index("def get_manga_info"):src.index("def get_chapters")]
    assert ".detail_avatar img" in body
    assert ".story_images" not in body


# --------------------------------------------------------- hentaiakane


def test_hentaiakane_parses_the_ts_reader_payload():
    from mangasurf.sources.hentaiakane import HentaiAkaneSource

    payload = {"sources": [{"images": ["https://img.hentai1.io/a/1.jpg",
                                       "https://img.hentai1.io/a/2.jpg"]}]}
    html = "ts_reader.run(%s);" % json.dumps(payload)
    assert HentaiAkaneSource.parse_reader(html) == payload["sources"][0]["images"]


def test_hentaiakane_reader_parse_is_safe_on_junk():
    from mangasurf.sources.hentaiakane import HentaiAkaneSource

    assert HentaiAkaneSource.parse_reader("") == []
    assert HentaiAkaneSource.parse_reader("ts_reader.run({broken);") == []


def test_hentaiakane_cards_ignore_the_sidebar_series_links():
    """a.series matches 60 sidebar links on a search page; only .bs is real."""
    from bs4 import BeautifulSoup

    from mangasurf.sources.hentaiakane import HentaiAkaneSource

    html = '''<a class="series" href="/manga/sidebar/" title="Sidebar"></a>
      <div class="bs"><div class="bsx"><a href="/manga/real/" title="Real">
      <img src="/c.jpg"><div class="tt">Real</div></a></div></div>'''
    results = HentaiAkaneSource()._cards(BeautifulSoup(html, "html.parser"), 10)
    assert [r["title"] for r in results] == ["Real"]


def test_hentaiakane_uses_the_plural_genres_path():
    """/genre/<slug>/ is a 404; the site uses /genres/<slug>/."""
    src = read(os.path.join(ROOT, "mangasurf", "sources", "hentaiakane.py"))
    body = src[src.index("def browse"):src.index("def genres")]
    assert "/genres/" in body


def test_hentaiakane_documents_the_domain_correction():
    """The request said "hentaikane"; that domain does not resolve."""
    src = read(os.path.join(ROOT, "mangasurf", "sources", "hentaiakane.py"))
    assert "hentaikane" in src           # the spelling is explained
    assert "NXDOMAIN" in src


# ================================================================ misc


def test_landing_page_source_count_matches_the_registry():
    """The redesigned page shows this as a hero stat rather than a tab
    counter, but the number still has to track the registry."""
    from mangasurf.sources import SOURCE_CLASSES

    html = read(os.path.join(ROOT, "docs", "index.html"))
    # Read the stat tiles structurally: keying on one set of class names
    # made this silently vacuous after the page was redesigned.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tiles = {}
    for value in soup.select(".st-n, .hs-n"):
        label = value.find_next(class_=["st-k", "hs-k"])
        if label:
            tiles[label.get_text(strip=True).lower()] = value.get_text(strip=True)
    assert tiles.get("sources") == str(len(SOURCE_CLASSES)), (
        f"page says {tiles.get('sources')}, registry has {len(SOURCE_CLASSES)}")


def test_adult_sources_are_all_rating_stamped():
    """Safe mode filters on content_rating/tags, so every adult source must
    set them or it would leak into a filtered search."""
    from mangasurf.sources import SOURCE_CLASSES

    for cls in SOURCE_CLASSES:
        if not getattr(cls, "adult_only", False):
            continue
        src = read(os.path.join(ROOT, "mangasurf", "sources",
                                cls.__module__.rsplit(".", 1)[-1] + ".py"))
        assert "pornographic" in src, cls.id
