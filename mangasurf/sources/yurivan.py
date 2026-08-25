"""Yurivan (yurivan.com) source scraper for Mangasurf.

.. warning::

   Yurivan is an adult (pornographic) site that gates **every** page behind a client-side Next.js age gate. The
   server only ever ships the age-gate shell for an un-authenticated request -
   no titles, chapter lists or image URLs are present in the HTML we can read.
   This source is therefore *best-effort*: it will discover story URLs from
   the site sitemap, attempt the age-gate confirm, and then parse whatever is
   served. On a network where the age gate cannot be passed it degrades
   gracefully (empty results) rather than raising. Treat it as **unverified**;
   the other adult sources in this package are the reliable path.

Content structure (once the gate is passed) is the site's standard story /
chapter layout: ``/story/<uuid>`` for a series and
``/story/<uuid>/chapter/<n>`` for a chapter, with pages under an image CDN.
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source

logger = logging.getLogger(__name__)

SITE = "https://www.yurivan.com"
SITEMAP = "https://www.yurivan.com/sitemap/0.xml"

#: Plausible age-gate cookies (best-effort; the site may rotate these).
AGE_COOKIES = ("adult=1", "age=1", "age_verified=1", "over18=1",
               "adult_verified=1", "age_confirmed=1", "verified=1",
               "yuriauth=1", "is_adult=1")


class YurivanSource(Source):
    id = "yurivan"
    name = "Yurivan"
    base_url = SITE
    domains = ("yurivan.com", "www.yurivan.com")
    default_series_type = None
    adult_only = True
    needs_flaresolverr = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Relevance",)
    browse_sorts = ("Latest", "Popular")

    GENRES = (
        "Action", "Comedy", "Drama", "Fantasy", "Harem", "Romance",
        "School Life", "Sci-Fi", "Slice of Life", "Supernatural", "Yaoi", "Yuri",
    )

    def headers(self) -> dict:
        h = super().headers()
        h["Referer"] = f"{SITE}/"
        return h

    # ------------------------------------------------------ age gate
    def _prepare(self):
        """Try to pass the age gate so content pages render."""
        for cookie in AGE_COOKIES:
            name, _, value = cookie.partition("=")
            try:
                self.session.cookies.set(name, value, domain="yurivan.com", path="/")
            except Exception:
                pass
        # A confirm pass on the homepage is what the gate button does.
        try:
            self.fetch(SITE, max_retries=1)
        except Exception:
            pass

    def _gated(self, text: str) -> bool:
        return "Age Verification" in text or "age-gate" in text

    def _ensure_open(self, path: str):
        self._prepare()
        resp = self.fetch(urljoin(SITE, path))
        if self._gated(resp.text):
            raise ScrapeError(
                "Yurivan age gate could not be passed in this environment; "
                "content is served client-side."
            )
        return resp

    # --------------------------------------------------------- search
    def search(self, query: str, limit: int = 32, page: int = 1, **__) -> list:
        # The sitemap lists every story; we filter by the query against the
        # slug so the user gets usable results even though titles live inside
        # the gated front-end.
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)
        page = max(1, int(page or 1))
        limit = max(1, int(limit or 32))
        entries = self._sitemap_stories()
        matches = [e for e in entries if query.lower() in e["slug"].replace("-", " ")]
        page_items = matches[(page - 1) * limit: page * limit]
        results = [self._result(e["title"], e["url"]) for e in page_items]
        if page == 1:
            results = self.filter_and_rank(results, query)
        return results[:limit]

    # --------------------------------------------------------- browse
    def browse(self, sort: str = "Latest", genre: str = None, page: int = 1,
               limit: int = 32, **__) -> list:
        page = max(1, int(page or 1))
        limit = max(1, int(limit or 32))
        # Always the same sitemap slice before: every page returned the first
        # new pages after page 1 arrived empty. Slice by page.
        entries = self._sitemap_stories()
        page_items = entries[(page - 1) * limit: page * limit]
        return [self._result(e["title"], e["url"]) for e in page_items]

    # ----------------------------------------------------------- info
    def get_manga_info(self, manga_url: str) -> dict:
        try:
            resp = self._ensure_open(manga_url)
        except ScrapeError:
            return {"url": manga_url, "title": self._title_from_url(manga_url),
                    "cover": None, "description": "", "tags": [], "status": None,
                    "authors": []}
        soup = BeautifulSoup(resp.text, "html.parser")
        title = (soup.find("h1") or soup.find("title"))
        title = (title.get_text(" ", strip=True) if title else "") or self._title_from_url(manga_url)
        og = soup.find("meta", attrs={"property": "og:image"})
        return {"url": manga_url, "title": title,
                "cover": (og.get("content") if og else None),
                "description": "", "tags": [], "status": None, "authors": []}

    # ------------------------------------------------------ chapters
    def get_chapters(self, manga_url: str) -> list:
        try:
            resp = self._ensure_open(manga_url)
        except ScrapeError:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        items, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/chapter/" not in href:
                continue
            full = urljoin(manga_url, href)
            if full in seen:
                continue
            seen.add(full)
            items.append({"url": full, "name": a.get_text(" ", strip=True) or
                          href.rstrip("/").split("/")[-1]})
        items.reverse()
        return items

    # ------------------------------------------------------ images
    def get_chapter_images(self, chapter) -> list:
        url = self._chapter_url(chapter)
        try:
            resp = self._ensure_open(url)
        except ScrapeError:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for img in soup.find_all("img", ):
            src = img.get("data-src") or img.get("src")
            if not src or src.startswith("data:"):
                continue
            if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", src) and \
                    any(k in url.lower() for k in ("yurivan", "cdn")) and src not in urls:
                urls.append(urljoin(url, src))
        return urls

    # --------------------------------------------------------- util
    def _sitemap_stories(self):
        """Unique story URLs from the sitemap (slug -> story url)."""
        try:
            text = self.fetch(SITEMAP, max_retries=1).text
            urls = set(re.findall(r"<loc>([^<]+)</loc>", text))
        except Exception:
            urls = set()
        results, seen = [], set()
        for u in sorted(urls):
            if u not in seen:
                seen.add(u)
                m = re.search(r"/story/([0-9a-fA-F\-]{36})", u)
                if m:
                    results.append({"url": f"{SITE}/story/{m.group(1)}",
                                    "slug": m.group(1), "title": m.group(1)})
        return results

    @staticmethod
    def _title_from_url(url: str) -> str:
        m = re.search(r"/story/([0-9a-fA-F\-]{36})", url or "")
        return m.group(1) if m else (url or "").rstrip("/").split("/")[-1]

    def genres(self) -> list:
        return [{"id": g.lower().replace(" ", "-"), "name": g} for g in self.GENRES]
