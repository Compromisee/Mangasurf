"""nhentai.to source (HTML scraping).

Adult content
    This site hosts adult doujinshi exclusively. Results are stamped with
    ``content_rating: "pornographic"`` and an ``Adult`` tag so the existing
    Safe mode filter removes them, and the source is flagged ``adult_only``
    so the UI shows an 18+ chip and it can be excluded like any other.

Structure
    Search:   ``/search/?q=<term>`` -> ``.gallery`` cards
    Gallery:  ``/g/<id>/``
    Pages:    the gallery page lists thumbnails as ``<gid>/<n>t.jpg``; the
              full-size page is the same path without the ``t`` suffix.
              Verified: ``1t.jpg`` is 21 KB, ``1.jpg`` is 464 KB.

One-shots
    A gallery is a single book, not a series, so it is exposed as a single
    chapter. That keeps it working with the normal download pipeline.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://nhentai.to"

#: "<gallery>/<n>t.<ext>" -> "<gallery>/<n>.<ext>"
_THUMB = re.compile(r"/(\d+)t\.(jpg|jpeg|png|webp|gif)$", re.I)


class NhentaiSource(Source):
    id = "nhentai"
    name = "nhentai"
    base_url = SITE
    domains = ("nhentai.to",)

    #: Catalogue is entirely manga; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manga"

    supports_search = True
    supports_browse = True
    supports_genres = True
    #: everything here is adult
    adult_only = True

    search_sorts = ("Best Match", "Popularity", "Newest")
    browse_sorts = ("Popularity",)

    #: Search accepts ?sort=; browse does not (``/popular-today`` is a 404).
    _SORTS = {
        "Popularity": "popular",
        "Newest": "date",
    }

    #: Real nhentai tag slugs. Measured 2026-07: the previous list was made
    #: up from generic manga genres and 7 of its 12 entries answered 404
    #: ("romance", "drama", "fantasy", "school-life", "vanilla",
    #: "historical", "sci-fi"), so every genre browse returned nothing.
    #: Every slug below was verified to return 25 galleries.
    GENRES = (
        "big-breasts", "sole-female", "sole-male", "nakadashi", "anal",
        "glasses", "stockings", "full-color", "schoolgirl-uniform", "milf",
        "ahegao", "yuri", "yaoi", "netorare", "harem", "comedy",
    )

    def headers(self):
        h = super().headers()
        h["Referer"] = SITE + "/"
        return h

    # ---------------------------------------------------------- helpers

    @staticmethod
    def full_size(url):
        """Turn a thumbnail URL into its full-size page."""
        return _THUMB.sub(r"/\1.\2", url or "")

    @staticmethod
    def _fallbacks(img, cover):
        """Cover URLs to try, best first.

        Cards carry ``data-fallbacks='["...", ...]'`` -- a JSON list the site
        itself walks when a thumbnail 404s. Covers live on a separate CDN
        (``zrocdn.xyz``) whose per-gallery files are not always present, so
        honouring the list is what stops empty tiles.
        """
        candidates = []
        if cover:
            candidates.append(cover)
        raw = (img.get("data-fallbacks") or "").strip()
        if raw:
            try:
                for url in json.loads(raw):
                    url = (url or "").strip()
                    if url and url not in candidates:
                        candidates.append(url)
            except (TypeError, ValueError):
                logger.debug("nhentai: unparsable data-fallbacks")
        return candidates

    def _cards(self, soup, limit):
        results, seen = [], set()
        for card in soup.select(".gallery, .gallery-favorite"):
            link = card.select_one("a[href*='/g/']")
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            if href in seen:
                continue

            caption = card.select_one(".caption")
            title = (caption.get_text(" ", strip=True) if caption
                     else link.get("title") or "").strip()
            if not title:
                continue

            img = card.select_one("img")
            cover, mirrors = None, []
            if img is not None:
                cover = (img.get("data-src") or img.get("src") or "").strip()
                if cover:
                    cover = urljoin(SITE, cover)
                # The site ships its own ordered fallback list on the tag and
                # swaps to it in an onerror handler, so reuse it rather than
                # guessing: thumb.webp, then the first page, then its webp.
                mirrors = self._fallbacks(img, cover)

            seen.add(href)
            results.append(self._result(
                title, href, cover=cover,
                cover_mirrors=mirrors,
                content_rating="pornographic",
                tags=["Adult"],
                adult=True,
            ))
            if len(results) >= limit:
                break
        return results

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, sort=None, genre=None, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(sort=sort, genre=genre, limit=limit)
        url = f"{SITE}/search/?q={quote(query)}"
        order = self._SORTS.get(sort or "")
        if order:
            url += f"&sort={order}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("nhentai search failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, **_):
        """Discovery listing.

        The site root is a landing page carrying **zero** ``.gallery`` cards
        (measured), so browsing it always came back empty. ``/popular`` is
        the real listing and pages with ``?page=N``.
        """
        page = max(1, int(page or 1))
        slug = str(genre or "").strip().lower().replace(" ", "-")
        # Genre labels are merged across sources, so this source is regularly
        # handed a tag it does not have ("action", "romance"). Those return a
        # hard 404, which burned four retries and logged an error every time.
        # Fall back to the search index, which does understand the word.
        if slug and slug in self.GENRES:
            url = f"{SITE}/tag/{quote(slug)}/?page={page}"
        elif slug:
            url = f"{SITE}/search/?q={quote(slug)}&page={page}"
        else:
            url = f"{SITE}/popular?page={page}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("nhentai browse failed: %s", e)
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

        heading = soup.select_one("#info h1, h1.title")
        title = (re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
                 if heading else "Unknown")

        cover = None
        cover_img = soup.select_one("#cover img")
        if cover_img is not None:
            cover = (cover_img.get("data-src") or cover_img.get("src") or "")
            cover = urljoin(SITE, cover) if cover else None

        tags = ["Adult"]
        for tag in soup.select(".tag-container a.tag .name, a.tag .name"):
            label = tag.get_text(strip=True)
            if label and label not in tags:
                tags.append(label)

        artists = [a.get_text(strip=True)
                   for a in soup.select('.tag-container:-soup-contains("Artists") a .name')
                   if a.get_text(strip=True)]

        pages = None
        match = re.search(r"(\d+)\s*pages?", soup.get_text(" ", strip=True), re.I)
        if match:
            pages = int(match.group(1))

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": None,
            "tags": tags[:20],
            "status": "Completed",       # a doujinshi is a finished book
            "authors": artists[:3],
            "artists": artists[:3],
            "pages": pages,
            "content_rating": "pornographic",
            "adult": True,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        """A gallery is one book, so it is a single chapter."""
        manga_url = self.normalize_url(manga_url)
        return [{
            "url": manga_url,
            "name": "Chapter 1",
            "referer": manga_url,
            "source": self.id,
        }]

    # ------------------------------------------------------------ pages

    def get_chapter_images(self, chapter) -> list:
        gallery_url = self.normalize_url(self._chapter_url(chapter))
        if not gallery_url:
            return []
        response = self.fetch(gallery_url)
        soup = BeautifulSoup(response.content, "html.parser")

        urls, seen = [], set()
        for img in soup.select(".thumb-container img, #thumbnail-container img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src:
                continue
            full = self.full_size(urljoin(SITE, src))
            if full not in seen:
                seen.add(full)
                urls.append(full)

        if not urls:
            raise ScrapeError(f"No pages found for {gallery_url}")
        return urls
