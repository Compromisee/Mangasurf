"""HentaiAkane source (HTML scraping of hentaiakane.com).

The request named "hentaikane". That exact spelling does not resolve --
``hentaikane.com``, ``.net``, ``.org``, ``.xyz`` and ``.to`` are all
NXDOMAIN. The site meant is ``hentaiakane.com`` ("Manhwa Hentai & Manga
Hentai"), which is live and returns HTTP 200.

Notes from probing the live site (2026-07):

Theme
    A WordPress build of the Themesia/Mangastream theme, the same family as
    a lot of manhwa aggregators, so the layout is predictable.

Search
    ``/?s=<term>`` genuinely filters (unlike Mangadass and Manga18.club,
    whose ``?s=``/``?q=`` are decoys). Results are ``.bs`` cards holding a
    ``.bsx > a`` with the title on both the ``title`` attribute and ``.tt``.
    Pagination is WordPress-style: ``/page/<n>/?s=<term>`` -- verified page 2
    returns a different set.

    Careful: ``a.series`` also matches 60 elements on a search page, but
    those are the sidebar's popular-list links, not the results.

Browse / genres
    ``/manga/?order=<update|popular|title>`` and ``/genres/<slug>/``.
    Note the plural: ``/genre/<slug>/`` is a 404.

Chapters
    ``#chapterlist li a`` -> ``/<series-slug>-chapter-N/`` (the chapter lives
    at the site root, not under ``/manga/``).

Images
    The reader exposes the page list twice: as ``#readerarea img`` tags and
    inside a ``ts_reader.run({...})`` JSON blob. The JSON is preferred
    because it is not affected by lazy-loading placeholders, with the DOM as
    a fallback. Images are served from ``img.hentai1.io``; measured, the CDN
    hotlinks fine (200 and the identical 1,265,647 bytes with and without a
    Referer).
"""

import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://hentaiakane.com"

#: ``ts_reader.run({... "sources":[{"images":[...]}] ...})``
_TS_READER = re.compile(r"ts_reader\.run\((\{.*?\})\);", re.S)


class HentaiAkaneSource(Source):
    id = "hentaiakane"
    name = "HentaiAkane"
    base_url = SITE
    domains = ("hentaiakane.com", "img.hentai1.io")

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True
    #: Adult-only site; stamped so Safe mode filters it and the UI shows 18+.
    adult_only = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Popularity", "Title")

    _ORDER = {
        "Latest Updates": "update",
        "Trending": "popular",
        "Popularity": "popular",
        "Title": "title",
    }

    GENRES = (
        "action", "adult", "adventure", "bl", "comedy", "comics",
        "doujinshi", "drama", "ecchi", "fantasy", "gender-bender", "gl",
        "harem", "historical", "horror", "isekai", "josei", "manhua",
        "manhwa", "martial-arts", "mature", "mystery", "psychological",
        "romance", "school-life", "sci-fi", "seinen", "shoujo", "shounen",
        "slice-of-life", "smut", "supernatural", "thriller", "tragedy",
        "webtoon", "yaoi", "yuri",
    )

    # ---------------------------------------------------------- helpers

    def _cards(self, soup, limit):
        """Parse a ``.bs`` grid. Shared by search, browse and genres.

        Deliberately scoped to ``.bs``: ``a.series`` on the same page is the
        sidebar popular list and would inject unrelated titles.
        """
        results, seen = [], set()
        for card in soup.select(".bs"):
            link = card.select_one("a[href]")
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            if href in seen:
                continue

            title = (link.get("title") or "").strip()
            if not title:
                label = card.select_one(".tt")
                title = label.get_text(" ", strip=True) if label else ""
            if not title:
                continue

            cover = None
            img = card.select_one("img")
            if img is not None:
                cover = (img.get("data-src") or img.get("src") or "").strip()
                if cover:
                    cover = urljoin(SITE, cover)

            latest = None
            chapter = card.select_one(".epxs")
            if chapter is not None:
                latest = chapter.get_text(" ", strip=True) or None

            seen.add(href)
            results.append(self._result(
                title, href, cover=cover,
                latest=latest,
                content_rating="pornographic",
                tags=["Adult"],
                adult=True,
            ))
            if len(results) >= limit:
                break
        return results

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        page = max(1, int(page or 1))
        if page > 1:
            url = f"{SITE}/page/{page}/?s={quote(query)}"
        else:
            url = f"{SITE}/?s={quote(query)}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("hentaiakane search failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._ORDER.get(sort or "", "update")
        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            # plural "genres" -- the singular form is a 404
            base = f"{SITE}/genres/{quote(slug)}/"
        else:
            base = f"{SITE}/manga/"
        url = f"{base}?page={page}&order={order}" if page > 1 else f"{base}?order={order}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("hentaiakane browse failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def genres(self) -> list:
        return [{"id": slug, "name": slug.replace("-", " ").title()}
                for slug in self.GENRES]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        heading = soup.select_one("h1.entry-title, h1")
        title = heading.get_text(" ", strip=True) if heading else "Unknown"

        cover = None
        img = soup.select_one(".thumb img, .infomanga img, img.wp-post-image")
        if img is not None:
            cover = (img.get("data-src") or img.get("src") or "").strip()
        if not cover:
            meta = soup.select_one('meta[property="og:image"]')
            cover = (meta.get("content") or "").strip() if meta else ""
        cover = urljoin(SITE, cover) if cover else None

        description = None
        block = soup.select_one('.entry-content[itemprop="description"], '
                                '.desc, .entry-content')
        if block is not None:
            description = re.sub(r"\s+", " ",
                                 block.get_text(" ", strip=True)) or None

        tags = ["Adult"]
        for link in soup.select('a[href*="/genres/"]'):
            label = link.get_text(strip=True)
            if label and label not in tags:
                tags.append(label)

        authors = [a.get_text(strip=True)
                   for a in soup.select('a[href*="/author/"]')
                   if a.get_text(strip=True)]

        status = None
        match = re.search(r"Status\s*:?\s*(Ongoing|Completed|Hiatus|Dropped)",
                          soup.get_text(" ", strip=True), re.I)
        if match:
            status = match.group(1).title()

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:20],
            "status": status,
            "authors": authors[:5],
            "artists": [],
            "content_rating": "pornographic",
            "adult": True,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        chapters, seen = [], set()
        for link in soup.select("#chapterlist li a, .eplister li a"):
            href = urljoin(SITE, link.get("href") or "")
            if not href or href in seen:
                continue
            label = link.select_one(".chapternum")
            name = (label.get_text(" ", strip=True) if label
                    else link.get_text(" ", strip=True))
            # the raw text also carries the release date; keep the number
            match = re.search(r"(Chapter\s*[\d.]+)", name, re.I)
            if match:
                name = match.group(1)
            if not name:
                name = href.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        # The list renders newest first; the engine wants oldest first.
        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    @staticmethod
    def parse_reader(html):
        """Pull the ordered page list out of the ``ts_reader.run`` payload."""
        match = _TS_READER.search(html or "")
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except (TypeError, ValueError):
            logger.debug("hentaiakane: unparsable ts_reader payload")
            return []

        images = []
        for source in payload.get("sources") or []:
            for url in source.get("images") or []:
                url = (url or "").strip()
                if url and url not in images:
                    images.append(url)
        return images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)

        images = self.parse_reader(response.text)
        if images:
            return images

        soup = BeautifulSoup(response.content, "html.parser")
        for img in soup.select("#readerarea img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src:
                continue
            src = urljoin(SITE, src)
            if src not in images:
                images.append(src)
        return images
