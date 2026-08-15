"""Manga18.club source (HTML scraping + a small JSON search API).

Notes from probing the live site (2026-07):

Search
    Two obvious candidates are decoys. ``/?s=<term>`` returns the homepage
    grid, and ``/list-manga?q=<term>`` returns the same 20 titles for every
    query ("naruto", "dirty" and "love" all gave the identical list) -- the
    ``q`` parameter is simply ignored.

    The header form posts ``search``, not ``q``, and there are two real
    endpoints:

    * ``/list-manga?search=<term>`` -- full HTML page of ``.story_item``
      cards, genuinely filtered (``?search=naruto`` correctly returned 0).
    * ``/search?search=<term>`` -- the autocomplete JSON the site's own
      jQuery UI widget calls: ``{"status":0,"data":[{id,name,slug,
      otherNames,cover_url}]}``. Capped at 10 rows.

    The HTML page is used because it returns more rows and carries the
    latest-chapter labels; the JSON is used as a fallback when the HTML
    layout returns nothing.

Chapters
    ``.chapter_box a.chapter_num`` -> ``/manhwa/<slug>/chapter-N``.

Images
    The reader ships **no** usable ``<img>`` tags: the markup holds one
    placeholder (``/1.jpg``) and the real pages are injected by an obfuscated
    script. The payload is ``slides_p_path``, an array of base64 strings each
    decoding to a full CDN URL, e.g.
    ``https://cdn.manga18.club/manga/<slug>/chapters/<chapter>/01.jpg``.
    Decoding it here avoids needing a browser -- confirmed against a real
    Chromium run, which requested exactly the same 11 URLs.

    Measured: the CDN hotlinks fine (200 and the identical 1,172,335 bytes
    with and without a Referer).
"""

import base64
import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://manga18.club"

#: ``var slides_p_path = ["<base64>", ...]`` -- the reader's page list.
_SLIDES = re.compile(r"slides_p_path\s*=\s*(\[[^\]]*\])")
_B64 = re.compile(r"[\"']([A-Za-z0-9+/=]{8,})[\"']")


class Manga18ClubSource(Source):
    id = "manga18club"
    name = "Manga18.club"
    base_url = SITE
    domains = ("manga18.club", "cdn.manga18.club")

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True
    #: Adult-only site; stamped so Safe mode filters it and the UI shows 18+.
    adult_only = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Trending")

    GENRES = (
        "action", "adult", "adventure", "comedy", "drama", "ecchi",
        "fantasy", "harem", "historical", "horror", "josei", "manhua",
        "manhwa", "martial-arts", "mature", "mecha", "mystery",
        "psychological", "romance", "school-life", "sci-fi", "seinen",
        "shoujo", "shounen", "slice-of-life", "smut", "sports",
        "supernatural", "thriller", "tragedy", "webtoon", "yaoi", "yuri",
        "18",
    )

    # ---------------------------------------------------------- helpers

    def _cards(self, soup, limit):
        """Parse a ``.story_item`` grid. Shared by search, browse and genres."""
        results, seen = [], set()
        for card in soup.select(".story_item"):
            link = card.select_one(".mg_name a") or card.select_one("a[href]")
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            if href in seen:
                continue

            title = (link.get_text(" ", strip=True)
                     or link.get("title") or "").strip()
            if not title:
                continue

            cover = None
            img = card.select_one("img")
            if img is not None:
                cover = (img.get("data-src") or img.get("src") or "").strip()
                if cover:
                    cover = urljoin(SITE, cover)

            latest = None
            chapter = card.select_one(".chapter_count a")
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

    def _search_json(self, query, limit):
        """Autocomplete API fallback: ``/search?search=`` -> JSON, max 10."""
        try:
            payload = self.fetch_json(
                f"{SITE}/search?search={quote(query)}",
                headers={"X-Requested-With": "XMLHttpRequest",
                         "Accept": "application/json"})
        except (ScrapeError, ValueError) as e:
            logger.debug("manga18club json search failed: %s", e)
            return []

        results = []
        for row in (payload or {}).get("data") or []:
            slug = (row.get("slug") or "").strip()
            name = (row.get("name") or "").strip()
            if not slug or not name:
                continue
            results.append(self._result(
                name, f"{SITE}/manhwa/{slug}",
                cover=(row.get("cover_url") or "").strip() or None,
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

        # ``search``, not ``q`` -- ``?q=`` is ignored and returns everything.
        page = max(1, int(page or 1))
        url = f"{SITE}/list-manga?search={quote(query)}"
        if page > 1:
            url += f"&page={page}"
        try:
            response = self.fetch(url)
            results = self._cards(
                BeautifulSoup(response.content, "html.parser"), limit)
        except ScrapeError as e:
            logger.error("manga18club search failed: %s", e)
            results = []

        # Fall back to the autocomplete API if the grid layout changed.
        if not results and page == 1:
            results = self._search_json(query, limit)
        return results

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            url = f"{SITE}/manga-list/{quote(slug)}"
            if page > 1:
                url += f"?page={page}"
        else:
            url = f"{SITE}/latest-release/{page}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("manga18club browse failed: %s", e)
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

        heading = soup.select_one("h1")
        title = heading.get_text(" ", strip=True) if heading else "Unknown"

        # ``.detail_avatar img`` is the series cover. Do NOT fall back to
        # ``.story_images img``: that is the "you may also like" sidebar and
        # it appears *before* nothing useful -- measured, it returned another
        # series' artwork ("my-girlfriend-was-already-fully-trained-raw") on
        # the Dirty Talk page. The og:image meta is a reliable second choice.
        cover = None
        img = soup.select_one(".detail_avatar img, .book_avatar img")
        if img is not None:
            cover = (img.get("data-src") or img.get("src") or "").strip()
        if not cover:
            meta = soup.select_one('meta[property="og:image"]')
            cover = (meta.get("content") or "").strip() if meta else ""
        cover = urljoin(SITE, cover) if cover else None

        description = None
        block = soup.select_one(".story-detail-info, .summary_content, "
                                ".detail_reviewContent, .man-content")
        if block is not None:
            description = re.sub(r"\s+", " ",
                                 block.get_text(" ", strip=True)) or None

        tags = ["Adult"]
        for link in soup.select('a[href*="/manga-list/"]'):
            label = link.get_text(strip=True)
            if label and label not in tags:
                tags.append(label)

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
            "authors": [],
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

        series_path = self.series_path(manga_url)
        chapters, seen = [], set()

        for link in soup.select('.chapter_box a[href*="/chap"]'):
            href = urljoin(SITE, link.get("href") or "")
            path = re.sub(r"^https?://[^/]+", "", href)
            if not path.startswith(series_path + "/"):
                continue
            if href in seen:
                continue
            name = link.get_text(" ", strip=True)
            if not name:
                name = path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        def sort_key(entry):
            match = re.search(r"chap(?:ter)?-(\d+(?:[-.]\d+)?)",
                              entry["url"], re.I)
            if not match:
                return (1, 0.0)
            return (0, float(match.group(1).replace("-", ".", 1).replace("-", "")))

        chapters.sort(key=sort_key)
        return chapters

    # ----------------------------------------------------------- images

    @staticmethod
    def decode_slides(html):
        """Decode the reader's base64 ``slides_p_path`` array into URLs."""
        match = _SLIDES.search(html or "")
        if not match:
            return []
        images = []
        for token in _B64.findall(match.group(1)):
            try:
                url = base64.b64decode(token).decode("utf-8", "replace").strip()
            except (ValueError, TypeError):
                continue
            if url.startswith(("http://", "https://")) and url not in images:
                images.append(url)
        return images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)
        html = response.text

        images = self.decode_slides(html)
        if images:
            return images

        # Fallback: a plain DOM read, in case the site ever stops obfuscating.
        soup = BeautifulSoup(response.content, "html.parser")
        for img in soup.select("#chapter_boxImages img, .chapter_boxImages img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src:
                continue
            src = urljoin(SITE, src)
            # the placeholder the page ships before the script runs
            if src.rstrip("/").endswith("manga18.club/1.jpg"):
                continue
            if src not in images:
                images.append(src)
        return images
