"""Regression tests for v1.4.15 -- eleven new manhwa/manhua sources.

Six were requested by name (Witch Scans, Writers' Scans, Manhua Top, Setsu
Scans, Manhua Plus, Demonic Scans) and five more added under "more manhwa and
manhua sources" (Asura Scans, Flame Comics, Toonily, Manhwa Top, MangaRead).

Everything here is offline. Each assertion encodes a behaviour that was
measured against the live site while the source was written, and the measured
numbers are quoted in the module docstrings so a future reader can re-check
them. The tests exist because in every one of these cases the *obvious*
implementation is the broken one.
"""

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "readerm", "sources")

#: The eleven sources v1.4.15 added. Six of them (the Madara-theme sites)
#: were folded into the single "madaranet" aggregate in v1.4.18, so they are
#: no longer registered individually -- they are reached as its members.
NEW_SOURCES = [
    "witchscans", "writerscans", "demonicscans", "asurascans", "flamecomics",
]

#: The Madara-theme sites, now members of the aggregate rather than sources.
MADARA_MEMBERS = [
    "madara.toonily", "madara.manhuaplus", "madara.manhuatop",
    "madara.manhwatop", "madara.mangaread", "madara.setsuscans",
]


def member(member_id):
    from readerm.sources.madaranet import MEMBERS

    for cls in MEMBERS:
        if cls.id == member_id:
            return cls
    raise AssertionError(f"no such member: {member_id}")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def code(text):
    """Source with docstrings and comments stripped.

    Several checks assert a decoy endpoint is *not used*. The docstrings name
    those endpoints deliberately, to explain why they are avoided, so matching
    raw text would produce false failures.
    """
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    return re.sub(r"(?m)#.*$", "", text)


def source_code(source_id):
    from readerm.sources import SOURCES

    module = SOURCES[source_id].__module__.rsplit(".", 1)[-1]
    return read(os.path.join(SRC, module + ".py"))


# ============================================================== registry


def test_every_new_source_is_registered():
    from readerm.sources import SOURCES

    missing = [s for s in NEW_SOURCES if s not in SOURCES]
    assert not missing, missing


def test_registry_ids_are_unique():
    """A duplicate id would silently shadow a source in the SOURCES dict."""
    from readerm.sources import SOURCE_CLASSES, SOURCES

    assert len(SOURCES) == len(SOURCE_CLASSES)


def test_madara_members_are_reachable_but_not_registered():
    """v1.4.18 folded the six Madara-theme sites into one aggregate. They
    must still be usable -- just not as separate rows in Settings."""
    from readerm.sources import SOURCES
    from readerm.sources.madaranet import MEMBERS

    ids = {cls.id for cls in MEMBERS}
    for member_id in MADARA_MEMBERS:
        assert member_id in ids, member_id
        assert member_id not in SOURCES, f"{member_id} leaked into the registry"


def test_new_sources_claim_their_domains():
    from readerm.sources import detect_source

    cases = [
        ("https://witchscans.com/manga/afterlife-diner/", "witchscans"),
        ("https://writerscans.com/series/652beef7274/", "writerscans"),
        ("https://demonicscans.org/manga/Eleceed", "demonicscans"),
        ("https://asuracomic.net/series/emperor-of-solo-play", "asurascans"),
        ("https://flamecomics.xyz/series/165", "flamecomics"),
        # The Madara-theme sites now resolve to the aggregate.
        ("https://manhuatop.org/manhua/golden-martial-god/", "madaranet"),
        ("https://manhuaplus.com/manga/martial-god-chat-group/", "madaranet"),
        ("https://setsuscans.com/manga/anything/", "madaranet"),
        ("https://toonily.com/serie/love-rebooted-dce39162/", "madaranet"),
        ("https://manhwatop.com/manga/complicated-love-in-tokyo/", "madaranet"),
        ("https://www.mangaread.org/manga/x/", "madaranet"),
    ]
    for url, expected in cases:
        assert detect_source(url) == expected, url


def test_new_sources_do_not_steal_existing_urls():
    """manhwatop/manhuatop/manhwaread are one letter apart; a sloppy domain
    tuple would have one swallow another's URLs."""
    from readerm.sources import detect_source

    assert detect_source("https://manhwaread.com/x") == "manhwaread"
    assert detect_source("https://manhwa18.cc/x") == "manhwa18"
    assert detect_source("https://mangadex.org/title/x") == "mangadex"


def test_new_sources_are_instantiable_and_declare_capabilities():
    from readerm.sources import get_source

    for source_id in NEW_SOURCES:
        source = get_source(source_id)
        try:
            assert source.base_url.startswith("https://"), source_id
            assert source.domains, source_id
            assert source.supports_search, source_id
        finally:
            source.close()


def test_none_of_the_new_sources_are_adult_flagged():
    """All eleven are general-audience scanlation sites. Flagging one adult
    would hide it behind Safe mode; failing to flag a real adult site would
    leak it into a filtered search. These are the former."""
    from readerm.sources import SOURCES

    for source_id in NEW_SOURCES:
        assert not getattr(SOURCES[source_id], "adult_only", False), source_id


# ====================================================== Cloudflare timeout


def test_fetch_stops_retrying_when_flaresolverr_is_absent():
    """The bug this fixes: a Cloudflare site with no solver running slept
    through five exponential backoffs -- 2+4+8+16+32 = 62s -- before giving
    up. Measured on Setsu Scans: one search took 67.5s and dragged a whole
    20-source search from ~4s to 66.1s. After the fix: 0.1s and 3.7s."""
    import time

    from readerm.sources.base import ScrapeError
    from readerm.sources.madaranet import _SetsuScans as SetsuScansSource

    class Challenged:
        status_code = 403
        text = "<title>Just a moment...</title>"
        content = b"x"
        headers = {}
        request = None

    source = SetsuScansSource()
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return Challenged()

    def no_solver(self, url, **kwargs):      # bound method: needs self
        raise ConnectionError("FlareSolverr is not reachable")

    source.session.get = fake_get
    import readerm.flaresolverr as fs
    original = fs.FlareSolverrSession.get
    fs.FlareSolverrSession.get = no_solver
    try:
        started = time.time()
        with pytest.raises(ScrapeError):
            source.fetch("https://setsuscans.com/", max_retries=5)
        elapsed = time.time() - started
    finally:
        fs.FlareSolverrSession.get = original
        source.close()

    # One attempt, no sleeping: the old code made five and slept 62s.
    assert len(calls) == 1, calls
    assert elapsed < 5, elapsed
    assert source._solverr_down is True


def test_solverr_down_is_sticky_per_source_instance():
    """Once the solver is known missing, later calls must not re-probe it."""
    from readerm.sources.madaranet import _SetsuScans as SetsuScansSource

    source = SetsuScansSource()
    try:
        source._solverr_down = True
        assert source._solve_challenge("https://setsuscans.com/", 0) is None
    finally:
        source.close()


def test_cloudflare_sources_say_they_need_a_solver():
    from readerm.sources import SOURCES

    assert member("madara.setsuscans").needs_flaresolverr is True
    assert SOURCES["weebcentral"].needs_flaresolverr is True
    # ...and the ones that do not, do not.
    for source_id in ("witchscans", "asurascans"):
        assert SOURCES[source_id].needs_flaresolverr is False, source_id
    assert member("madara.toonily").needs_flaresolverr is False


# ============================================================ Madara base


def test_madara_base_is_not_registered():
    """It is an implementation detail; registering it would put a broken
    "source" with no base_url in the UI."""
    from readerm.sources import SOURCE_CLASSES
    from readerm.sources.madara import MadaraSource

    assert MadaraSource not in SOURCE_CLASSES
    assert not any(cls is MadaraSource for cls in SOURCE_CLASSES)


def test_madara_search_uses_paged_not_page_path():
    """/page/2/?s= returns page ONE on Toonily -- 18 results, all 18 identical
    to page one. &paged=2 returns a disjoint set. Using the path form would
    make "next page" loop forever there."""
    from readerm.sources.madara import MadaraSource

    body = code(read(os.path.join(SRC, "madara.py")))
    search = body[body.index("def search"):body.index("def browse")]
    assert "paged=" in search
    assert "/page/" not in search
    import readerm.sources.madara as madara_module
    assert "paged" in (madara_module.__doc__ or "")


def test_madara_browse_pages_with_the_path_segment():
    from readerm.sources.madara import MadaraSource

    source = MadaraSource()
    source.base_url = "https://example.com"
    try:
        assert source._page_url("https://example.com/manga/", 1,
                                "m_orderby=views") == \
            "https://example.com/manga/?m_orderby=views"
        assert source._page_url("https://example.com/manga/", 2,
                                "m_orderby=views") == \
            "https://example.com/manga/page/2/?m_orderby=views"
    finally:
        source.close()


def test_madara_chapter_ajax_sends_a_body():
    """The AJAX route answers 400 with zero bytes for a bare POST and 200 with
    the full list when a body is present, even an empty one."""
    body = code(read(os.path.join(SRC, "madara.py")))
    fetch = body[body.index("def _chapter_soup"):body.index("def get_chapter_images")]
    assert "data=b\"\"" in fetch
    # the older admin-ajax route 400s on every one of these installs
    assert "admin-ajax" not in fetch


def test_madara_cards_fall_back_to_h3_when_post_title_is_absent():
    """Manhua Top's child theme drops .post-title entirely: 0 matches vs 12
    for h3 a. Only handling .post-title returned an empty grid there."""
    from bs4 import BeautifulSoup

    from readerm.sources.madara import MadaraSource

    html = """
      <div class="page-item-detail">
        <h3><a href="/manhua/x/">HOTReal Title</a></h3>
        <img data-src="https://cdn/x.jpg" src="https://cdn/dflazy.png">
      </div>"""
    source = MadaraSource()
    source.base_url = "https://example.com"
    try:
        rows = source._cards(BeautifulSoup(html, "html.parser"), 10)
    finally:
        source.close()

    assert [r["title"] for r in rows] == ["Real Title"]     # badge stripped
    assert rows[0]["cover"] == "https://cdn/x.jpg"          # not the placeholder


def test_madara_cards_prefer_data_src_over_the_lazy_placeholder():
    """Manhua Plus ships the theme's 'dflazy' placeholder in src and the real
    cover in data-src, so every card would show the same grey rectangle."""
    from bs4 import BeautifulSoup

    from readerm.sources.madara import MadaraSource

    html = """
      <div class="page-item-detail">
        <div class="post-title"><a href="/manga/y/">Y</a></div>
        <img src="https://site/wp-content/themes/madara/images/dflazy.jpg"
             data-src="https://site/real-cover.jpg">
      </div>"""
    source = MadaraSource()
    source.base_url = "https://site"
    try:
        rows = source._cards(BeautifulSoup(html, "html.parser"), 10)
    finally:
        source.close()
    assert rows[0]["cover"] == "https://site/real-cover.jpg"


def test_madara_genre_labels_strip_seo_noise():
    """Manhwa Top's real slugs are 'genre-action-new-genre' and
    'adventure-genre-hot'. The request must use them verbatim, but the picker
    must not read like that."""
    from readerm.sources.madara import MadaraSource

    assert MadaraSource._genre_label("genre-action-new-genre") == "Action"
    assert MadaraSource._genre_label("adventure-genre-hot") == "Adventure"
    assert MadaraSource._genre_label("romance-genre-hot") == "Romance"
    assert MadaraSource._genre_label("martial-arts") == "Martial Arts"


def test_each_madara_site_declares_its_measured_genre_prefix():
    """The prefix differs per install and a wrong one is a hard 404."""
    from readerm.sources import SOURCES

    expected = {
        "madara.manhuaplus": "manga-genre",
        "madara.manhuatop": "manhua-genre",
        "madara.mangaread": "genres",
        "madara.manhwatop": "manga-genre",
        "madara.toonily": "webtoon-genre",
        "madara.setsuscans": "manga-genre",
    }
    for member_id, prefix in expected.items():
        assert member(member_id).genre_prefix == prefix, member_id


def test_manhuatop_browses_the_manga_path_not_manhua():
    """Series live under /manhua/ but /manhua/?m_orderby= returns ZERO cards
    -- reproduced four times, three seconds apart. /manga/ is the listing."""
    from readerm.sources import SOURCES

    assert member("madara.manhuatop").series_prefix == "/manhua/"
    assert member("madara.manhuatop").browse_path == "/manga/"


def test_toonily_uses_the_singular_serie_path():
    from readerm.sources import SOURCES

    assert member("madara.toonily").series_prefix == "/serie/"
    assert member("madara.toonily").browse_path == "/search/"


# ============================================================ Witch Scans


def test_witchscans_keeps_the_percent_encoded_emoji_genres():
    """The taxonomy carries emoji, which WordPress encodes into the slug.
    Four genres are reachable ONLY through the encoded form; the plain word
    404s. Fetched: all 20 slugs answered 200 with cards."""
    from readerm.sources.witchscans import WitchScansSource

    slugs = [slug for slug, _label in WitchScansSource.GENRES]
    assert "action-%e2%9a%94%ef%b8%8f" in slugs
    assert "cultivation-%f0%9f%a7%98%e2%99%82%ef%b8%8f" in slugs
    assert "harem-%e2%9d%a4%ef%b8%8f%f0%9f%94%a5" in slugs
    assert "system-%e2%9a%99%ef%b8%8f" in slugs

    # measured 404s must not be advertised
    dead = {"school-life", "sci-fi", "seinen", "slice-of-life", "tragedy",
            "webtoon", "psychological", "villainess", "reincarnation",
            "regression"}
    assert not dead & set(slugs)


def test_witchscans_maps_a_genre_name_back_to_its_encoded_slug():
    from readerm.sources.witchscans import WitchScansSource

    assert WitchScansSource._genre_slug("Cultivation") == \
        "cultivation-%f0%9f%a7%98%e2%99%82%ef%b8%8f"
    assert WitchScansSource._genre_slug("Martial Arts") == "martial-arts"


def test_witchscans_uses_the_plural_genres_path():
    """/genre/<slug>/ is a 404; the archive is /genres/<slug>/."""
    body = code(source_code("witchscans"))
    browse = body[body.index("def browse"):body.index("def _genre_slug")]
    assert "/genres/" in browse


def test_witchscans_parses_the_ts_reader_payload():
    from readerm.sources.witchscans import WitchScansSource

    payload = {"sources": [{"images": ["https://s/1.jpg", "https://s/2.jpg"]}]}
    html = "ts_reader.run(%s);" % json.dumps(payload)
    assert WitchScansSource.parse_reader(html) == payload["sources"][0]["images"]
    assert WitchScansSource.parse_reader("") == []
    assert WitchScansSource.parse_reader("ts_reader.run({broken);") == []


def test_witchscans_reads_the_type_off_the_card():
    """Cards label themselves <span class="type Manhua">, which is better
    than the site-wide default."""
    from bs4 import BeautifulSoup

    from readerm.sources.witchscans import WitchScansSource

    html = """<div class="bs"><div class="bsx">
      <a href="/manga/x/" title="X"><span class="type Manhwa"></span>
      <div class="tt">X</div><div class="epxs">Chapter 5</div></a>
      </div></div>"""
    source = WitchScansSource()
    try:
        rows = source._cards(BeautifulSoup(html, "html.parser"), 5)
    finally:
        source.close()
    assert rows[0]["series_type"] == "Manhwa"
    assert rows[0]["latest"] == "Chapter 5"


def test_witchscans_strips_the_date_from_chapter_labels():
    """Labels read "Chapter 128 July 27, 2026"; the date is volatile and
    breaks library matching."""
    body = code(source_code("witchscans"))
    chapters = body[body.index("def get_chapters"):body.index("def parse_reader")]
    assert "Chapter\\s*[\\d.]+" in chapters


# ========================================================== Writers' Scans


def test_writerscans_rebuilds_pages_from_uid_not_src():
    """Every page ships src="/assets/images/placeholder.svg" and the real file
    is cdn.meowing.org/uploads/<uid>. Reading src returns six copies of an
    SVG -- which looks like it worked."""
    from readerm.sources.writerscans import WriterScansSource

    html = """
      <img src="/assets/images/placeholder.svg" count="2" uid="ccc">
      <img src="/assets/images/placeholder.svg" count="0" uid="aaa">
      <img src="/assets/images/placeholder.svg" count="1" uid="bbb">"""
    pages = WriterScansSource.parse_pages(html)
    assert pages == ["https://cdn.meowing.org/uploads/aaa",
                     "https://cdn.meowing.org/uploads/bbb",
                     "https://cdn.meowing.org/uploads/ccc"]
    assert not any("placeholder" in p for p in pages)


def test_writerscans_page_order_follows_count_not_document_order():
    from readerm.sources.writerscans import WriterScansSource

    html = '<img uid="z" count="9"><img uid="a" count="1">'
    assert WriterScansSource.parse_pages(html) == [
        "https://cdn.meowing.org/uploads/a",
        "https://cdn.meowing.org/uploads/z"]


def test_writerscans_parses_the_catalogue_buttons():
    from readerm.sources.writerscans import WriterScansSource

    html = """<button id="abc" alt="Star Flowers"
       title="Star Flowers Hoshi no Hana" tags='["Romance","Drama"]'
       data-type="manhwa" data-status="ongoing"
       style="background-image:url(https://wsrv.nl/?url=x&amp;w=600)">
       <a href="/series/abc/">x</a></button>"""
    rows = WriterScansSource.parse_catalogue(html)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Star Flowers"
    assert row["tags"] == ["Romance", "Drama"]
    assert row["status"] == "Ongoing"
    assert row["series_type"] == "Manhwa"
    assert row["url"] == "https://writerscans.com/series/abc/"
    assert row["cover"].startswith("https://wsrv.nl/")


def test_writerscans_search_matches_alternative_titles():
    """The site's own filter matches the title attribute, which carries every
    alias, so searching the romaji or original-language title works."""
    from readerm.sources.writerscans import WriterScansSource

    source = WriterScansSource()
    source._catalogue = WriterScansSource.parse_catalogue(
        """<button id="a" alt="Star Flowers" title="Star Flowers Hoshi no Hana"
           tags='[]'><a href="/series/a/">x</a></button>""")
    try:
        assert len(source.search("hoshi")) == 1
        assert len(source.search("star")) == 1
        assert len(source.search("nothing here")) == 0
    finally:
        source.close()


def test_writerscans_skips_coin_locked_chapters():
    body = code(source_code("writerscans"))
    chapters = body[body.index("def get_chapters"):body.index("def parse_pages")]
    assert "paid-chapter" in chapters


# =========================================================== Demonic Scans


def test_demonicscans_filters_genres_over_post_only():
    """Measured: GET ?genres[]=6 returned the same 55 rows as no filter at all
    (55 of 55 identical). The POST returned 56 rows sharing ZERO with the
    unfiltered set. A GET filter looks like it works and silently returns the
    whole catalogue."""
    body = code(source_code("demonicscans"))
    browse = body[body.index("def browse"):body.index("def genre_id")]
    assert "session.post" in browse
    assert "genres[]" in browse


def test_demonicscans_uses_numeric_genre_ids():
    """The form posts ids, not slugs: Action is 1, Martial Arts 6, Murim 36."""
    from readerm.sources.demonicscans import DemonicScansSource

    assert DemonicScansSource.GENRE_IDS["Action"] == 1
    assert DemonicScansSource.GENRE_IDS["Martial Arts"] == 6
    assert DemonicScansSource.GENRE_IDS["Murim"] == 36
    assert len(DemonicScansSource.GENRE_IDS) == 36
    assert DemonicScansSource.genre_id("martial arts") == 6
    assert DemonicScansSource.genre_id("nonsense") is None


def test_demonicscans_scopes_chapters_to_the_list():
    """A "Read First Chap" button outside the list points at chapter 1 too:
    416 anchors on the page, 415 inside #chapters-list."""
    # NB: not code() -- it strips "#..." as comments and would eat the CSS id
    # out of the selector string, failing on correct code.
    body = source_code("demonicscans")
    chapters = body[body.index("def get_chapters"):body.index("def get_chapter_images")]
    assert "#chapters-list a" in chapters


def test_demonicscans_strips_release_dates_from_chapter_names():
    """Labels read "Chapter 411 2026-07-28"."""
    body = code(source_code("demonicscans"))
    chapters = body[body.index("def get_chapters"):body.index("def get_chapter_images")]
    assert r"\d{4}-\d{2}-\d{2}" in chapters


def test_demonicscans_skips_the_relative_ad_banner():
    """The first img.imgholder is /img/free_ads.jpg, not a page."""
    body = code(source_code("demonicscans"))
    images = body[body.index("def get_chapter_images"):]
    assert "startswith" in images and "http" in images


def test_demonicscans_search_does_not_use_the_decoy_endpoints():
    """/index.php?search= returns the homepage and /api/search 404s."""
    body = code(source_code("demonicscans"))
    search = body[body.index("def search"):body.index("def browse")]
    assert "search.php?manga=" in search
    assert "index.php" not in search
    assert "/api/search" not in search


# ============================================================ Asura Scans


def test_asurascans_pages_with_offset_not_page():
    """?page=2, ?p=2, ?skip=20, ?per_page= and ?perPage= all returned page one
    (20 of 20 ids identical). Only offset pages: offset=20 shared 0 ids."""
    body = code(source_code("asurascans"))
    query = body[body.index("def _query"):body.index("def search")]
    assert "offset" in query
    assert '"page"' not in query


def test_asurascans_searches_with_search_not_the_decoys():
    """&name=, &q= and &title= are ignored -- each returned the full 338-item
    catalogue, i.e. "everything" for any word."""
    body = code(source_code("asurascans"))
    search = body[body.index("def search"):body.index("def browse")]
    assert "search=query" in search.replace(" ", "")
    for decoy in ("name=", "q=", "title="):
        assert decoy not in search


def test_asurascans_strips_the_constant_public_url_suffix():
    """Every public URL ends in the same -059befe1; it is a constant, not a
    per-series hash, and /api/series/<slug> accepts either form."""
    from readerm.sources.asurascans import AsuraScansSource

    for value in ("https://asuracomic.net/comics/emperor-of-solo-play-059befe1",
                  "https://asuracomic.net/series/emperor-of-solo-play",
                  "emperor-of-solo-play-059befe1",
                  "emperor-of-solo-play"):
        assert AsuraScansSource.slug_of(value) == "emperor-of-solo-play"


def test_asurascans_keys_chapter_pages_by_number():
    """/chapters/chapter-1 404s; /chapters/1 works."""
    body = code(source_code("asurascans"))
    chapters = body[body.index("def get_chapters"):body.index("def get_chapter_images")]
    assert "chapters/{number}" in chapters


def test_asurascans_skips_locked_chapters():
    body = code(source_code("asurascans"))
    chapters = body[body.index("def get_chapters"):body.index("def get_chapter_images")]
    assert "is_locked" in chapters


# =========================================================== Flame Comics


def test_flamecomics_sorts_the_image_dict_numerically():
    """images is a dict keyed by stringified index, not a list. Iterating it
    directly yields dictionary order, which is not page order."""
    from readerm.sources.flamecomics import FlameComicsSource

    chapter = {
        "series_id": 165, "token": "tok", "edit_time": 999,
        "images": {"10": {"name": "p10.jpg"}, "2": {"name": "p02.jpg"},
                   "1": {"name": "p01.jpg"}},
    }
    pages = FlameComicsSource.build_pages(chapter)
    assert [p.rsplit("/", 1)[-1] for p in pages] == \
        ["p01.jpg?999", "p02.jpg?999", "p10.jpg?999"]
    assert pages[0].startswith(
        "https://cdn.flamecomics.xyz/uploads/images/series/165/tok/")


def test_flamecomics_reads_the_next_data_payload():
    from readerm.sources.flamecomics import FlameComicsSource

    html = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"series":[{"series_id":1}]}}}</script>')
    assert FlameComicsSource.parse_next_data(html) == {"series": [{"series_id": 1}]}
    assert FlameComicsSource.parse_next_data("") == {}
    assert FlameComicsSource.parse_next_data(
        '<script id="__NEXT_DATA__" type="application/json">{oops</script>') == {}


def test_flamecomics_series_id_parsing():
    from readerm.sources.flamecomics import FlameComicsSource

    assert FlameComicsSource.series_id_of("https://flamecomics.xyz/series/165") == "165"
    assert FlameComicsSource.series_id_of("https://flamecomics.xyz/series/165/") == "165"
    assert FlameComicsSource.series_id_of("165") == "165"


# ================================================================ Toonily


def test_toonily_chapters_carry_a_referer():
    """data.tnlycdn.com answers 403 to any Referer that is not toonily.com --
    403 with none, 403 with example.com, 200 with the site. The engine
    forwards chapter["referer"] to every image download."""
    body = code(read(os.path.join(SRC, "madara.py")))
    chapters = body[body.index("def get_chapters"):body.index("def _chapter_soup")]
    assert '"referer"' in chapters


def test_toonily_covers_do_not_need_proxying():
    """static.tnlycdn.com serves covers with no Referer (200 both ways), so
    unlike Webtoons this does not need the Python-side proxy."""
    from readerm.sources import SOURCES

    assert member("madara.toonily").cover_needs_referer is False


# ============================================================== docs / UI


def test_landing_page_lists_every_source():
    from bs4 import BeautifulSoup

    from readerm.sources import list_sources

    soup = BeautifulSoup(read(os.path.join(ROOT, "docs", "index.html")),
                         "html.parser")
    listed = {t.get_text(strip=True).lower() for t in soup.select(".src-n")}
    real = {m["name"].lower() for m in list_sources()}
    assert listed == real, f"drifted: {listed ^ real}"


def test_landing_page_marks_both_cloudflare_sites():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read(os.path.join(ROOT, "docs", "index.html")),
                         "html.parser")
    flagged = set()
    for tile in soup.select("a.src"):
        if tile.select_one(".tag-cf"):
            flagged.add(tile.select_one(".src-n").get_text(strip=True))
    # Setsu Scans is now a member of the Madara Sites aggregate, so the
    # aggregate tile carries the badge on its behalf.
    assert flagged == {"Weeb Central", "Madara Sites"}


def test_readme_documents_every_source():
    """The Sources table keys on the source *id*, which is what -s takes.
    Checking the registry rather than a hand-written list means a source
    added without a README row fails here."""
    from readerm.sources import SOURCES

    readme = read(os.path.join(ROOT, "README.md"))
    for source_id in SOURCES:
        assert f"`{source_id}`" in readme, source_id


def test_readme_source_table_row_count_matches_the_registry():
    from readerm.sources import SOURCES

    readme = read(os.path.join(ROOT, "README.md"))
    table = readme[readme.index("| Source | Site |"):]
    table = table[:table.index("\n\n")]
    rows = [line for line in table.splitlines()
            if line.startswith("| `")]
    assert len(rows) == len(SOURCES), \
        f"{len(rows)} table rows vs {len(SOURCES)} sources"


def test_every_new_source_module_records_its_measurements():
    """These sources exist because the obvious implementation is wrong in each
    case. The docstring has to say why, or the next reader will "simplify" it
    straight back into the bug."""
    for source_id in NEW_SOURCES:
        text = source_code(source_id)
        assert text.lstrip().startswith('"""'), source_id
        head = text.split('"""')[1]
        assert "2026-07" in head or "measured" in head.lower() \
            or "Measured" in head, source_id
