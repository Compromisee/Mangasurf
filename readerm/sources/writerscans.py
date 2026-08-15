"""Writers' Scans source (HTML scraping of writerscans.com).

This is a bespoke Tailwind + htmx site, not one of the usual themes, so
nothing here is shared with the other sources.

Notes from probing the live site (2026-07):

Catalogue size
    The whole catalogue is **27 series**. That is not a paging bug: the
    listing at ``/series/`` returns 27 links, ``?page=2`` returns the same 27,
    and the site's own search endpoint returns 27 cards. It is a small
    scanlation group.

Search
    There is no server-side search. The site loads the entire catalogue once
    from ``GET /search_series`` and filters it **in the browser** by the
    ``title`` attribute -- their own JS reads
    ``anchor.getAttribute("title").toLowerCase().includes(inputValue)``, and
    ``/series/?q=<term>`` returns the unfiltered 27 either way (measured).

    So search is done the same way here: fetch the catalogue once, match
    locally. The upside is that the ``title`` attribute carries every
    alternative title -- "Star Flowers Hoshi no Hana, 星のはな" -- so a search
    for the romaji or the original-language title works.

Catalogue cards
    ``/search_series`` returns bare ``<button>`` elements, one per series,
    carrying everything needed without a second request::

        <button id="652beef7274" alt="Star Flowers"
                title="Star Flowers Hoshi no Hana, 星のはな"
                tags='["Romance","Slice of life","Drama","Shoujo"]'
                data-type="mangatoon" data-status="ongoing">

    The cover is a CSS ``background-image``, not an ``<img>``, so it has to be
    pulled out of the inline style.

Chapters
    ``/series/<id>/`` lists every chapter as ``/chapter/<series>-<chapter>/``;
    47 on the series measured, no pagination or AJAX. Coin-locked chapters are
    marked ``id="paid-chapter"`` and are skipped -- their pages are not served.

Images
    The reader ships **placeholders**: every page is
    ``<img src="/assets/images/placeholder.svg" count="0" uid="F_owIXfvX7j">``
    and the real URL is built by their loader as
    ``https://cdn.meowing.org/uploads/${uid}``. Scraping ``src`` gets you six
    copies of an SVG, which is exactly the kind of thing that looks like it
    works. The ``count`` attribute gives the page order.

    The CDN needs no Referer (200 with and without) but answers
    ``Content-Type: text/plain`` for what is really a PNG, so the engine's
    magic-byte sniffing rather than the content-type is what accepts it.
"""

import json
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://writerscans.com"
CDN = "https://cdn.meowing.org/uploads"


class WriterScansSource(Source):
    id = "writerscans"
    name = "Writers' Scans"
    base_url = SITE
    domains = ("writerscans.com", "cdn.meowing.org")

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Title")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue = None

    # ---------------------------------------------------------- helpers

    def _load_catalogue(self):
        """Fetch and parse the whole catalogue once per source instance.

        The site itself does this -- there is no server-side filter -- so a
        single request backs search, browse and genres.
        """
        if self._catalogue is not None:
            return self._catalogue

        try:
            response = self.fetch(f"{SITE}/search_series")
        except ScrapeError as e:
            logger.error("writerscans catalogue failed: %s", e)
            self._catalogue = []
            return self._catalogue

        self._catalogue = self.parse_catalogue(response.text)
        return self._catalogue

    @staticmethod
    def parse_catalogue(html):
        """Parse ``/search_series`` into result dicts."""
        soup = BeautifulSoup(html or "", "html.parser")
        rows = []
        for button in soup.select("button[id]"):
            link = button.select_one('a[href^="/series/"]')
            if link is None:
                continue
            href = urljoin(SITE, link["href"])

            # alt= is the clean English title; title= adds every alias and is
            # what the site's own filter matches against.
            title = (button.get("alt") or "").strip()
            aliases = (button.get("title") or "").strip()
            if not title:
                title = aliases
            if not title:
                continue

            tags = []
            raw = button.get("tags")
            if raw:
                try:
                    tags = [str(t) for t in json.loads(raw)]
                except (TypeError, ValueError):
                    tags = []

            cover = None
            for element in [button] + button.select("[style]"):
                style = element.get("style") or ""
                match = re.search(r"background-image:\s*url\(([^)]+)\)", style)
                if match:
                    cover = match.group(1).strip("'\" ")
                    break

            kind = (button.get("data-type") or "").strip()
            status = (button.get("data-status") or "").strip()

            rows.append({
                "title": title,
                "url": href,
                "cover": cover,
                "aliases": aliases,
                "tags": tags,
                "status": status.title() or None,
                "series_type": classify_type(text=kind, tags=tags),
                "raw_type": kind,
            })
        return rows

    def _to_result(self, row):
        return self._result(
            row["title"], row["url"], cover=row.get("cover"),
            tags=row.get("tags") or [],
            status=row.get("status"),
            series_type=row.get("series_type"),
        )

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        rows = self._load_catalogue()
        query = (query or "").strip().lower()
        if query:
            # Match the aliases too, exactly as the site's own filter does.
            rows = [r for r in rows
                    if query in r["title"].lower()
                    or query in (r.get("aliases") or "").lower()]

        page = max(1, int(page or 1))
        start = (page - 1) * limit
        return [self._to_result(r) for r in rows[start:start + limit]]

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        rows = list(self._load_catalogue())

        if genre:
            wanted = str(genre).strip().lower()
            rows = [r for r in rows
                    if any(wanted == t.strip().lower() for t in r["tags"])]

        if (sort or "").lower() == "title":
            rows.sort(key=lambda r: r["title"].lower())

        page = max(1, int(page or 1))
        start = (page - 1) * limit
        return [self._to_result(r) for r in rows[start:start + limit]]

    def genres(self) -> list:
        """Genres are whatever the catalogue's own tags say."""
        names = {}
        for row in self._load_catalogue():
            for tag in row["tags"]:
                names.setdefault(tag.strip().lower(), tag.strip())
        return [{"id": name, "name": name}
                for _key, name in sorted(names.items())]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        heading = soup.select_one("h1")
        title = heading.get_text(" ", strip=True) if heading else "Unknown"

        cover = None
        meta = soup.select_one('meta[property="og:image"]')
        if meta is not None:
            cover = (meta.get("content") or "").strip() or None

        description = None
        meta = soup.select_one('meta[name="description"]')
        if meta is not None:
            description = re.sub(r"\s+", " ",
                                 (meta.get("content") or "").strip()) or None

        # The catalogue already knows the tags/status/type for this id.
        entry = None
        for row in self._load_catalogue():
            if row["url"].rstrip("/") == manga_url.rstrip("/"):
                entry = row
                break

        return {
            "url": manga_url,
            "title": title,
            "cover": cover or (entry or {}).get("cover"),
            "description": description,
            "tags": (entry or {}).get("tags") or [],
            "status": (entry or {}).get("status"),
            "authors": [],
            "artists": [],
            "series_type": (entry or {}).get("series_type"),
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        chapters, seen = [], set()
        for link in soup.select('a[href^="/chapter/"]'):
            href = urljoin(SITE, link["href"])
            if href in seen:
                continue
            # Coin-locked chapters serve no pages.
            if link.get("id") == "paid-chapter" or \
                    link.find_parent(id="paid-chapter") is not None:
                continue

            name = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            match = re.search(r"(Chapter\s*[\d.]+(?::\s*[^0-9].*?)?)\s*"
                              r"(?:\d+\s+\w+\s+ago|[A-Z][a-z]{2}\s+\d)", name)
            if match:
                name = match.group(1).strip()
            if not name:
                name = href.rstrip("/").rsplit("/", 1)[-1]

            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    @staticmethod
    def parse_pages(html):
        """Rebuild page URLs from the reader's ``uid`` placeholders.

        ``src`` is a placeholder SVG on every page; the real file is
        ``https://cdn.meowing.org/uploads/<uid>``, ordered by ``count``.
        """
        soup = BeautifulSoup(html or "", "html.parser")
        pages = []
        for index, img in enumerate(soup.select("img[uid]")):
            uid = (img.get("uid") or "").strip()
            if not uid:
                continue
            try:
                order = int(img.get("count"))
            except (TypeError, ValueError):
                order = index
            pages.append((order, f"{CDN}/{uid}"))

        pages.sort(key=lambda item: item[0])
        out = []
        for _order, url in pages:
            if url not in out:
                out.append(url)
        return out

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)
        return self.parse_pages(response.text)
