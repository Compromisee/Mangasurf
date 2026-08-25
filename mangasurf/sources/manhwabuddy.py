"""ManhwaBuddy (manhwabuddy.com) source scraper for Mangasurf.

Custom (non-Madara) Korean-manhwa reader. Verified live (2026-08):
- search   ``/search/?s=<q>`` -> series cards ``/manhwa/<slug>/``
- browse   homepage ``/`` lists recent series as ``/manhwa/<slug>/`` cards
- series   ``/manhwa/<slug>/`` -> chapters in a list of relative hrefs
           ``/manhwa/<slug>/chapter-<n>/``
- pages    chapter page ``img[data-src]`` on ``img01.manhwabuddy.com``
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source

logger = logging.getLogger(__name__)

SITE = "https://manhwabuddy.com"


class ManhwaBuddySource(Source):
    id = "manhwabuddy"
    name = "ManhwaBuddy"
    base_url = SITE
    domains = ("manhwabuddy.com", "img01.manhwabuddy.com", "img02.manhwabuddy.com")

    supports_search = True
    supports_browse = True
    supports_genres = True
    default_series_type = "Manhwa"
    adult_only = False

    search_sorts = ("Relevance",)
    browse_sorts = ("Latest",)

    GENRES = (
        "Action", "Adult", "Comedy", "Drama", "Fantasy", "Harem", "Isekai",
        "Romance", "Seinen", "Shounen", "Slice of Life", "Supernatural",
    )

    def genres(self) -> list:
        return [{"id": g.lower().replace(" ", "-"), "name": g} for g in self.GENRES]

    def headers(self) -> dict:
        h = super().headers()
        h.update({"Referer": f"{SITE}/"})
        return h

    # ------------------------------------------------------ card parsing
    @staticmethod
    def _series_links(soup):
        """Return unique series URLs harvested from the real content grid.

        Scoped to ``.latest-list`` (the paginated "Latest Update" grid). The
        ``.move.owl-carousel`` "Popular Manhwa" widget re-serves the same
        trending titles on *every* page, so harvesting those too means later
        pages only yield a handful of genuinely-unseen series. Dropping the
        widget keeps each page's content distinct (measured p2 -> 23 new,
        p3 -> 24 new).
        """
        seen, out = set(), []
        grid = soup.select_one(".latest-list")
        anchors = (grid.find_all("a", href=True) if grid is not None
                   else soup.find_all("a", href=True))
        for a in anchors:
            href = a["href"]
            if re.fullmatch(r"/manhwa/[^/]+/", href) and href not in seen:
                seen.add(href)
                out.append(a)
        return out

    @staticmethod
    def _card(a):
        url = urljoin(SITE, a["href"])
        title = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        cover = None
        img = a.find("img") or (a.find_parent("div").find("img") if a.find_parent("div") else None)
        if img is not None:
            cover = img.get("src") or img.get("data-src") or img.get("data-original")
        return url, title, cover

    # --------------------------------------------------------- search
    def search(self, query: str, limit: int = 32, page: int = 1, **__) -> list:
        query = (query or "").strip()
        page = max(1, int(page or 1))
        if not query:
            return self.browse(limit=limit, page=page)
        # ``?page=`` is ignored by the site; pagination lives in the path:
        # ``/page/<n>/?s=<q>`` (verified: /search/?s=&page=2 repeats the same
        # 24 results, while /page/2/?s= returns 24 entirely-new ones).
        if page > 1:
            resp = self.fetch(f"{SITE}/page/{page}/", params={"s": query})
        else:
            resp = self.fetch(f"{SITE}/search/", params={"s": query})
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for a in self._series_links(soup):
            url, title, cover = self._card(a)
            if not title or "/chapter-" in url:
                continue
            results.append(self._result(title, url, cover=cover))
            if len(results) >= limit:
                break
        return self.filter_and_rank(results, query)

    # --------------------------------------------------------- browse
    def browse(self, sort: str = "Latest", genre: str = None, page: int = 1,
               limit: int = 32, **__) -> list:
        page = max(1, int(page or 1))
        url = f"{SITE}/" if page <= 1 else f"{SITE}/page/{page}/"
        resp = self.fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for a in self._series_links(soup):
            u, title, cover = self._card(a)
            if not title or "/chapter-" in u:
                continue
            results.append(self._result(title, u, cover=cover))
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------ info
    def get_manga_info(self, manga_url: str) -> dict:
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        title = (soup.find("h1") or soup.find("title"))
        title = (title.get_text(" ", strip=True) if title else "") or manga_url.rstrip("/").split("/")[-1]
        cover = None
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            cover = og["content"]
        desc = ""
        d = soup.find("meta", attrs={"name": "description"})
        if d and d.get("content"):
            desc = d["content"]
        return {"url": manga_url, "title": title, "cover": cover,
                "description": desc, "tags": [], "status": None, "authors": []}

    # ------------------------------------------------------ chapters
    def get_chapters(self, manga_url: str) -> list:
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        slug = manga_url.rstrip("/").split("/")[-1]
        items, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if f"/manhwa/{slug}/" not in href or "/chapter-" not in href:
                continue
            full = urljoin(manga_url, href)
            if full in seen:
                continue
            seen.add(full)
            name = a.get("title") or a.get_text(" ", strip=True) or href.rsplit("/", 2)[-2]
            items.append({"url": full, "name": name})
        items = [c for c in items if c["name"].strip()]
        items.reverse()   # newest-first is what the server renders
        return items

    # ------------------------------------------------------ images
    def get_chapter_images(self, chapter) -> list:
        url = self._chapter_url(chapter)
        resp = self.fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for img in soup.find_all("img", attrs={"data-src": True}):
            src = img["data-src"]
            if src.startswith("data:"):
                continue
            src = urljoin(url, src)
            if self._is_page_asset(src) and src not in urls:
                urls.append(src)
        if not urls:
            for img in soup.find_all("img", src=True):
                src = img["src"]
                if self._is_page_asset(src):
                    urls.append(src)
        return urls

    @staticmethod
    def _is_page_asset(url: str) -> bool:
        return bool(re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", url))
