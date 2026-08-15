"""Comix / Comick source scraper for Mangasurf.

Adapted from comix-downloader with full integration for the Mangasurf Source API.
Uses Comix API / Comick API (comix.to / comick.app).
"""

import logging
import re
from urllib.parse import quote, urljoin

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://comix.to"
API_BASE = "https://comix.to/api/v2"


class ComixSource(Source):
    id = "comix"
    name = "Comix"
    base_url = SITE
    domains = ("comix.to", "www.comix.to", "comick.app", "comick.io", "comick.live")

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Most Popular", "Top Rated", "Latest Updates", "New")
    browse_sorts = ("Trending", "Most Popular", "Latest Updates", "Top Rated")

    GENRES = (
        "Action", "Adventure", "Comedy", "Drama", "Fantasy", "Gender Bender",
        "Harem", "Historical", "Horror", "Isekai", "Josei", "Martial Arts",
        "Mature", "Mecha", "Mystery", "Psychological", "Romance",
        "School Life", "Sci-Fi", "Seinen", "Shoujo", "Shounen",
        "Slice of Life", "Sports", "Supernatural", "Tragedy", "Webtoon",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "Accept": "application/json, text/html, */*",
            "User-Agent": "Mangasurf/2.0 (compatible; ComixDownloader/2.0)",
            "Referer": f"{SITE}/",
        })
        return h

    @staticmethod
    def extract_manga_code(url: str) -> str:
        parts = url.rstrip("/").split("/")
        last = parts[-1] if parts[-1] else parts[-2]
        return last

    def genres(self) -> list:
        return [{"id": name.lower(), "name": name} for name in self.GENRES]

    def search(self, query: str, limit: int = 32, **_) -> list:
        query_str = (query or "").strip()
        if not query_str:
            return []

        data = None
        for endpoint, key_name in [
            (f"{API_BASE}/search", "q"),
            (f"{API_BASE}/search", "query"),
            ("https://api.comick.app/v1.0/search", "q"),
        ]:
            try:
                data = self.fetch_json(endpoint, params={key_name: query_str, "limit": max(limit, 40)})
                if data:
                    break
            except Exception:
                continue

        if not data:
            return []

        items = data.get("data") or data.get("results") or (data if isinstance(data, list) else [])
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug") or item.get("hid") or item.get("id")
            if not slug:
                continue
            title = item.get("title") or "Unknown"
            cover = item.get("cover_url") or item.get("poster")
            if isinstance(cover, dict):
                cover = cover.get("large") or cover.get("medium")

            results.append(
                self._result(
                    title,
                    f"{SITE}/title/{slug}",
                    cover=cover,
                    status=item.get("status"),
                    type=item.get("country_name") or item.get("type"),
                )
            )

        if query_str and results:
            results = self.filter_and_rank(results, query_str)

        return results[:limit]

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 32, **_) -> list:
        page = max(1, int(page or 1))
        url = f"{API_BASE}/top"
        params = {"page": page, "limit": min(limit, 40)}
        if genre:
            params["genre"] = genre

        try:
            data = self.fetch_json(url, params=params)
        except Exception:
            return []

        items = data.get("data") or data.get("results") or (data if isinstance(data, list) else [])
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug") or item.get("hid") or item.get("id")
            if not slug:
                continue
            title = item.get("title") or "Unknown"
            cover = item.get("cover_url") or item.get("poster")
            if isinstance(cover, dict):
                cover = cover.get("large") or cover.get("medium")

            results.append(
                self._result(
                    title,
                    f"{SITE}/title/{slug}",
                    cover=cover,
                    status=item.get("status"),
                )
            )
            if len(results) >= limit:
                break
        return results

    def get_manga_info(self, manga_url: str) -> dict:
        code = self.extract_manga_code(manga_url)
        url = f"{API_BASE}/title/{code}"
        data = None
        try:
            data = self.fetch_json(url)
        except Exception:
            pass

        if not data or not isinstance(data, dict):
            from bs4 import BeautifulSoup
            resp = self.fetch(manga_url)
            soup = BeautifulSoup(resp.content, "html.parser")
            title = soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else code
            img = soup.select_one("img[src*='cover'], img[alt*='cover'], img")
            cover = img.get("src") if img else None
            desc = soup.select_one("p.description, div.description, p")
            description = desc.get_text(strip=True) if desc else ""
            return {
                "url": manga_url,
                "title": title,
                "cover": cover,
                "description": description,
                "tags": [],
                "status": "Ongoing",
                "authors": [],
                "artists": [],
                "source": self.id,
                "source_name": self.name,
            }

        comic = data.get("comic") or data.get("data") or data
        title = comic.get("title") or code
        desc = comic.get("desc") or comic.get("description") or ""

        cover = comic.get("cover_url") or comic.get("poster")
        if isinstance(cover, dict):
            cover = cover.get("large") or cover.get("medium")

        tags = []
        for g in comic.get("md_genres", []) or comic.get("genres", []):
            if isinstance(g, dict) and g.get("name"):
                tags.append(g["name"])
            elif isinstance(g, str):
                tags.append(g)

        authors = []
        for a in comic.get("authors", []) or comic.get("md_authors", []):
            if isinstance(a, dict) and a.get("name"):
                authors.append(a["name"])
            elif isinstance(a, str):
                authors.append(a)

        return {
            "url": f"{SITE}/title/{code}",
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": tags,
            "status": comic.get("status"),
            "authors": authors,
            "artists": [],
            "source": self.id,
            "source_name": self.name,
        }

    def get_chapters(self, manga_url: str) -> list:
        code = self.extract_manga_code(manga_url)
        url = f"{API_BASE}/title/{code}/chapters"
        data = None
        try:
            data = self.fetch_json(url, params={"limit": 300})
        except Exception:
            pass

        raw_chapters = []
        if data and isinstance(data, dict):
            raw_chapters = data.get("chapters") or data.get("data") or []
        elif isinstance(data, list):
            raw_chapters = data

        chapters = []
        for ch in raw_chapters:
            if not isinstance(ch, dict):
                continue
            hid = ch.get("hid") or ch.get("id") or ch.get("chap")
            ch_num = ch.get("chap") or ch.get("chapter_number") or ch.get("title") or "1"
            title = ch.get("title") or f"Chapter {ch_num}"
            name = f"Chapter {ch_num} - {title}" if title and str(ch_num) not in title else f"Chapter {ch_num}"

            chapters.append({
                "url": f"{SITE}/chapter/{hid}" if hid else f"{manga_url}/chapter-{ch_num}",
                "name": name,
                "date": ch.get("created_at") or ch.get("updated_at"),
                "source": self.id,
                "sort_val": float(re.search(r"(\d+(?:\.\d+)?)", str(ch_num)).group(1)) if re.search(r"(\d+(?:\.\d+)?)", str(ch_num)) else 0.0,
            })

        chapters.sort(key=lambda c: c.get("sort_val", 0))
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        parts = chapter_url.strip("/").split("/")
        hid = parts[-1]
        api_url = f"{API_BASE}/chapter/{hid}"
        try:
            data = self.fetch_json(api_url)
            chapter_data = data.get("chapter") or data
            images = chapter_data.get("images") or chapter_data.get("md_images") or []
            if images:
                return [
                    img.get("url") if isinstance(img, dict) else str(img)
                    for img in images
                    if isinstance(img, (dict, str))
                ]
        except Exception:
            pass

        from bs4 import BeautifulSoup
        resp = self.fetch(chapter_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        urls = []
        for img in soup.select("img[src*='chapter'], img[data-src*='chapter'], img"):
            src = img.get("data-src") or img.get("src")
            if src and src.startswith("http") and not src.endswith("loading.gif"):
                urls.append(src)
        return urls
