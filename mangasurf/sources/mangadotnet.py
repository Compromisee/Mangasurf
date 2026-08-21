"""MangaDotNet source scraper for Mangasurf.

Adapted from mangadotnet-downloader with full integration for the Mangasurf Source API.
Features:
- REST API integration (mangadot.net/api)
- Nuxt-style packed response unpacking with regex fallback
- High speed metadata and chapter retrieval
"""

import json
import logging
import re
from urllib.parse import quote, urljoin

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://mangadot.net"
API_BASE = "https://mangadot.net/api"


class MangaDotNetSource(Source):
    id = "mangadotnet"
    name = "MangaDotNet"
    base_url = SITE
    domains = ("mangadot.net", "www.mangadot.net")
    needs_flaresolverr = True

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
            "User-Agent": "Mangasurf/2.0 (compatible; MangaDotNetDownloader/2.0)",
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

    def search(self, query: str, limit: int = 32, page: int = 1, **_) -> list:
        query_str = (query or "").strip()
        if not query_str:
            return []

        page_val = max(1, int(page or _.get("page", 1) or 1))
        url = f"{API_BASE}/search"
        results = []
        try:
            data = self.fetch_json(url, params={"q": query_str, "per_page": max(limit, 50), "page": page_val})
            parsed = self._parse_search_response(data)
            results = [
                self._result(
                    r.get("title", "Unknown"),
                    f"{SITE}/manga/{r.get('id')}",
                    cover=r.get("photo"),
                    status=r.get("status"),
                )
                for r in parsed
            ]
        except Exception as e:
            logger.warning("MangaDotNet search failed: %s", e)

        if query_str and results:
            results = self.filter_and_rank(results, query_str)

        return results[:limit]

    def _parse_search_response(self, data) -> list:
        if not isinstance(data, list):
            if isinstance(data, dict):
                return data.get("results") or data.get("data") or []
            return []

        results_indices = None
        for i, item in enumerate(data):
            if item == "results" and i + 1 < len(data) and isinstance(data[i + 1], list):
                results_indices = data[i + 1]
                break

        if not results_indices:
            return self._regex_search_fallback(data)

        items = []
        for idx in results_indices:
            if idx >= len(data):
                continue
            obj = data[idx]
            if not isinstance(obj, dict):
                continue
            resolved = {}
            for k, v in obj.items():
                if k.startswith("_") and k[1:].isdigit():
                    field_idx = int(k[1:])
                    if field_idx < len(data) and isinstance(data[field_idx], str):
                        field_name = data[field_idx]
                        resolved[field_name] = self._resolve_val(data, v)
            if resolved.get("id") and resolved.get("title"):
                items.append(resolved)

        return items

    def _resolve_val(self, data, val):
        if isinstance(val, int) and 0 <= val < len(data):
            res = data[val]
            if isinstance(res, (str, int, float, bool)):
                return res
            elif isinstance(res, list):
                return [self._resolve_val(data, x) for x in res]
        return val

    def _regex_search_fallback(self, data) -> list:
        raw = json.dumps(data)
        ids = re.findall(r'"id"\s*:\s*(\d+)', raw)
        titles = re.findall(r'"title"\s*:\s*"([^"]+)"', raw)
        out = []
        for mid, title in zip(ids, titles):
            out.append({"id": mid, "title": title})
        return out

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 32, **_) -> list:
        page = max(1, int(page or 1))
        url = f"{API_BASE}/manga"
        try:
            data = self.fetch_json(url, params={"page": page, "per_page": min(limit, 50)})
            items = data.get("data") or data.get("results") or (data if isinstance(data, list) else [])
            results = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                mid = item.get("id")
                if not mid:
                    continue
                title = item.get("title") or "Unknown"
                photo = item.get("photo") or item.get("cover")
                if photo and not photo.startswith("http"):
                    photo = f"{SITE}{photo}"
                results.append(
                    self._result(
                        title,
                        f"{SITE}/manga/{mid}",
                        cover=photo,
                        status=item.get("status"),
                    )
                )
                if len(results) >= limit:
                    break
            return results
        except Exception as e:
            logger.warning("MangaDotNet browse failed: %s", e)
            return []

    def get_manga_info(self, manga_url: str) -> dict:
        mid = self.extract_manga_id(manga_url)
        url = f"{API_BASE}/manga/{mid}"
        data = self.fetch_json(url)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]

        title = data.get("title") or "Unknown Manga"
        description = data.get("description") or ""
        cover = data.get("photo") or data.get("cover")
        if cover and not cover.startswith("http"):
            cover = f"{SITE}{cover}"

        genres = data.get("genres", [])
        tags = [g.get("name", g) if isinstance(g, dict) else str(g) for g in genres]

        authors = []
        for a in data.get("authors", []):
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

    def get_chapters(self, manga_url: str) -> list:
        mid = self.extract_manga_id(manga_url)
        url = f"{API_BASE}/manga/{mid}/chapters"
        try:
            data = self.fetch_json(url)
        except Exception:
            data = self.fetch_json(f"{API_BASE}/chapters/{mid}")

        raw_chapters = data.get("data") or data.get("chapters") or (data if isinstance(data, list) else [])
        chapters = []
        for ch in raw_chapters:
            if not isinstance(ch, dict):
                continue
            cid = ch.get("id")
            num = ch.get("chapter_number") or ch.get("number") or "0"
            title = ch.get("chapter_title") or ch.get("title") or ""
            name = f"Chapter {num} - {title}" if title else f"Chapter {num}"

            chapters.append({
                "url": f"{SITE}/chapter/{cid}" if cid else f"{manga_url}/chapter-{num}",
                "name": name,
                "date": ch.get("date_added") or ch.get("created_at"),
                "source": self.id,
                "chapter_id": cid,
                "sort_val": float(num) if str(num).replace(".", "", 1).isdigit() else 0.0,
            })

        chapters.sort(key=lambda c: c.get("sort_val", 0))
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        parts = chapter_url.strip("/").split("/")
        cid = parts[-1]
        url = f"{API_BASE}/images/{cid}"
        try:
            data = self.fetch_json(url)
            images = data.get("images") or data.get("pages") or (data if isinstance(data, list) else [])
            urls = []
            for img in images:
                src = img.get("url") if isinstance(img, dict) else str(img)
                if src:
                    if not src.startswith("http"):
                        src = f"{SITE}{src}"
                    urls.append(src)
            if urls:
                return urls
        except Exception:
            pass

        from bs4 import BeautifulSoup
        resp = self.fetch(chapter_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        return [
            urljoin(SITE, img.get("data-src") or img.get("src"))
            for img in soup.select("#reader img, .pages img, img")
            if (img.get("data-src") or img.get("src")) and not (img.get("data-src") or img.get("src")).endswith("loading.gif")
        ]
