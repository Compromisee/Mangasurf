"""Kagane source scraper for Mangasurf.

Adapted from kagane-downloader with full integration for the Mangasurf Source API.
Uses Kagane REST API (yuzuki.kagane.to/api/v2).
"""

import logging
import re
from urllib.parse import quote

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://kagane.to"
API_BASE = "https://yuzuki.kagane.to/api/v2"
IMAGE_BASE = f"{API_BASE}/image"

SERIES_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?kagane\.to/series/([a-f0-9-]+)",
    re.IGNORECASE,
)
UUID_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    re.IGNORECASE,
)


class KaganeSource(Source):
    id = "kagane"
    name = "Kagane"
    base_url = SITE
    domains = ("kagane.to", "www.kagane.to", "yuzuki.kagane.to")

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Popularity", "Latest", "Alphabetical", "Rating")
    browse_sorts = ("Trending", "Popularity", "Latest Updates", "Rating")

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
            "Accept": "application/json",
            "User-Agent": "Mangasurf/2.0 (compatible; KaganeDownloader/2.0)",
            "Referer": f"{SITE}/",
        })
        return h

    @classmethod
    def extract_series_id(cls, url_or_id: str) -> str:
        if not url_or_id:
            return ""
        url_or_id = url_or_id.strip()
        match = SERIES_URL_PATTERN.search(url_or_id)
        if match:
            return match.group(1)
        if UUID_PATTERN.match(url_or_id):
            return url_or_id
        parts = url_or_id.split("/")
        for part in parts:
            if UUID_PATTERN.match(part):
                return part
        return url_or_id

    def genres(self) -> list:
        return [{"id": name.lower(), "name": name} for name in self.GENRES]

    def search(self, query: str, limit: int = 32, **_) -> list:
        query_str = (query or "").strip()
        if not query_str:
            return []

        if UUID_PATTERN.match(query_str):
            try:
                info = self.get_manga_info(query_str)
                return [self._result(info["title"], info["url"], cover=info.get("cover"))]
            except Exception:
                pass

        data = None
        for endpoint, key_name in [("search", "q"), ("series", "query"), ("series", "search"), ("series", "q")]:
            try:
                url = f"{API_BASE}/{endpoint}"
                data = self.fetch_json(url, params={key_name: query_str, "limit": max(limit, 50)})
                if data:
                    break
            except Exception:
                continue

        if not data:
            return []

        items = data.get("data") or data.get("results") or data.get("series") or (data if isinstance(data, list) else [])
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            series_id = item.get("series_id") or item.get("id")
            if not series_id:
                continue
            title = item.get("title") or "Unknown"
            cover_url = None
            if item.get("cover_image_id"):
                cover_url = f"{IMAGE_BASE}/{item['cover_image_id']}"
            elif item.get("series_covers"):
                covers = item.get("series_covers")
                if covers and isinstance(covers, list) and covers[0].get("image_id"):
                    cover_url = f"{IMAGE_BASE}/{covers[0]['image_id']}"

            results.append(
                self._result(
                    title,
                    f"{SITE}/series/{series_id}",
                    cover=cover_url,
                    status=item.get("publication_status"),
                    type=item.get("format"),
                )
            )

        if query_str and results:
            results = self.filter_and_rank(results, query_str)

        return results[:limit]

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 32, **_) -> list:
        page = max(1, int(page or 1))
        url = f"{API_BASE}/series"
        params = {"page": page, "limit": min(limit, 50)}
        if genre:
            params["genre"] = genre

        try:
            data = self.fetch_json(url, params=params)
        except Exception as e:
            logger.warning("Kagane browse failed: %s", e)
            return []

        items = data.get("data") or data.get("results") or (data if isinstance(data, list) else [])
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            series_id = item.get("series_id") or item.get("id")
            if not series_id:
                continue
            title = item.get("title") or "Unknown"
            cover_url = None
            if item.get("cover_image_id"):
                cover_url = f"{IMAGE_BASE}/{item['cover_image_id']}"
            elif item.get("series_covers"):
                covers = item.get("series_covers")
                if covers and isinstance(covers, list) and covers[0].get("image_id"):
                    cover_url = f"{IMAGE_BASE}/{covers[0]['image_id']}"

            results.append(
                self._result(
                    title,
                    f"{SITE}/series/{series_id}",
                    cover=cover_url,
                    status=item.get("publication_status"),
                    type=item.get("format"),
                )
            )
            if len(results) >= limit:
                break
        return results

    def get_manga_info(self, manga_url: str) -> dict:
        series_id = self.extract_series_id(manga_url)
        if not series_id:
            raise ScrapeError(f"Could not extract Kagane series ID from {manga_url}")

        api_url = f"{API_BASE}/series/{series_id}"
        data = self.fetch_json(api_url)
        if not data or not isinstance(data, dict):
            raise ScrapeError(f"Failed to fetch series data from {api_url}")

        title = data.get("title") or "Unknown Manga"
        description = data.get("description") or ""

        cover_url = None
        covers = data.get("series_covers", [])
        if covers and isinstance(covers, list) and covers[0].get("image_id"):
            cover_url = f"{IMAGE_BASE}/{covers[0]['image_id']}"
        elif data.get("cover_image_id"):
            cover_url = f"{IMAGE_BASE}/{data['cover_image_id']}"

        alt_titles = [
            t.get("title") for t in data.get("series_alternate_titles", [])
            if isinstance(t, dict) and t.get("title")
        ]

        tags = []
        for g in data.get("genres", []):
            if isinstance(g, dict) and g.get("genre_name"):
                tags.append(g["genre_name"])
        for t in data.get("tags", []):
            if isinstance(t, dict) and t.get("tag_name"):
                tags.append(t["tag_name"])

        authors = []
        artists = []
        for s in data.get("series_staff", []):
            if not isinstance(s, dict):
                continue
            name = s.get("name")
            role = (s.get("role") or "").lower()
            if not name:
                continue
            if "art" in role:
                artists.append(name)
            else:
                authors.append(name)

        return {
            "url": f"{SITE}/series/{series_id}",
            "title": title,
            "alt_titles": alt_titles,
            "cover": cover_url,
            "description": description,
            "tags": tags,
            "status": data.get("publication_status"),
            "authors": authors,
            "artists": artists,
            "source": self.id,
            "source_name": self.name,
            "format": data.get("format"),
            "rating": data.get("average_rating"),
        }

    def get_chapters(self, manga_url: str) -> list:
        series_id = self.extract_series_id(manga_url)
        if not series_id:
            return []

        api_url = f"{API_BASE}/series/{series_id}"
        data = self.fetch_json(api_url)
        books = data.get("series_books", [])
        if not books and isinstance(data, list):
            books = data

        chapters = []
        for book in books:
            if not isinstance(book, dict):
                continue
            book_id = book.get("book_id") or book.get("id")
            if not book_id:
                continue

            ch_no = str(book.get("chapter_no", "")).strip()
            ch_title = str(book.get("title", "")).strip()

            if ch_no and ch_title and ch_no != ch_title:
                name = f"Chapter {ch_no} - {ch_title}"
            elif ch_no:
                name = f"Chapter {ch_no}"
            elif ch_title:
                name = ch_title
            else:
                name = f"Chapter {book.get('sort_no', 0)}"

            chapters.append({
                "url": f"{SITE}/series/{series_id}/reader/{book_id}",
                "name": name,
                "date": book.get("created_at") or book.get("updated_at"),
                "source": self.id,
                "book_id": book_id,
                "sort_no": float(book.get("sort_no", 0) or 0),
            })

        chapters.sort(key=lambda c: c.get("sort_no", 0))
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        parts = chapter_url.strip("/").split("/")
        book_id = parts[-1]

        api_url = f"{API_BASE}/books/{book_id}"
        try:
            data = self.fetch_json(api_url)
            if "pages" in data and isinstance(data["pages"], list):
                return [
                    f"{API_BASE}/books/page/{p.get('image_id', p)}" if not str(p).startswith("http") else str(p)
                    for p in data["pages"]
                ]
            page_count = int(data.get("page_count", 0))
            if page_count > 0:
                return [f"{API_BASE}/books/{book_id}/page/{i}" for i in range(1, page_count + 1)]
        except Exception:
            pass

        try:
            resp = self.fetch(chapter_url)
            html = resp.text
            urls = re.findall(r'https?://[^\s"\']+(?:kstatic\.to|kagane\.to)[^\s"\']+\.(?:webp|jpg|jpeg|png)', html)
            if urls:
                return sorted(list(set(urls)))
        except Exception as e:
            logger.warning("Kagane HTML page fallback failed: %s", e)

        return [f"https://kstatic.to/api/v2/books/{book_id}/page/{i}.webp" for i in range(1, 25)]
