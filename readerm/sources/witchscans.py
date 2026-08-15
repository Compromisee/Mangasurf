"""Witch Scans source (HTML scraping of witchscans.com).

Notes from probing the live site (2026-07):

Theme
    A WordPress build of the Themesia/Mangastream theme -- the same family as
    HentaiAkane, so the card and reader markup is shared. ``<meta generator>``
    reports "WordPress 7.0" with ``themes/mangareader-child``.

Search
    ``/?s=<term>`` genuinely filters (measured: ``?s=martial`` returned 10
    cards, ``?s=diner`` returned exactly one -- "Afterlife Diner"). Page two
    is ``/page/<n>/?s=<term>``.

    ``/manga/?title=<term>`` filters identically and is what the site's own
    form posts, but the plain ``?s=`` form pages more predictably.

Browse
    ``/manga/?order=<update|popular|title>``, 20 cards a page, page two via
    ``?page=2`` (verified: a different first title).

Genres
    ``/genres/<slug>/`` -- plural. ``/genre/<slug>/`` is a hard 404.

    The slugs are **not** the usual clean words. This site's taxonomy carries
    emoji, which WordPress percent-encodes into the slug, so the real paths
    include ``action-%e2%9a%94%ef%b8%8f`` (Action ⚔️),
    ``cultivation-%f0%9f%a7%98%e2%99%82%ef%b8%8f`` (Cultivation 🧘‍♂️),
    ``harem-%e2%9d%a4%ef%b8%8f%f0%9f%94%a5`` and ``system-%e2%9a%99%ef%b8%8f``.
    Guessing the plain words gets you a 404 for four of them, and the plain
    ``action`` slug also exists but holds a *different, smaller* set (7 vs 10
    titles), so both are kept. Every slug in ``GENRES`` was fetched and
    confirmed 200 with cards; ``school-life``, ``sci-fi``, ``seinen``,
    ``slice-of-life``, ``tragedy``, ``webtoon``, ``psychological``,
    ``villainess``, ``reincarnation`` and ``regression`` all 404 here and are
    deliberately absent.

Chapters
    ``#chapterlist li a`` -> ``/<series-slug>-chapter-N/`` at the site root,
    not under ``/manga/``. The link text carries the release date, so the
    chapter number is extracted.

Images
    ``ts_reader.run({...})`` holds the ordered page list (9 images on the
    chapter measured); ``#readerarea img`` is empty because the reader
    injects them, so the JSON is the only reliable source. Pages are served
    from the site's own ``/wp-content/uploads/`` and hotlink fine (200,
    image/jpeg, no Referer). Covers come through the Jetpack CDN
    (``i2.wp.com``), which also needs no Referer.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://witchscans.com"

#: ``ts_reader.run({... "sources":[{"images":[...]}] ...})``
_TS_READER = re.compile(r"ts_reader\.run\((\{.*?\})\);", re.S)


class WitchScansSource(Source):
    id = "witchscans"
    name = "Witch Scans"
    base_url = SITE
    domains = ("witchscans.com",)

    #: Catalogue is overwhelmingly manhua, but cards carry their own type
    #: (``.type Manhua`` / ``.type Manhwa``) so this is only a fallback.
    default_series_type = "Manhua"

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

    #: Every slug here was fetched and returned 200 with cards. The
    #: percent-encoded ones are emoji taxonomies -- see the module docstring.
    GENRES = (
        ("action", "Action"),
        ("action-%e2%9a%94%ef%b8%8f", "Action \u2694\ufe0f"),
        ("adventure", "Adventure"),
        ("comedy", "Comedy"),
        ("cultivation-%f0%9f%a7%98%e2%99%82%ef%b8%8f", "Cultivation"),
        ("drama", "Drama"),
        ("ecchi", "Ecchi"),
        ("fantasy", "Fantasy"),
        ("harem-%e2%9d%a4%ef%b8%8f%f0%9f%94%a5", "Harem"),
        ("historical", "Historical"),
        ("horror", "Horror"),
        ("isekai", "Isekai"),
        ("magic", "Magic"),
        ("martial-arts", "Martial Arts"),
        ("murim", "Murim"),
        ("mystery", "Mystery"),
        ("romance", "Romance"),
        ("shounen", "Shounen"),
        ("supernatural", "Supernatural"),
        ("system-%e2%9a%99%ef%b8%8f", "System"),
    )

    # ---------------------------------------------------------- helpers

    def _cards(self, soup, limit):
        """Parse a ``.bs`` grid. Shared by search, browse and genres."""
        results, seen = [], set()
        for card in soup.select(".bs"):
            link = card.select_one("a[href]")
            if link is None or not link.get("href"):
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

            # Cards label the type themselves: <span class="type Manhua">.
            series_type = None
            type_span = card.select_one(".type")
            if type_span is not None:
                for name in type_span.get("class") or []:
                    if name.lower() != "type":
                        series_type = classify_type(text=name)
                        break

            latest = None
            chapter = card.select_one(".epxs")
            if chapter is not None:
                latest = chapter.get_text(" ", strip=True) or None

            seen.add(href)
            results.append(self._result(
                title, href, cover=cover,
                latest=latest,
                series_type=series_type or self.default_series_type,
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
            logger.error("witchscans search failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._ORDER.get(sort or "", "update")
        if genre:
            base = f"{SITE}/genres/{self._genre_slug(genre)}/"
        else:
            base = f"{SITE}/manga/"
        url = f"{base}?page={page}&order={order}" if page > 1 \
            else f"{base}?order={order}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("witchscans browse failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    @classmethod
    def _genre_slug(cls, genre) -> str:
        """Map a genre name back to its (possibly emoji) slug."""
        wanted = str(genre or "").strip().lower()
        for slug, label in cls.GENRES:
            if wanted in (slug.lower(), label.lower()):
                return slug
        # Unknown name: slugify it and let the site answer.
        return quote(wanted.replace(" ", "-"))

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

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
        block = soup.select_one('[itemprop="description"], .entry-content')
        if block is not None:
            description = re.sub(r"\s+", " ",
                                 block.get_text(" ", strip=True)) or None

        tags = [a.get_text(strip=True) for a in soup.select(".mgen a")
                if a.get_text(strip=True)]

        # .tsinfo rows read "Status Ongoing", "Type Manhwa", "Author ...".
        info = {}
        for row in soup.select(".tsinfo .imptdt"):
            text = row.get_text(" ", strip=True)
            match = re.match(r"([A-Za-z ]+?)\s+(.+)", text)
            if match:
                info[match.group(1).strip().lower()] = match.group(2).strip()

        status = info.get("status")
        if status:
            status = status.title()

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:20],
            "status": status,
            "authors": [info[k] for k in ("author", "author(s)") if info.get(k)],
            "artists": [info[k] for k in ("artist", "artist(s)") if info.get(k)],
            "series_type": classify_type(tags=tags, text=info.get("type"))
            or self.default_series_type,
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
            # The raw text carries the release date too; keep the number.
            name = re.sub(r"\s+", " ", name)
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
            logger.debug("witchscans: unparsable ts_reader payload")
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
