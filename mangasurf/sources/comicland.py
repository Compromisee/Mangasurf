"""ComicLand (comicland.org) source scraper for Mangasurf.

ComicLand is a modern React SPA backed by a clean JSON REST API at
``https://api.comicland.org/api``. The API requires a valid browser
``Referer``/``Origin`` (``https://comicland.org``) or it answers 403
``"invalid referer or origin"`` -- so the source sets those headers and uses
the browser-impersonating curl_cffi session. Verified live (2026-08):

- search    ``GET /api/comic/search?q=``  -> ``data.items[]``
- browse    ``GET /api/comics`` / ``/api/comics/popular`` / ``/api/comics/official``
- series    ``GET /api/comic/detail?slug=`` -> cover, chapters[], genres, authors
- pages     ``GET /api/chapter/pages_by_index?slug=&index=`` -> page CDN urls
"""

import logging
from urllib.parse import urljoin

from .base import Source

logger = logging.getLogger(__name__)

SITE = "https://comicland.org"
API = "https://api.comicland.org/api"


class ComicLandSource(Source):
    id = "comicland"
    name = "ComicLand"
    base_url = SITE
    domains = ("comicland.org", "api.comicland.org", "cdn.comicland.org", "img.comicland.org")

    supports_search = True
    supports_browse = True
    supports_genres = True
    default_series_type = None
    adult_only = False

    search_sorts = ("Relevance",)
    browse_sorts = ("Popular", "Latest", "Official")

    GENRES = (
        "Action", "Adventure", "Comedy", "Drama", "Fantasy", "Harem",
        "Historical", "Horror", "Isekai", "Mature", "Mystery", "Romance",
        "School Life", "Sci-Fi", "Seinen", "Shoujo", "Shounen", "Slice of Life",
        "Sports", "Supernatural", "Thriller", "Tragedy",
    )

    def headers(self) -> dict:
        h = super().headers()
        # The API rejects requests without a valid browser origin/referer.
        h.update({
            "Referer": f"{SITE}/",
            "Origin": SITE,
            "Accept": "application/json",
        })
        return h

    # --------------------------------------------------------- api
    def _api(self, path: str, params=None):
        resp = self.fetch(API + path, params=params)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("code") not in (0, "0"):
            raise ValueError(f"[{self.id}] API error: {data.get('message')}")
        return (data or {}).get("data")

    # --------------------------------------------------------- search
    def search(self, query: str, limit: int = 32, page: int = 1, **__) -> list:
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)
        page = max(1, int(page or 1))
        limit = max(1, int(limit or 32))
        data = self._api("/comic/search", params={
            "q": query,
            "offset": (page - 1) * limit,
        })
        items = ((data or {}).get("items") or []) if isinstance(data, dict) else []
        results = [self._result(i.get("title"), self._comic_url(i), cover=i.get("cover_url"))
                   for i in items]
        if page == 1:
            results = self.filter_and_rank(results, query)
        return results[:limit]

    # --------------------------------------------------------- browse
    def browse(self, sort: str = "Popular", genre: str = None, page: int = 1,
               limit: int = 32, **__) -> list:
        page = max(1, int(page or 1))
        limit = max(1, int(limit or 32))
        # The API ignores ``?page=`` and paginates with ``?offset=`` (a row
        # index), so offset = (page-1)*limit. ``/comics`` and
        # ``/comics/official`` honour it; ``/comics/popular`` is a static
        # 50-item list with no paging at all, so "Popular"/"Trending" fall
        # back to the paginated ``/comics`` feed (closest stable ordering).
        if "official" in str(sort).lower():
            path = "/comics/official"
        else:
            path = "/comics"
        data = self._api(path, params={"offset": (page - 1) * limit})
        items = ((data or {}).get("list") or []) if isinstance(data, dict) else []
        return [self._result(i.get("title"), self._comic_url(i), cover=i.get("cover_url"))
                for i in items][:limit]

    # ----------------------------------------------------------- info
    def get_manga_info(self, manga_url: str) -> dict:
        slug = manga_url.rstrip("/").split("/")[-1]
        data = self._api("/comic/detail", params={"slug": slug})
        if not data:
            return {"url": manga_url, "title": slug, "cover": None,
                    "description": "", "tags": [], "status": None, "authors": []}
        return {
            "url": manga_url,
            "title": data.get("title") or slug,
            "cover": data.get("cover_url"),
            "description": data.get("description") or "",
            "tags": list(data.get("genres") or []),
            "status": data.get("status"),
            "authors": list(data.get("authors") or data.get("artists") or []),
        }

    # ------------------------------------------------------ chapters
    def get_chapters(self, manga_url: str) -> list:
        slug = manga_url.rstrip("/").split("/")[-1]
        data = self._api("/comic/detail", params={"slug": slug})
        chapters = ((data or {}).get("chapters") or [])
        items = []
        for ch in chapters:
            index = ch.get("chapter_index")
            name = ch.get("title") or f"Chapter {index}"
            url = f"{SITE}/comic/{slug}/chapter/{index}"
            items.append({"url": url, "name": name, "index": index,
                          "id": ch.get("id"), "page_count": ch.get("page_count")})
        items.sort(key=lambda c: c.get("index", 0))     # oldest first
        return items

    # ------------------------------------------------------ images
    def get_chapter_images(self, chapter) -> list:
        slug, index = self._chapter_slug_and_index(chapter)
        data = self._api("/chapter/pages_by_index", params={"slug": slug, "index": index})
        pages = ((data or {}).get("pages") or [])
        return [p for p in pages if p]

    def _chapter_slug_and_index(self, chapter):
        if isinstance(chapter, dict):
            url = chapter.get("url") or ""
            index = chapter.get("index")
            if index is None and chapter.get("name"):
                import re
                m = re.search(r"(\d+)", str(chapter.get("name")))
                index = int(m.group(1)) if m else None
        else:
            url = chapter or ""
            index = None
        # /comic/<slug>/chapter/<index>  (or just <index>)
        parts = [p for p in url.rstrip("/").split("/") if p]
        if "chapter" in parts and len(parts) >= 2:
            idx = parts[-1]
            cidx = parts.index("chapter")
            if cidx > 0:
                slug = parts[cidx - 1]
                if idx.isdigit():
                    index = int(idx)
                return slug, index
        if index is None:
            raise ValueError(f"[{self.id}] cannot determine chapter index from {url!r}")
        return url.rstrip("/").split("/")[-1], int(index)

    @staticmethod
    def _comic_url(item) -> str:
        slug = item.get("slug") or ""
        return f"{SITE}/comic/{slug}"

    def genres(self) -> list:
        return [{"id": g.lower().replace(" ", "-"), "name": g} for g in self.GENRES]
