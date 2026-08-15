"""MangaDemon / Demonic Scans source (demonicscans.org).

A hand-written PHP site -- no theme, no JSON API -- so every endpoint here was
found by probing. Notes from 2026-07:

Search
    ``GET /search.php?manga=<term>`` returns an **HTML fragment**, not a
    page: a bare list of ``<a href="/manga/Slug"><li>…</li></a>`` blocks with
    the cover and the view count. It is the site's live-search backend.
    A query matching nothing returns a single newline (1 byte), which is a
    valid empty result rather than a failure.

    ``/index.php?search=`` and ``/api/search`` are not search: the first
    returns the homepage, the second 404s.

Browse
    ``GET /advanced.php?list=<n>`` -- ``list`` is the page number, and pages
    genuinely differ (page 1 and page 2 shared **0** of 55/56 entries).
    ``orderby`` accepts ``VIEWS DESC``, ``ID DESC`` and ``NAME ASC``.

    ``/lastupdates.php?list=<n>`` is the latest-updates feed.

Genres
    Checkboxes named ``genres[]`` carrying **numeric ids**, not slugs --
    Action is ``1``, Martial Arts ``6``, Murim ``36``. The 36 pairs are read
    off the form and hardcoded below.

    Genre filtering only works over **POST**: measured, a GET with
    ``?genres[]=6`` returned the same 55 rows as no filter at all (55 of 55
    identical), while the POST returned 56 rows sharing **0** with the
    unfiltered set. A GET-based genre filter would have looked like it worked
    and quietly returned the unfiltered catalogue.

Series
    ``/manga/<Slug>`` -- note the slug is Title-Cased with hyphens, and some
    titles are **double** percent-encoded in the site's own links
    (``Past%25252DLife-Demon``). Those URLs are passed through unchanged
    because the site resolves them; re-encoding or decoding breaks them.

    Chapters are ``#chapters-list a`` -> ``/chaptered.php?manga=<id>&chapter=N``.
    A "Read First Chap" button outside the list points at chapter 1 as well,
    so links are scoped to ``#chapters-list`` (measured: 416 anchors on the
    page, 415 in the list).

Images
    ``img.imgholder`` on the chapter page, served from ``mangathird.org``.
    The first ``.imgholder`` is an ad banner (``/img/free_ads.jpg``) and is
    skipped by requiring an absolute URL. The CDN hotlinks fine (200,
    image/webp, no Referer). Covers live on ``readermc.org`` and contain
    literal spaces, which requests handles.
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source

logger = logging.getLogger(__name__)

SITE = "https://demonicscans.org"


class DemonicScansSource(Source):
    id = "demonicscans"
    name = "Demonic Scans"
    base_url = SITE
    domains = ("demonicscans.org", "readermc.org", "mangathird.org")

    #: Predominantly Korean manhwa, but the catalogue holds manga and manhua
    #: too, so this is only a fallback for entries with no type of their own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Popularity", "Latest Updates", "Title")

    _ORDER = {
        "Popularity": "VIEWS DESC",
        "Trending": "VIEWS DESC",
        "Latest Updates": "ID DESC",
        "Title": "NAME ASC",
    }

    #: name -> numeric id, read off the ``genres[]`` checkboxes on
    #: /advanced.php. The site filters on the id; the name means nothing to it.
    GENRE_IDS = {
        "Action": 1, "Adventure": 2, "Comedy": 3, "Cooking": 34,
        "Doujinshi": 25, "Drama": 4, "Ecchi": 19, "Fantasy": 5,
        "Gender Bender": 30, "Harem": 10, "Historical": 28, "Horror": 8,
        "Isekai": 33, "Josei": 31, "Martial Arts": 6, "Mature": 22,
        "Mecha": 32, "Murim": 36, "Mystery": 15, "One Shot": 26,
        "Our Translation": 35, "Psychological": 11, "Romance": 12,
        "School Life": 13, "Sci-fi": 16, "Seinen": 17, "Shoujo": 14,
        "Shoujo Ai": 23, "Shounen": 7, "Shounen Ai": 29,
        "Slice of Life": 21, "Smut": 27, "Sports": 20, "Supernatural": 9,
        "Tragedy": 18, "Webtoons": 24,
    }

    # ---------------------------------------------------------- helpers

    def _cards(self, soup, limit):
        """Parse ``/manga/`` anchors out of a listing or search fragment."""
        results, seen = [], set()
        for link in soup.select('a[href^="/manga/"]'):
            href = link.get("href") or ""
            if href in ("/manga/", "/manga"):
                continue
            full = urljoin(SITE, href)
            if full in seen:
                continue

            img = link.select_one("img")
            cover = None
            if img is not None:
                cover = (img.get("src") or img.get("data-src") or "").strip()
                if cover:
                    cover = urljoin(SITE, cover)

            # Listing anchors carry the title in a div; the view count sits in
            # a sibling div, so the anchor text is "Title 12533339".
            title = ""
            for div in link.select("div"):
                text = div.get_text(" ", strip=True)
                if text and not re.fullmatch(r"[\d,.]+[KM]?", text):
                    title = text
                    break
            if not title:
                title = link.get("title") or link.get_text(" ", strip=True)
            title = re.sub(r"\s*\b\d{4,}\b\s*$", "", title).strip()
            # Long titles are ellipsised in the grid; fall back to the slug.
            if not title or title.endswith("..."):
                slug = href.rsplit("/", 1)[-1]
                title = self._slug_title(slug) or title
            if not title:
                continue

            seen.add(full)
            results.append(self._result(
                title, full, cover=cover,
                series_type=self.default_series_type,
            ))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _slug_title(slug: str) -> str:
        """Best-effort title from a (possibly double-encoded) slug."""
        from urllib.parse import unquote

        text = unquote(unquote(slug or ""))
        return re.sub(r"\s+", " ", text.replace("-", " ")).strip()

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        try:
            response = self.fetch(f"{SITE}/search.php?manga={quote(query)}")
        except ScrapeError as e:
            logger.error("demonicscans search failed: %s", e)
            return []
        # A no-match query answers with a single newline -- not an error.
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Popularity", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._ORDER.get(sort or "", "VIEWS DESC")

        try:
            if genre:
                # Genre filtering is POST-only: over GET the site ignores it
                # and returns the unfiltered catalogue.
                genre_id = self.genre_id(genre)
                if genre_id is None:
                    return []
                response = self.session.post(
                    f"{SITE}/advanced.php?list={page}",
                    data=[("genres[]", str(genre_id)),
                          ("status", "all"),
                          ("orderby", order)],
                    timeout=25,
                )
                response.raise_for_status()
            else:
                response = self.fetch(
                    f"{SITE}/advanced.php?list={page}"
                    f"&status=all&orderby={quote(order)}"
                )
        except Exception as e:
            logger.error("demonicscans browse failed: %s", e)
            return []

        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    @classmethod
    def genre_id(cls, genre):
        """Numeric id for a genre name (case-insensitive), or None."""
        wanted = str(genre or "").strip().lower()
        for name, number in cls.GENRE_IDS.items():
            if wanted in (name.lower(), str(number)):
                return number
        return None

    def genres(self) -> list:
        return [{"id": name, "name": name} for name in sorted(self.GENRE_IDS)]

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
        block = soup.select_one("#manga-info-rightColumn .white-font, "
                                ".white-font")
        if block is not None:
            description = re.sub(r"\s+", " ",
                                 block.get_text(" ", strip=True)) or None

        tags = [a.get_text(strip=True) for a in soup.select(".genres-list a, "
                                                            ".genres-list li")
                if a.get_text(strip=True)]

        # #manga-info-stats renders label/value as alternating children.
        stats, cells = {}, [li.get_text(" ", strip=True)
                            for li in soup.select("#manga-info-stats li div")]
        for index in range(0, len(cells) - 1, 2):
            stats[cells[index].strip().lower()] = cells[index + 1].strip()

        status = stats.get("status")
        author = stats.get("author")

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:20],
            "status": status.title() if status else None,
            "authors": [author] if author and author.upper() != "N/A" else [],
            "artists": [],
            "series_type": self.default_series_type,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        chapters, seen = [], set()
        # Scoped to the list: a "Read First Chap" button outside it points at
        # chapter 1 and would duplicate it under a junk name.
        for link in soup.select('#chapters-list a[href*="chaptered.php"]'):
            href = urljoin(SITE, link.get("href") or "")
            if not href or href in seen:
                continue
            name = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            # The label carries the release date: "Chapter 411 2026-07-28".
            name = re.sub(r"\s*\d{4}-\d{2}-\d{2}\s*$", "", name).strip()
            if not name:
                match = re.search(r"chapter=([\d.]+)", href)
                name = f"Chapter {match.group(1)}" if match else href
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

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)
        soup = BeautifulSoup(response.content, "html.parser")

        images = []
        for img in soup.select("img.imgholder"):
            src = (img.get("src") or img.get("data-src") or "").strip()
            # The first .imgholder is a relative ad banner (/img/free_ads.jpg);
            # real pages are absolute CDN URLs.
            if not src.startswith(("http://", "https://")):
                continue
            if src not in images:
                images.append(src)
        return images
