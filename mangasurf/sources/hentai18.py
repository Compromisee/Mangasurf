"""Hentai18 (hentai18.net) source scraper for Mangasurf.

Adult (18+) hentai / manhwa reader (pornographic adult content, gated by Safe mode). Verified live (2026-08):
- search   ``/search?s=<q>`` -> series cards ``/read-hentai/<slug>``
- series   ``/read-hentai/<slug>`` -> chapters in ``ul.chapter-list`` with
           hrefs ``/read-hentai/<slug>-ch<n>-<id>`` or ``<slug>-oneshot-ch<id>``
- pages    chapter page ``cdn.hentai18.net/images/manga/<slug>/<chapter>/N.jpg``
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Source

logger = logging.getLogger(__name__)

SITE = "https://hentai18.net"


class Hentai18Source(Source):
    id = "hentai18"
    name = "Hentai18"
    base_url = SITE
    domains = ("hentai18.net", "cdn.hentai18.net", "static.hentai18.net")

    supports_search = True
    supports_browse = True
    supports_genres = True
    default_series_type = None
    adult_only = True

    search_sorts = ("Relevance",)
    browse_sorts = ("Latest", "Popular")

    GENRES = (
        "Comedy", "Couple", "Cream", "Drama", "Fantasy", "Femdom", "Full Color",
        "Harem", "Mature", "Milf", "Netorare", "NTR", "Romance", "Schoolgirl",
        "Sci-Fi", "Solo Female", "Solo Male", "Stockings", "Tentacle", "Yaoi",
        "Yuri",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({"Referer": f"{SITE}/"})
        return h

    # --------------------------------------------------------- search
    def search(self, query: str, limit: int = 32, **__) -> list:
        url = f"{SITE}/search?s={query.strip()}"
        resp = self.fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        results, seen = [], set()
        series, chapters = [], []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            clean = href.split("#")[0].split("?")[0]
            # The series cards carry absolute URLs (https://hentai18.net/read-
            # hentai/<slug>) while sidebar/related rows use relative paths; a
            # regex that only matched relative paths silently dropped every
            # real series result, leaving only the oneshot/chapter label rows.
            path = re.sub(r"^https?://[^/]+", "", clean).strip("/")
            if not re.fullmatch(r"read-hentai/[a-z0-9\-]+", path):
                continue
            clean = "/" + path
            if clean in seen:
                continue
            seen.add(clean)
            # The real title lives in every card's <img alt>. Fall back to the
            # anchor's title -- but that attribute is "Oneshot"/"Chapter 47"
            # on chapter rows, so only use it when it is a real title (i.e. we
            # already found nothing better) and never a bare label.
            title = ""
            img = a.find("img")
            if img is not None:
                title = (img.get("alt") or "").strip()
            if not title:
                raw = (a.get("title") or "").strip()
                if raw and not re.fullmatch(r"(Oneshot|Chapter[ \.\-]?\d+.*|Ep[ \.\-]?\d+.*)", raw, re.I):
                    title = raw
            if not title:
                title = a.get_text(" ", strip=True)
            if not title:
                continue
            item = self._result(title, urljoin(SITE, clean), cover=self._cover(soup, a))
            # A series URL is a bare slug; chapter pages carry a
            # -chapter-<n>-ch<id> or -oneshot-ch<id> suffix.
            if "-chapter-" in clean or "-oneshot-" in clean:
                chapters.append(item)
            else:
                series.append(item)
        # Prefer series pages over the individual chapter entries the search
        # page also surfaces, so the result list points at the whole manga.
        # Gather a generous pool first (the search page can surface generic
        # listings) and let the shared ranker surface the best matches.
        pool = (series + chapters)[: max(limit, 40)]
        ranked = self.filter_and_rank(pool, query)
        return ranked[:limit]

    @staticmethod
    def _cover(soup, a) -> str:
        img = a.find("img")
        if img is not None:
            return img.get("src") or img.get("data-src") or None
        return None

    # --------------------------------------------------------- browse
    def browse(self, sort: str = "Latest", genre: str = None, page: int = 1,
               limit: int = 32, **__) -> list:
        page = max(1, int(page or 1))
        url = f"{SITE}/top-hentai/{'page/'+str(page)+'/' if page>1 else ''}"
        resp = self.fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        results, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            clean = href.split("#")[0]
            if not re.fullmatch(r"/read-hentai/[a-z0-9\-]+", clean) or clean in seen:
                continue
            seen.add(clean)
            title = (a.get("title") or a.get_text(" ", strip=True) or clean.split("/")[-1]).strip()
            results.append(self._result(title, urljoin(SITE, clean), cover=self._cover(soup, a)))
            if len(results) >= limit:
                break
        return results

    # --------------------------------------------------------- info
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
        for a in soup.select(".chapter-list a[href]"):
            href = a["href"].split("#")[0]
            if slug not in href or "/read-hentai/" not in href:
                continue
            full = urljoin(manga_url, href)
            if full in seen:
                continue
            seen.add(full)
            name = (a.get("title") or a.get_text(" ", strip=True) or href).strip()
            if not name:
                continue
            items.append({"url": full, "name": name})
        items.reverse()
        return items

    # ------------------------------------------------------ images
    def get_chapter_images(self, chapter) -> list:
        url = self._chapter_url(chapter)
        resp = self.fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for img in soup.find_all("img", src=True):
            src = img["src"]
            # Drop chrome assets (logo / icon / author avatars) and keep only
            # the actual page images under the manga image path.
            if not re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", src):
                continue
            if any(k in src for k in ("/images/logo", "/images/icon", "/favicon", "avatar")):
                continue
            full = urljoin(url, src)
            if full not in urls:
                urls.append(full)
        return urls

    # ------------------------------------------------------ genres
    def genres(self) -> list:
        return [{"id": g.lower().replace(" ", "-"), "name": g} for g in self.GENRES]
