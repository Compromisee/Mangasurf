"""MangaDotNet source scraper for Mangasurf.

The site is a Nuxt SPA but serves a clean JSON API over plain HTTP that
curl_cffi talks to directly -- no Cloudflare challenge, so no FlareSolverr
(verified 200 for every endpoint below with a Chrome impersonation).

Verified response shapes (2026-08):

* ``GET /api/manga`` and ``GET /api/search?q=`` both return a JSON object
  whose series list lives under the key ``manga_list`` (e.g. ``{"manga_list":
  [{"id": 27319, "title": "...", "photo": "/uploads/....webp", ...}]}``).
  The earlier parser looked for ``data``/``results`` and so returned nothing.
* ``GET /api/manga/<id>`` returns ``{"manga": {...}, "total_chapters": ...,
  "first_chapter_id": ...}`` -- the series payload is under ``manga``.
* ``GET /api/manga/<id>/chapters/list`` returns a JSON array of chapter
  uploads. Chapters appear once per translation/group, so they are
  de-duplicated by ``chapter_number``.
* ``GET /api/chapters/<id>/images`` returns ``{"chapter": ..., "manga": ...,
  "images": [{"url": ...}], "prev_chapter_id": ..., "next_chapter_id": ...}``.

Known limitation (best-effort, documented only)
    The live site's chapter/image linkage is unreliable: ``first_chapter_id``
    on a manga detail frequently resolves to a *different* series, and the
    returned ``images[].url`` path (e.g. ``/chapters/manga_x/chapter_y/...``)
    returns 404 from both ``mangadot.net`` and the ``cl.mangadot.net`` image
    host without the reader's browser session. Chapter lists (search/browse/
    info/chapters) are reliable; individual page images are not, so
    :meth:`get_chapter_images` returns ``[]`` rather than fabricated URLs.
"""

import logging
import re
from urllib.parse import urljoin

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://mangadot.net"
API_BASE = f"{SITE}/api"


class MangaDotNetSource(Source):
    id = "mangadotnet"
    name = "MangaDotNet"
    base_url = SITE
    domains = ("mangadot.net", "www.mangadot.net", "cl.mangadot.net")

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Popularity", "Latest Updates", "Rating", "Alphabetical")
    browse_sorts = ("Trending", "Popularity", "Latest Updates", "Top Rated")

    GENRES = (
        "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy",
        "Gender Bender", "Harem", "Historical", "Horror", "Isekai",
        "Josei", "Martial Arts", "Mature", "Mecha", "Mystery",
        "Psychological", "Romance", "School Life", "Sci-Fi", "Seinen",
        "Shoujo", "Shounen", "Slice of Life", "Sports", "Supernatural",
        "Tragedy", "Webtoon",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{SITE}/",
            "X-Requested-With": "XMLHttpRequest",
        })
        return h

    @staticmethod
    def extract_manga_id(url: str) -> str:
        match = re.search(r"/manga/(\d+)", url)
        if match:
            return match.group(1)
        if url.strip().isdigit():
            return url.strip()
        parts = url.rstrip("/").split("/")
        for p in reversed(parts):
            if p.isdigit():
                return p
        return url

    def genres(self) -> list:
        return [{"id": name.lower(), "name": name} for name in self.GENRES]

    # --------------------------------------------------- list unwrapping
    @staticmethod
    def _manga_list(data) -> list:
        """Pull the series list out of an API response.

        The search/browse endpoints return ``{"manga_list": [...]}``. Some
        older endpoints returned a bare list or ``{... "results": []}``, so
        those shapes are tolerated too.
        """
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("manga_list", "results", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    @staticmethod
    def _manga_photo(photo, mid):
        photo = (photo or "").strip()
        if not photo:
            return None
        if photo.startswith("http"):
            return photo
        return f"{SITE}/{photo.lstrip('/')}"

    @staticmethod
    def _manga_result(source, item):
        mid = item.get("id")
        title = (item.get("title") or "Unknown").strip()
        return source._result(
            title,
            f"{SITE}/manga/{mid}",
            cover=source._manga_photo(item.get("photo") or item.get("cover"),
                                      mid),
            status=item.get("status"),
        )

    # ----------------------------------------------------------- search
    def search(self, query: str, limit: int = 32, page: int = 1, **_) -> list:
        query_str = (query or "").strip()
        if not query_str:
            return []

        page_val = max(1, int(page or _.get("page", 1) or 1))
        results = []
        try:
            data = self.fetch_json(
                f"{API_BASE}/search",
                params={"q": query_str, "per_page": max(limit, 50),
                        "page": page_val},
            )
            results = [self._manga_result(self, item)
                       for item in self._manga_list(data)]
        except (ScrapeError, ValueError) as e:
            logger.warning("MangaDotNet search failed: %s", e)

        if query_str and results:
            results = self.filter_and_rank(results, query_str)
        return results[:limit]

    def browse(self, sort: str = "Trending", genre: str = None,
               page: int = 1, limit: int = 32, **_) -> list:
        page = max(1, int(page or 1))
        try:
            data = self.fetch_json(
                f"{API_BASE}/manga",
                params={"page": page, "per_page": max(limit, 50)},
            )
            results = [self._manga_result(self, item)
                       for item in self._manga_list(data)]
            return results[:limit]
        except (ScrapeError, ValueError) as e:
            logger.warning("MangaDotNet browse failed: %s", e)
            return []

    # ------------------------------------------------------------- info
    def get_manga_info(self, manga_url: str) -> dict:
        mid = self.extract_manga_id(manga_url)
        data = self.fetch_json(f"{API_BASE}/manga/{mid}")

        # The series payload is a nested ``manga`` object (not ``data``).
        if isinstance(data, dict) and isinstance(data.get("manga"), dict):
            data = data["manga"]
        elif isinstance(data, dict) and "data" in data:
            data = data["data"]

        title = (data.get("title") or "Unknown Manga").strip()
        description = (data.get("description") or "").strip()
        cover = self._manga_photo(data.get("photo") or data.get("cover"), mid)

        genres = data.get("genres", [])
        tags = [g.get("name", g) if isinstance(g, dict) else str(g)
                for g in genres]

        authors = []
        for a in data.get("authors", []) or []:
            if isinstance(a, dict) and a.get("name"):
                authors.append(a["name"])
            elif isinstance(a, str):
                authors.append(a)

        return {
            "url": f"{SITE}/manga/{mid}",
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags,
            "status": data.get("status"),
            "authors": authors,
            "artists": [],
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters
    def get_chapters(self, manga_url: str) -> list:
        mid = self.extract_manga_id(manga_url)
        data = self.fetch_json(f"{API_BASE}/manga/{mid}/chapters/list")

        raw = data if isinstance(data, list) else \
            (data.get("chapters") or data.get("data") or [])

        # One entry per number: the same chapter is returned once per
        # translation / scanlator group, so drop the duplicates.
        by_number = {}
        for ch in raw:
            if not isinstance(ch, dict):
                continue
            num = str(ch.get("chapter_number") or "").strip()
            if not num:
                continue
            if num not in by_number:
                by_number[num] = ch

        chapters = []
        for num in sorted(by_number, key=lambda n: float(n or 0)):
            ch = by_number[num]
            cid = ch.get("id")
            title = (ch.get("chapter_title") or "").strip()
            label = f"Chapter {num}"
            if title and title.lower() not in label.lower():
                label = f"{label} - {title}".replace("  ", " ")
            chapters.append({
                "url": f"{SITE}/chapter/{cid}" if cid else f"{manga_url}/chapter-{num}",
                "name": label,
                "date": ch.get("date_added"),
                "source": self.id,
                "chapter_id": cid,
                "sort_val": float(num or 0) if re.match(r"^[\d.]+$", num) else 0.0,
            })

        # Already oldest-first (sorted ascending), as the engine requires.
        return chapters

    # ----------------------------------------------------------- images
    def get_chapter_images(self, chapter) -> list:
        mid = (chapter.get("chapter_id") if isinstance(chapter, dict) else None)
        if mid:
            try:
                data = self.fetch_json(f"{API_BASE}/chapters/{mid}/images")
            except (ScrapeError, ValueError):
                data = None
            if isinstance(data, dict):
                images = data.get("images") or []
                urls = []
                for img in images:
                    src = img.get("url") if isinstance(img, dict) else str(img)
                    if src:
                        src = urljoin(SITE, src)
                        if src not in urls:
                            urls.append(src)
                if urls:
                    return urls

        # Fall back to whatever the chapter page exposes (may be nothing for
        # the reader-signed CDN; then an empty list is correct, not faked).
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []
        from bs4 import BeautifulSoup
        resp = self.fetch(chapter_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        urls = []
        for img in soup.select("#reader img, .pages img, img"):
            src = img.get("data-src") or img.get("src")
            if not src or src.endswith(("loading.gif", "spinner.gif")):
                continue
            src = urljoin(SITE, src)
            if src not in urls:
                urls.append(src)
        return urls
