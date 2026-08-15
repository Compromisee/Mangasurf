"""Madara Scans source (madarascans.org).

Naming, because it is genuinely confusing
-----------------------------------------
There are two unrelated things called "Madara" in this codebase:

* :mod:`readerm.sources.madara` -- the shared scraper for the **Madara
  WordPress theme**, which six other sites run. It is engine code, has no
  ``base_url``, is deliberately not registered, and never appears in the UI.
* **this module** -- the scanlation group *Madara Scans*, a real site that you
  can search and download from. It is registered and does appear in Settings.

Despite the name, Madara Scans does **not** run the Madara theme: its
``wp-content/themes/mangareader`` is the Themesia build, the same family as
Witch Scans and HentaiAkane. So it subclasses nothing from ``madara.py``.

Notes from probing the live site (2026-07):

Domain
    ``madarascans.com`` 301s to **madarascans.org**; the ``.org`` is canonical
    and every internal link uses it. Both are claimed so either pasted URL
    resolves. ``madarascan.com``, ``madara-scans.com`` and ``madaramanga.com``
    do not resolve.

Listing
    ``/series/`` is the catalogue -- 30 cards a page, 11 pages. ``/manga/``
    exists but returns a **53-byte** empty document, and the homepage renders
    its grid in JS so it has zero cards server-side. Using either would have
    produced a source that silently never browses.

Pagination
    ``/series/?page=N``. The path form ``/series/page/2/`` is a **decoy**: it
    answers 200 and returns page one (measured: the same 30 slugs). So is
    ``?paged=``, ``?pg=``, ``?offset=`` and ``?show=`` -- all four returned the
    identical 30. Only ``?page=`` pages, which is what the site's own
    pagination widget emits (``/series/?page=2`` … ``?page=11``).

Sorting
    ``?order=update|popular|title`` works on ``/series/`` and genuinely
    reorders (``?order=popular`` returned a different first title).

Search
    ``/?s=<term>`` filters properly. Page two is ``/page/<n>/?s=<term>`` --
    note that search pages on the *path* while browsing pages on the *query*,
    which is the opposite of what you would guess from either one alone.

Cards
    Results are plain anchors inside ``.listupd``; there are no ``.bs``/
    ``.bsx`` wrappers this theme normally ships, so the Witch Scans parser
    does not transfer. Each series is linked twice per card -- once wrapping
    the cover image, once wrapping the title text -- so hrefs are
    de-duplicated and the title is taken from whichever anchor carries text.

    ``/series/list-mode`` matches the same selector but is a **view-toggle
    link, not a series**, and is excluded by name.

Chapters
    ``#chapters-list-container .ch-item a`` -> ``/<series-slug>-chapter-N/``
    at the site root, not under ``/series/``.

    Three selectors that look right and are not: ``#chapterlist`` appears only
    inside a ``<style>`` block on this theme and matches **zero** anchors;
    ``.eplister`` does not exist here at all; and the rows are ``div.ch-item``,
    not ``<li>``, so ``li[id^="chapter-item-"]`` also matches zero even though
    the string ``chapter-item`` appears once per chapter. Scoping to the
    container additionally drops the previous/next shortcut anchors.

Genres
    ``/genres/<slug>/``. There is no genre index page -- ``/genres/`` itself
    lists none -- so the slugs are collected from series pages. All six were
    fetched and returned 200 with cards.

Images
    ``ts_reader.run({...})`` carries the ordered page list (42 pages on the
    chapter measured). Pages are served from the site's own
    ``/wp-content/uploads/manga/`` and hotlink fine: 200 ``image/webp`` with no
    Referer.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://madarascans.org"

#: ``ts_reader.run({... "sources":[{"images":[...]}] ...})``
_TS_READER = re.compile(r"ts_reader\.run\((\{.*?\})\);", re.S)

#: A series URL, anchored so listing/pagination links do not match.
_SERIES = re.compile(r"/series/([a-z0-9][a-z0-9-]*)/?$", re.I)

#: Matches the same selector as a series but is a view toggle.
_NOT_SERIES = {"list-mode", "grid-mode", "page"}


class MadaraScansSource(Source):
    id = "madarascans"
    name = "Madara Scans"
    base_url = SITE
    #: .com 301s to .org; claim both so either pasted link is recognised.
    domains = ("madarascans.org", "madarascans.com")

    #: Catalogue is Korean/Chinese action-fantasy; individual entries carry
    #: their own genres, so this is only a fallback.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Popularity", "Title")

    _ORDER = {
        "Latest Updates": "update",
        "Trending": "popular",
        "Popularity": "popular",
        "Title": "title",
    }

    #: Every slug fetched and confirmed 200 with cards. There is no genre
    #: index on the site, so these were gathered from series pages.
    GENRES = (
        "action", "demon", "drama", "fantasy", "martial-arts", "murim",
    )

    # ---------------------------------------------------------- helpers

    @staticmethod
    def _series_slug(href):
        """Slug for a real series URL, or ``None`` for anything else."""
        match = _SERIES.search((href or "").split("?", 1)[0].split("#", 1)[0])
        if not match:
            return None
        slug = match.group(1).lower()
        return None if slug in _NOT_SERIES else slug

    def _cards(self, soup, limit):
        """Parse a listing into results.

        This theme's grid is bare anchors, and every series is linked twice
        per card (cover, then title), so entries are keyed by slug and the
        first non-empty title wins.
        """
        found, order = {}, []
        for link in soup.select('a[href*="/series/"]'):
            slug = self._series_slug(link.get("href"))
            if slug is None:
                continue
            href = urljoin(SITE, link["href"])

            entry = found.get(slug)
            if entry is None:
                entry = {"url": href, "title": "", "cover": None,
                         "latest": None}
                found[slug] = entry
                order.append(slug)

            if not entry["title"]:
                title = (link.get("title") or "").strip()
                if not title:
                    title = link.get_text(" ", strip=True)
                # Chapter shortcuts inside a card carry text too.
                if title and not re.match(r"^chapter\s", title, re.I):
                    entry["title"] = title

            if entry["cover"] is None:
                img = link.select_one("img")
                if img is not None:
                    cover = (img.get("data-src") or img.get("src") or "").strip()
                    if cover:
                        entry["cover"] = urljoin(SITE, cover)

        results = []
        for slug in order:
            entry = found[slug]
            title = entry["title"] or slug.replace("-", " ").title()
            results.append(self._result(
                title, entry["url"], cover=entry["cover"],
                latest=entry["latest"],
                series_type=self.default_series_type,
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
        # Search pages on the PATH; browsing pages on the QUERY. Measured.
        if page > 1:
            url = f"{SITE}/page/{page}/?s={quote(query)}"
        else:
            url = f"{SITE}/?s={quote(query)}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("madarascans search failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._ORDER.get(sort or "", "update")

        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            base = f"{SITE}/genres/{quote(slug)}/"
            url = base if page == 1 else f"{base}?page={page}"
        else:
            # ?page= only. /series/page/2/ silently returns page one.
            url = f"{SITE}/series/?order={order}"
            if page > 1:
                url += f"&page={page}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("madarascans browse failed: %s", e)
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
        img = soup.select_one(".thumb img, img.wp-post-image")
        if img is not None:
            cover = (img.get("data-src") or img.get("src") or "").strip()
        if not cover:
            meta = soup.select_one('meta[property="og:image"]')
            cover = (meta.get("content") or "").strip() if meta else ""
        cover = urljoin(SITE, cover) if cover else None

        description = None
        block = soup.select_one('[itemprop="description"], .entry-content, '
                                '.desc')
        if block is not None:
            description = re.sub(r"\s+", " ",
                                 block.get_text(" ", strip=True)) or None
        if not description:
            meta = soup.select_one('meta[name="description"]')
            if meta is not None:
                description = (meta.get("content") or "").strip() or None

        tags, seen = [], set()
        for link in soup.select('a[href*="/genres/"]'):
            label = link.get_text(strip=True)
            if label and label.lower() not in seen:
                seen.add(label.lower())
                tags.append(label)

        text = soup.get_text(" ", strip=True)
        status = None
        match = re.search(r"Status\s*:?\s*(Ongoing|Completed|Hiatus|Dropped)",
                          text, re.I)
        if match:
            status = match.group(1).title()

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:20],
            "status": status,
            "authors": [],
            "artists": [],
            "series_type": classify_type(tags=tags) or self.default_series_type,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        # The list is #chapters-list-container > div.ch-item -- NOT <li>, and
        # NOT #chapterlist, which on this theme appears only inside a <style>
        # block and matches zero anchors. Scoping to the container also drops
        # the previous/next shortcut anchors that sit outside it.
        items = soup.select('#chapters-list-container .ch-item a[href]')
        if not items:
            items = soup.select('div[id^="chapter-item-"] a[href]')
        if not items:
            items = soup.select('#chapterlist li a[href], .eplister li a[href]')

        chapters, seen = [], set()
        for link in items:
            href = urljoin(SITE, link.get("href") or "")
            if not href or href in seen:
                continue
            label = link.select_one(".chapternum")
            name = (label.get_text(" ", strip=True) if label
                    else link.get_text(" ", strip=True))
            name = re.sub(r"\s+", " ", name)
            match = re.search(r"(Chapter\s*[\d.]+)", name, re.I)
            if match:
                name = match.group(1)
            if not name:
                slug = href.rstrip("/").rsplit("/", 1)[-1]
                number = re.search(r"chapter-([\d.]+)", slug, re.I)
                name = (f"Chapter {number.group(1)}" if number
                        else slug.replace("-", " ").title())
            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        # Newest first on the page; the engine wants oldest first.
        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    @staticmethod
    def parse_reader(html):
        """Ordered page list from the ``ts_reader.run`` payload."""
        match = _TS_READER.search(html or "")
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except (TypeError, ValueError):
            logger.debug("madarascans: unparsable ts_reader payload")
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
