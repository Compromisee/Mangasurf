"""Mewhen18 source (HTML scraping of mewhen18.com).

The original request named "hentaiakane". That domain (``hentaiakane.com``,
a manhwa-hentai aggregator) has since been taken over: it now resolves to a
bare "mewhen18.com -" shell and the old series permalinks are gone. Per
direction, this source now targets https://mewhen18.com/, which hosts the
same catalogue (Secret Class, Staying with Ajumma, Dont Rub It Against Me
There, ...).

Verified against the live site (2026-08) with curl_cffi + Chrome
impersonation plus a headed reference browser:

Theme
    A WordPress/Madara build whose archive pages reuse the ``.bs`` / ``.bsx``
    card grid, so browse, search and the chapter list are all very close to
    the theme the old HentaiAkane install used.

Series permalinks are 404
    Card links point at ``/manga/<slug>/``, which returns 404 on this
    install (in a real browser too). The working series page is the
    WordPress category archive ``/category/<slug>/``, so every card URL is
    rewritten from ``/manga/<slug>/`` to ``/category/<slug>/`` before it
    leaves this module.

Search
    ``/?s=<term>`` genuinely filters (verified: "secret" -> Secret Class).
    Pagination is WordPress-style: ``/page/<n>/?s=<term>``.

Browse
    The homepage ``/`` is the latest-updates grid (42 ``.bs`` cards),
    paginated via ``/page/<n>/``. This install has no ``/manga/`` listing
    and no ``/genres/`` taxonomy, so genre browsing is not supported and a
    genre argument degrades to the latest-updates grid.

Chapters
    A series page (``/category/<slug>/``) lists chapters as ``.listupd .bsx``
    cards whose links live at the site root: ``/<series-slug>-chapter-<N>/``,
    with ``.epxs`` carrying "Chapter 310" (or "Chapter 309.6"). The list is
    paginated (Secret Class spans ~30 pages), so we follow every page
    instead of returning only the first ten. Chapter cards carry no
    ``#chapterlist`` container, so they are parsed directly from the grid.

Images
    The reader exposes the page list as ``#readerarea img`` and inside a
    ``ts_reader.run({...})`` JSON blob. The JSON is preferred (immune to
    lazy-load placeholders); the DOM is the fallback. Images come from
    ``img.hentai1.io`` -- the same CDN as the old install -- and hotlink
    fine (verified 200 with and without a Referer).
"""

import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://mewhen18.com"

#: ``ts_reader.run({... "sources":[{"images":[...]}] ...})``
_TS_READER = re.compile(r"ts_reader\.run\((\{.*?\})\);", re.S)

#: ``/manga/<slug>/`` -> that permalink is a 404; the category archive is real.
_MANGA_PATH = re.compile(r"/manga/([^/?#]+)/?$")

#: Safety cap on chapter-list pagination (a long-running series must not
#: fan out into the hundreds of requests).
_MAX_CHAPTER_PAGES = 80


class Mewhen18Source(Source):
    id = "mewhen18"
    name = "Mewhen18"
    base_url = SITE
    domains = ("mewhen18.com", "img.hentai1.io")

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    #: No ``/genres/`` taxonomy on this install (category = per-series group).
    supports_genres = False
    #: Adult-only site; stamped so Safe mode filters it and the UI shows 18+.
    adult_only = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates",)

    # ---------------------------------------------------------- helpers

    @staticmethod
    def _series_href(href):
        """Rewrite the dead ``/manga/<slug>/`` card link to the live archive."""
        href = (href or "").strip()
        match = _MANGA_PATH.search(href)
        if match:
            return urljoin(SITE, f"/category/{quote(match.group(1))}/")
        return href

    def _cards(self, soup, limit):
        """Parse a ``.bs`` series grid. Shared by search and browse.

        Scoped to ``.bs`` (the card grid); stray ``a.series`` sidebar links on
        the same page are ignored. The card's ``/manga/<slug>/`` href is
        rewritten to the working ``/category/<slug>/``.
        """
        results, seen = [], set()
        for card in soup.select(".bs"):
            link = card.select_one("a[href]")
            if not link or not link.get("href"):
                continue
            href = self._series_href(urljoin(SITE, link["href"]))
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
            logger.error("mewhen18 search failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        # Latest-updates grid on the homepage, paginated; no genre taxonomy.
        url = f"{SITE}/page/{page}/" if page > 1 else f"{SITE}/"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("mewhen18 browse failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def genres(self) -> list:
        # No ``/genres/`` taxonomy on this install.
        return []

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        heading = soup.select_one("h1.entry-title, h1, .page-title")
        title = heading.get_text(" ", strip=True) if heading else "Unknown"

        # The category archive's first chapter card carries the series cover.
        cover = None
        img = soup.select_one(".listupd .bsx img, .thumb img")
        if img is not None:
            cover = (img.get("data-src") or img.get("src") or "").strip()
        cover = urljoin(SITE, cover) if cover else None

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": None,
            "tags": ["Adult"],
            "status": None,
            "authors": [],
            "artists": [],
            "content_rating": "pornographic",
            "adult": True,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def _chapter_cards(self, soup):
        """Collect ``(href, name)`` chapter pairs from a series archive page."""
        cards, seen = [], set()
        for card in soup.select(".listupd .bsx a[href]"):
            href = urljoin(SITE, card.get("href") or "")
            if not href or href in seen:
                continue
            seen.add(href)
            name = None
            label = card.select_one(".epxs")
            if label is not None:
                name = label.get_text(" ", strip=True)
            match = re.search(r"chapter\s*([\d.]+)", name or "", re.I)
            if match:
                name = f"Chapter {match.group(1)}"
            if not name:
                name = href.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            cards.append({"url": href, "name": name})
        return cards

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        # Normalise a pasted ``/manga/`` link to the live category archive too.
        manga_url = self._series_href(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        chapters = self._chapter_cards(soup)

        # Follow the pagination (page 1 is the newest; older chapters live on
        # later pages) so a full series is returned, not just the front page.
        depth = 0
        while depth < _MAX_CHAPTER_PAGES:
            last = 0
            for a in soup.select(f'a[href*="{manga_url.rstrip(chr(47))}/page/"]'):
                m = re.search(r"/page/(\d+)/", a.get("href") or "")
                if m:
                    last = max(last, int(m.group(1)))
            if last <= 1:
                break
            for n in range(2, last + 1):
                url = f"{manga_url.rstrip('/')}/page/{n}/"
                try:
                    resp = self.fetch(url)
                except ScrapeError as e:
                    logger.warning("mewhen18 chapter page %s failed: %s", n, e)
                    continue
                more = self._chapter_cards(
                    BeautifulSoup(resp.content, "html.parser"))
                if not more:
                    break
                chapters.extend(c for c in more
                                if c["url"] not in {x["url"] for x in chapters})
            break

        # De-duplicate while preserving order, then oldest-first (page 1 is
        # newest-first, so a reverse of the collected list is the read order).
        seen, uniq = set(), []
        for c in chapters:
            if c["url"] in seen:
                continue
            seen.add(c["url"])
            uniq.append({**c, "referer": manga_url, "source": self.id})
        uniq.reverse()
        return uniq

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
            logger.debug("mewhen18: unparsable ts_reader payload")
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
