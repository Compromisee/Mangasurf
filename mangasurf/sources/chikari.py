"""Chikari (chikari.moe) source scraper for Mangasurf.

High-speed REST API reader & downloader for manhwa, manhua, and manga.
Supports both SFW and adult/NSFW catalog items.
"""

import logging
import re
from urllib.parse import quote, urljoin, urlparse

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://chikari.moe"
API_BASE = "https://chikari.moe/api"


class ChikariSource(Source):
    id = "chikari"
    name = "Chikari"
    base_url = SITE
    domains = ("chikari.moe", "www.chikari.moe")

    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest", "Popular", "Rating", "Title")

    _ORDER = {
        "Latest": "latest",
        "Popular": "views",
        "Rating": "rating",
        "Title": "title",
    }

    GENRES = (
        ("action", "Action"),
        ("adult", "Adult"),
        ("adventure", "Adventure"),
        ("comedy", "Comedy"),
        ("drama", "Drama"),
        ("fantasy", "Fantasy"),
        ("horror", "Horror"),
        ("isekai", "Isekai"),
        ("martial-arts", "Martial Arts"),
        ("mature", "Mature"),
        ("mystery", "Mystery"),
        ("romance", "Romance"),
        ("sci-fi", "Sci-Fi"),
        ("shounen", "Shounen"),
        ("supernatural", "Supernatural"),
    )

    @classmethod
    def is_list_url(cls, url: str) -> bool:
        if not url:
            return False
        return bool(re.search(r"/lists?/(\d+)", url))

    @classmethod
    def extract_list_id(cls, url: str) -> str:
        match = re.search(r"/lists?/(\d+)", url)
        return match.group(1) if match else ""

    def get_list_series(self, list_url: str) -> dict:
        """Fetch all series belonging to a curated Chikari list (e.g. /lists/461-my-manhwa-list)."""
        list_id = self.extract_list_id(list_url)
        if not list_id:
            raise ScrapeError(f"Could not extract list ID from {list_url}")

        api_url = f"{API_BASE}/lists/{list_id}"
        resp = self.fetch(api_url)
        if resp.status_code != 200:
            raise ScrapeError(f"Chikari list fetch failed: HTTP {resp.status_code}")

        data = resp.json()
        raw_items = data.get("items") or data.get("series") or []
        series = []
        for it in raw_items:
            slug = it.get("slug")
            if not slug:
                continue
            title = it.get("title") or slug.replace("-", " ").title()
            cover = it.get("cover_url")
            ch_count = it.get("chapter_count")
            stype = classify_type(text=it.get("type")) or self.default_series_type
            series.append({
                "url": f"{SITE}/series/{slug}",
                "title": title,
                "cover": cover,
                "chapters_count": ch_count,
                "latest": f"Chapter {ch_count}" if ch_count else None,
                "series_type": stype,
                "source": self.id,
                "source_name": self.name,
            })

        return {
            "id": list_id,
            "title": data.get("title") or f"Chikari List {list_id}",
            "description": data.get("description") or "",
            "item_count": len(series),
            "cover": series[0]["cover"] if series else None,
            "series": series,
        }

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        try:
            # Fetch standard SFW results
            api_url = f"{API_BASE}/search?q={quote(query)}"
            resp = self.fetch(api_url)
            items = resp.json() if resp.status_code == 200 else []

            # Also fetch NSFW/adult results
            try:
                resp_nsfw = self.fetch(f"{API_BASE}/search?q={quote(query)}&adult=true")
                if resp_nsfw.status_code == 200:
                    nsfw_items = resp_nsfw.json()
                    seen_ids = {x.get("id") for x in items}
                    for ni in nsfw_items:
                        if ni.get("id") not in seen_ids:
                            items.append(ni)
            except Exception:
                pass

            results = []
            for s in items[:limit]:
                title = s.get("title") or "Untitled"
                slug = s.get("slug") or ""
                href = f"{SITE}/series/{slug}" if slug else ""
                cover = s.get("cover_url")
                stype = classify_type(text=s.get("type")) or self.default_series_type
                ch_count = s.get("chapter_count")
                latest = f"Chapter {ch_count}" if ch_count else None

                results.append(self._result(
                    title, href, cover=cover,
                    latest=latest, series_type=stype,
                ))
            return results
        except Exception as e:
            logger.error("chikari search failed: %s", e)
            return []

    def browse(self, sort: str = "Latest", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._ORDER.get(sort or "", "latest")
        api_url = f"{API_BASE}/series?page={page}&limit={limit}&order={order}"
        if genre:
            genre_clean = str(genre).strip().lower()
            if genre_clean in ("adult", "nsfw", "18+"):
                api_url += "&adult=true"
            elif genre_clean.isdigit():
                api_url += f"&tag={genre_clean}"
            else:
                # Check if genre matches standard tag or custom tag name
                tag_id = self._resolve_tag_id(genre_clean)
                if tag_id:
                    api_url += f"&tag={tag_id}"
                else:
                    api_url += f"&genre={quote(genre_clean)}"

        try:
            resp = self.fetch(api_url)
            data = resp.json() if resp.status_code == 200 else {}
            items = data.get("items") or (data if isinstance(data, list) else [])
            results = []
            for s in items[:limit]:
                title = s.get("title") or "Untitled"
                slug = s.get("slug") or ""
                href = f"{SITE}/series/{slug}" if slug else ""
                cover = s.get("cover_url")
                stype = classify_type(text=s.get("type")) or self.default_series_type
                ch_count = s.get("chapter_count")
                latest = f"Chapter {ch_count}" if ch_count else None

                results.append(self._result(
                    title, href, cover=cover,
                    latest=latest, series_type=stype,
                ))
            return results
        except Exception as e:
            logger.error("chikari browse failed: %s", e)
            return []

    _TAG_CACHE = {}

    @classmethod
    def _resolve_tag_id(cls, tag_name: str) -> str:
        if not cls._TAG_CACHE:
            try:
                import requests
                r = requests.get(f"{API_BASE}/tags", headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                if r.status_code == 200:
                    for t in r.json():
                        cls._TAG_CACHE[t.get("name", "").lower()] = str(t.get("id"))
            except Exception:
                pass
        return cls._TAG_CACHE.get(tag_name.lower(), "")

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    @staticmethod
    def _extract_slug(url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        return parts[-1] if parts else ""

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        slug = self._extract_slug(manga_url)
        if not slug:
            raise ScrapeError(f"Could not extract slug from {manga_url}")

        api_url = f"{API_BASE}/series/{slug}"
        resp = self.fetch(api_url)
        if resp.status_code != 200:
            raise ScrapeError(f"Chikari series info failed: HTTP {resp.status_code}")

        d = resp.json()
        title = d.get("title") or "Unknown"
        cover = d.get("cover_url")
        desc = d.get("description")
        status = (d.get("status") or "Releasing").title()
        genres = [g["name"] for g in d.get("genres", []) if isinstance(g, dict) and g.get("name")]
        tags = [t["name"] for t in d.get("tags", []) if isinstance(t, dict) and t.get("name")]
        authors = [a["name"] for a in d.get("authors", []) if isinstance(a, dict) and a.get("name")]
        stype = classify_type(tags=genres + tags, text=d.get("type")) or self.default_series_type

        return {
            "url": f"{SITE}/series/{slug}",
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": (genres + tags)[:25],
            "status": status,
            "authors": authors,
            "artists": [],
            "series_type": stype,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        slug = self._extract_slug(manga_url)
        if not slug:
            return []

        api_url = f"{API_BASE}/series/{slug}/chapters"
        resp = self.fetch(api_url)
        if resp.status_code != 200:
            return []

        data = resp.json()
        items = data.get("items") or (data if isinstance(data, list) else [])
        chapters = []
        for it in items:
            num = it.get("number")
            if num is None:
                continue
            num_str = f"{int(num)}" if float(num).is_integer() else f"{num}"
            name = it.get("title") or f"Chapter {num_str}"
            if not name.lower().startswith("chapter"):
                name = f"Chapter {num_str}: {name}"
            ch_url = f"{API_BASE}/series/{slug}/chapters/{num_str}"
            chapters.append({
                "url": ch_url,
                "name": name,
                "referer": f"{SITE}/series/{slug}",
                "source": self.id,
            })

        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        resp = self.fetch(chapter_url)
        if resp.status_code != 200:
            return []

        d = resp.json()
        pages = d.get("pages") or d.get("images") or []
        images = []
        for p in pages:
            if isinstance(p, str) and p.strip():
                images.append(p.strip())
            elif isinstance(p, dict) and p.get("url"):
                images.append(p["url"].strip())
        return images
