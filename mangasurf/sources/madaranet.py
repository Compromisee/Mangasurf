"""Madara Sites -- one source that fans out across every Madara-theme site.

The **Madara** WordPress theme ("A powerful manga, novel theme from
Mangabooth.com") powers a large slice of the manhwa/manhua aggregator web.
:mod:`mangasurf.sources.madara` scrapes it; this module turns the whole set of
sites running it into a **single entry** in the UI.

Why one source instead of ten
-----------------------------
Every Madara install is the same software with a different skin, so from the
reader's point of view they are one catalogue that happens to be spread over
ten domains. Listing them individually made Settings long and pushed the
choice of "which mirror has this?" onto the user. Here the choice disappears:
a search hits all of them in parallel and the results are merged, with the
site each hit came from kept on the row.

Not to be confused with
-----------------------
* :mod:`mangasurf.sources.madara` -- the scraping engine. Not a source, never in
  the UI.
* :mod:`mangasurf.sources.madarascans` -- *Madara Scans*, an unrelated
  scanlation site that does not even run this theme.

Members
-------
Each entry is a full :class:`~mangasurf.sources.madara.MadaraSource` subclass,
so all the per-install quirks that release 1.4.15 measured still apply --
the genre prefix that 404s if guessed, the search pagination that silently
returns page one on the path form, the AJAX call that needs an explicit empty
body. Nothing about the scraping changed; only the packaging did.

Sites, and what is specific to each (measured 2026-07):

    toonily.com        /serie/     webtoon-genre   listing /search/
                       page CDN 403s without a Referer
    manhuaplus.com     /manga/     manga-genre     listing /manga/
    manhuatop.org      /manhua/    manhua-genre    listing /manga/  (!)
                       /manhua/?m_orderby= returns zero cards
    manhwatop.com      /manga/     manga-genre     listing /manga/
                       genre slugs are SEO-mangled: genre-action-new-genre
    mangaread.org      /manga/     genres          listing /manga/
    setsuscans.com     /manga/     manga-genre     listing /manga/
                       Cloudflare; needs FlareSolverr
    coffeemanga.ink    /manga/     manga-genre     listing /manga/
    mangasushi.org     /manga/     manga-genre     listing /manga/
    mangaowl.io        /read-1/    manga-genre     listing /manga-list/
                       /manga/ answers HTTP 410
    mangagg.com        /comic/     genre           listing /comic/

Two candidates were **rejected** after testing rather than shipped broken:

* ``manhwafull.com`` -- its search cards carry ``href="/"`` instead of a
  series URL, so there is nothing to follow.
* ``zinmanga.net`` -- the chapter AJAX route answers 404 and the series page
  embeds no chapter list, so no chapters can be read.

Fan-out
-------
Search and browse run the members in a thread pool and interleave the results,
so the first screen is a mix rather than one site's entire page. A member that
fails is logged and skipped -- one dead mirror never breaks the source. The
per-site circuit breaker in :mod:`mangasurf.robust` still applies to each member
individually.

Every result, and every series/chapter URL, still belongs to the real site it
came from, so ``get_manga_info``/``get_chapters``/``get_chapter_images``
delegate to whichever member owns that URL. Downloading is therefore identical
to using the site directly.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .base import ScrapeError, Source
from .madara import MadaraSource

logger = logging.getLogger(__name__)


# --------------------------------------------------------------- members
#
# Each of these is a normal Madara subclass. They are deliberately *not*
# registered in SOURCE_CLASSES -- MadaraNetSource is the single public face.


class _Toonily(MadaraSource):
    id = "madara.toonily"
    name = "Toonily"
    base_url = "https://toonily.com"
    domains = ("toonily.com", "static.tnlycdn.com", "data.tnlycdn.com")
    default_series_type = "Manhwa"
    series_prefix = "/serie/"
    genre_prefix = "webtoon-genre"
    browse_path = "/search/"
    GENRES = (
        "action", "adventure", "comedy", "crime", "drama", "fantasy",
        "historical", "horror", "isekai", "josei", "magic", "mature",
        "mystery", "psychological", "romance", "school-life", "seinen",
        "shoujo", "shounen", "slice-of-life", "sports", "supernatural",
        "thriller", "tragedy", "villainess", "wuxia", "yaoi", "yuri",
    )


class _ManhuaPlus(MadaraSource):
    id = "madara.manhuaplus"
    name = "Manhua Plus"
    base_url = "https://manhuaplus.com"
    domains = ("manhuaplus.com", "cdn.manhuaplus.com")
    default_series_type = "Manhua"
    series_prefix = "/manga/"
    genre_prefix = "manga-genre"
    browse_path = "/manga/"
    GENRES = (
        "action", "adult", "adventure", "comedy", "cooking", "doujinshi",
        "drama", "ecchi", "fantasy", "gender-bender", "harem", "historical",
        "horror", "josei", "manhua", "manhwa", "martial-arts", "mature",
        "mecha", "mystery", "one-shot", "psychological", "romance",
        "school-life", "sci-fi", "seinen", "shoujo", "shounen",
        "slice-of-life", "smut", "sports", "supernatural", "tragedy",
        "webtoon", "yaoi", "yuri",
    )


class _ManhuaTop(MadaraSource):
    id = "madara.manhuatop"
    name = "Manhua Top"
    base_url = "https://manhuatop.org"
    domains = ("manhuatop.org", "s3.manhuatop.org")
    default_series_type = "Manhua"
    series_prefix = "/manhua/"
    genre_prefix = "manhua-genre"
    #: /manhua/ returns an empty grid -- reproduced four times. /manga/ is
    #: the real listing even though series live under /manhua/.
    browse_path = "/manga/"
    GENRES = (
        "action", "adventure", "comedy", "cultivation", "drama", "dungeons",
        "fantasy", "game", "harem", "historical", "horror", "isekai",
        "magic", "manhua", "manhwa", "martial-arts", "mature", "murim",
        "mystery", "reincarnation", "romance", "school-life", "sci-fi",
        "seinen", "shounen", "slice-of-life", "supernatural", "system",
        "time-travel", "tragedy", "transmigration", "villainess", "wuxia",
    )


class _ManhwaTop(MadaraSource):
    id = "madara.manhwatop"
    name = "Manhwa Top"
    base_url = "https://manhwatop.com"
    domains = ("manhwatop.com", "c3.manhwatop.com")
    default_series_type = "Manhwa"
    series_prefix = "/manga/"
    genre_prefix = "manga-genre"
    browse_path = "/manga/"
    #: Real slugs, not tidied ones -- this install renames every taxonomy.
    GENRES = (
        "genre-action-new-genre", "adventure-genre-hot", "genre-comedy",
        "genre-drama", "ecchi-genre-hot", "fantasy-genre-hot",
        "harem-new", "historical-new-genre", "horror-genres-new",
        "isekai-new-genres", "josei-new-genre", "manhwa-hot",
        "martial-arts-genre-hot", "mature", "murim", "mystery-new-genres",
        "psychological-genre-hot", "romance-genre-hot", "school-life-genres",
        "sci-fi-genre-hot", "seinen-genre-hot", "shoujo-genres",
        "shounen-genres", "slice-of-life-genres", "smut-genre-hot",
        "supernatural-genres", "tragedy-genre-hot", "webtoons", "yaoi", "yuri",
    )


class _MangaRead(MadaraSource):
    id = "madara.mangaread"
    name = "MangaRead"
    base_url = "https://www.mangaread.org"
    domains = ("mangaread.org",)
    default_series_type = None
    series_prefix = "/manga/"
    #: /manga-genre/ is a 404 here; the archive is /genres/.
    genre_prefix = "genres"
    browse_path = "/manga/"
    GENRES = (
        "action", "adventure", "comedy", "cooking", "doujinshi", "drama",
        "ecchi", "fantasy", "gender-bender", "harem", "historical", "horror",
        "isekai", "josei", "magic", "manga", "manhua", "manhwa",
        "martial-arts", "mature", "mecha", "military", "mystery", "one-shot",
        "psychological", "reincarnation", "romance", "school-life", "sci-fi",
        "seinen", "shoujo", "shounen", "slice-of-life", "smut", "sports",
        "supernatural", "thriller", "tragedy", "webtoon",
    )


class _SetsuScans(MadaraSource):
    id = "madara.setsuscans"
    name = "Setsu Scans"
    base_url = "https://setsuscans.com"
    domains = ("setsuscans.com",)
    default_series_type = None
    #: 403 + cf-mitigated: challenge on every request without a solver.
    needs_flaresolverr = True
    series_prefix = "/manga/"
    genre_prefix = "manga-genre"
    browse_path = "/manga/"
    GENRES = (
        "action", "adventure", "comedy", "drama", "ecchi", "fantasy",
        "harem", "historical", "horror", "isekai", "josei", "manga",
        "manhua", "manhwa", "martial-arts", "mature", "mystery",
        "psychological", "romance", "school-life", "sci-fi", "seinen",
        "shoujo", "shounen", "slice-of-life", "smut", "supernatural",
        "tragedy", "webtoon", "yaoi", "yuri",
    )


class _CoffeeManga(MadaraSource):
    id = "madara.coffeemanga"
    name = "Coffee Manga"
    #: coffeemanga.io redirects here.
    base_url = "https://coffeemanga.ink"
    domains = ("coffeemanga.ink", "coffeemanga.io")
    default_series_type = None
    series_prefix = "/manga/"
    genre_prefix = "manga-genre"
    browse_path = "/manga/"
    GENRES = (
        "action", "adult", "adventure", "comedy", "drama", "ecchi",
        "fantasy", "harem", "historical", "horror", "isekai", "josei",
        "manhua", "manhwa", "martial-arts", "mature", "mystery",
        "psychological", "romance", "school-life", "sci-fi", "seinen",
        "shoujo", "shounen", "slice-of-life", "smut", "supernatural",
        "tragedy", "webtoon", "yaoi", "yuri",
    )


class _MangaSushi(MadaraSource):
    id = "madara.mangasushi"
    name = "MangaSushi"
    #: mangasushi.net redirects here.
    base_url = "https://mangasushi.org"
    domains = ("mangasushi.org", "mangasushi.net")
    default_series_type = None
    series_prefix = "/manga/"
    genre_prefix = "manga-genre"
    browse_path = "/manga/"
    GENRES = (
        "action", "adult", "adventure", "comedy", "cooking", "doujinshi",
        "drama", "ecchi", "fantasy", "gender-bender", "harem", "historical",
        "horror", "isekai", "josei", "manhua", "manhwa", "martial-arts",
        "mature", "mecha", "mystery", "one-shot", "psychological", "romance",
        "school-life", "sci-fi", "seinen", "shoujo", "shounen",
        "slice-of-life", "smut", "sports", "supernatural", "tragedy",
        "webtoon", "yaoi", "yuri",
    )


class _MangaOwl(MadaraSource):
    id = "madara.mangaowl"
    name = "MangaOwl"
    base_url = "https://mangaowl.io"
    domains = ("mangaowl.io",)
    default_series_type = None
    #: Series live under /read-1/, and /manga/ answers HTTP 410.
    series_prefix = "/read-1/"
    genre_prefix = "manga-genre"
    browse_path = "/manga-list/"
    GENRES = (
        "action", "adult", "adventure", "comedy", "drama", "ecchi",
        "fantasy", "harem", "historical", "horror", "isekai", "josei",
        "manhua", "manhwa", "martial-arts", "mature", "mystery",
        "psychological", "romance", "school-life", "sci-fi", "seinen",
        "shoujo", "shounen", "slice-of-life", "smut", "supernatural",
        "tragedy", "webtoon", "yaoi", "yuri",
    )


class _MangaGG(MadaraSource):
    id = "madara.mangagg"
    name = "MangaGG"
    base_url = "https://mangagg.com"
    domains = ("mangagg.com",)
    default_series_type = None
    series_prefix = "/comic/"
    #: Singular "genre" here, not the theme default "manga-genre".
    genre_prefix = "genre"
    browse_path = "/comic/"
    GENRES = (
        "action", "adventure", "comedy", "drama", "ecchi", "fantasy",
        "harem", "historical", "horror", "isekai", "josei", "manhua",
        "manhwa", "martial-arts", "mature", "mystery", "psychological",
        "romance", "school-life", "sci-fi", "seinen", "shoujo", "shounen",
        "slice-of-life", "smut", "supernatural", "tragedy", "webtoon",
    )


#: Every member, in the order they are tried and displayed.
MEMBERS = (
    _Toonily, _ManhuaPlus, _ManhuaTop, _ManhwaTop, _MangaRead,
    _CoffeeManga, _MangaSushi, _MangaOwl, _MangaGG, _SetsuScans,
)


class MadaraNetSource(Source):
    """One source spanning every site that runs the Madara theme."""

    #: NOT "madara" -- that reads as the theme engine in madara.py, which
    #: is exactly the confusion v1.4.17 had to untangle.
    id = "madaranet"
    name = "Madara Sites"
    #: Shown in the UI as the "home" link; the theme's own vendor page is the
    #: only honest choice, since there is no single site behind this entry.
    base_url = "https://mangabooth.com"
    #: Every member's domain, so pasting any of their URLs resolves here.
    domains = tuple(
        domain for member in MEMBERS for domain in member.domains
    )

    #: Mixed manga/manhwa/manhua across ten catalogues.
    default_series_type = None

    supports_search = True
    supports_browse = True
    supports_genres = True
    #: One member (Setsu Scans) is Cloudflare-gated. The rest work without a
    #: solver, and a member that cannot be read is skipped, so this is
    #: reported as False -- flagging it would imply the whole source needs
    #: FlareSolverr, which is not true.
    needs_flaresolverr = False

    search_sorts = ("Best Match",)
    browse_sorts = ("Trending", "Popularity", "Latest Updates", "Rating",
                    "Title", "New")

    #: How many members to hit at once.
    WORKERS = 6
    #: A member that has not answered by now is dropped from this call.
    DEADLINE = 25.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # delay/language/session are passed explicitly when building a member,
        # so they must not also arrive via **options -- that raises
        # "got multiple values for keyword argument 'delay'".
        self._options = {k: v for k, v in kwargs.items()
                         if k not in ("delay", "language", "session")}
        self._members = {}

    # ---------------------------------------------------------- members

    def member(self, member_id):
        """Instantiate (and cache) one member source."""
        source = self._members.get(member_id)
        if source is None:
            for cls in MEMBERS:
                if cls.id == member_id:
                    source = cls(delay=self.delay, language=self.language,
                                 **self._options)
                    self._members[member_id] = source
                    break
        return source

    def member_for_url(self, url):
        """The member that owns a series/chapter URL, or ``None``."""
        for cls in MEMBERS:
            if cls.handles(url):
                return self.member(cls.id)
        return None

    def _require_member(self, url):
        source = self.member_for_url(url)
        if source is None:
            raise ScrapeError(
                f"No Madara site recognises '{url}'. Sites: "
                + ", ".join(cls.base_url for cls in MEMBERS))
        return source

    def close(self):
        for source in self._members.values():
            try:
                source.close()
            except Exception:
                pass
        self._members.clear()
        super().close()

    # ----------------------------------------------------------- fanout

    def _fanout(self, call, limit):
        """Run ``call`` on every member in parallel and interleave results.

        A member that raises, or that has not answered by ``DEADLINE``, is
        logged and skipped: one dead mirror must never break the source.
        """
        from ..robust import SOURCE_BREAKER

        buckets = {}

        def run(cls):
            source = self.member(cls.id)
            # Keep the per-site breaker: a mirror that is down should stop
            # being dialled rather than costing a timeout on every search.
            return SOURCE_BREAKER.call(cls.id, lambda: call(source))

        pool = ThreadPoolExecutor(max_workers=min(self.WORKERS, len(MEMBERS)))
        try:
            futures = {pool.submit(run, cls): cls for cls in MEMBERS}
            try:
                for future in as_completed(futures, timeout=self.DEADLINE):
                    cls = futures[future]
                    try:
                        buckets[cls.id] = future.result() or []
                    except Exception as e:
                        logger.warning("[madaranet] %s failed: %s", cls.id, e)
            except Exception:
                # as_completed raises TimeoutError once the deadline passes;
                # whatever finished is still usable.
                pending = [futures[f].id for f in futures if not f.done()]
                if pending:
                    logger.warning("[madaranet] slow members dropped: %s",
                                   ", ".join(pending))
        finally:
            pool.shutdown(wait=False)

        # Interleave so the first screen is a mix of sites.
        merged, index = [], 0
        order = [cls.id for cls in MEMBERS if cls.id in buckets]
        while len(merged) < limit:
            added = False
            for member_id in order:
                rows = buckets[member_id]
                if index < len(rows):
                    merged.append(rows[index])
                    added = True
                    if len(merged) >= limit:
                        break
            if not added:
                break
            index += 1
        return merged

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **filters):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        # Ask each member for a share of the total, with a floor so small
        # limits still reach every site.
        per = max(4, -(-int(limit) // max(1, len(MEMBERS) // 2)))
        return self._fanout(
            lambda s: s.search(query, limit=per, page=page, **filters), limit)

    def browse(self, sort: str = "Trending", genre: str = None,
               page: int = 1, limit: int = 32, **filters):
        per = max(4, -(-int(limit) // max(1, len(MEMBERS) // 2)))
        return self._fanout(
            lambda s: s.browse(sort=sort, genre=genre, page=page,
                               limit=per, **filters), limit)

    @classmethod
    def offline_genres(cls):
        """Genre union without touching the network.

        ``genres()`` is already offline here -- it reads each member's
        declared list -- but the registry looks for ``GENRES`` on a source and
        an aggregate has none, so this is the explicit hook.
        """
        names = {}
        for member in MEMBERS:
            for slug in member.GENRES:
                label = MadaraSource._genre_label(slug)
                names.setdefault(label.lower(), label)
        return [{"id": name, "name": name}
                for _key, name in sorted(names.items())]

    def genres(self) -> list:
        """Union of the members' genres, keyed by name.

        The same genre has different slugs per install -- "Action" is
        ``action`` on most and ``genre-action-new-genre`` on Manhwa Top -- so
        the id exposed here is the **name**, and each member maps it back to
        its own slug when browsing.
        """
        return self.offline_genres()

    # ------------------------------------------------- per-URL delegates

    def get_manga_info(self, manga_url: str) -> dict:
        source = self._require_member(self.normalize_url(manga_url))
        info = source.get_manga_info(manga_url)
        # Report the aggregate as the source, but keep the real site visible.
        info["site"] = source.name
        info["site_url"] = source.base_url
        info["source"] = self.id
        info["source_name"] = f"{self.name} · {source.name}"
        return info

    def get_chapters(self, manga_url: str) -> list:
        source = self._require_member(self.normalize_url(manga_url))
        chapters = source.get_chapters(manga_url)
        for chapter in chapters:
            chapter["source"] = self.id
            chapter["site"] = source.name
        return chapters

    def get_chapter_images(self, chapter) -> list:
        url = self.normalize_url(self._chapter_url(chapter))
        return self._require_member(url).get_chapter_images(chapter)

    def download_file(self, url: str, filepath, referer: str = None,
                      max_retries: int = 5, headers: dict = None) -> bool:
        """Download through the owning member, so its headers apply.

        Toonily's page CDN 403s on any Referer that is not toonily.com, so
        using the aggregate's own session would fail there.
        """
        source = self.member_for_url(referer or url) or self
        if source is self:
            return super().download_file(url, filepath, referer=referer,
                                         max_retries=max_retries,
                                         headers=headers)
        return source.download_file(url, filepath, referer=referer,
                                    max_retries=max_retries, headers=headers)
