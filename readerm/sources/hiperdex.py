"""Hiperdex (hiperdex.com) source scraper for Mangasurf.

High-performance tRPC API integration for adult & webtoon series.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin, urlparse

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://hiperdex.com"
CFG_AUTH = "yceqt7qgu004"


class HiperdexSource(Source):
    id = "hiperdex"
    name = "Hiperdex"
    base_url = SITE
    domains = (
        "hiperdex.com", "www.hiperdex.com",
        "hiperdex.tv", "www.hiperdex.tv",
        "r2d2storage.com", "cloud-7.r2d2storage.com", "i1.r2d2storage.com",
    )

    default_series_type = "Manhwa"
    cover_needs_referer = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Relevance",)
    browse_sorts = ("Trending", "Latest")

    GENRES = (
        ("action", "Action"),
        ("adult", "Adult"),
        ("comedy", "Comedy"),
        ("drama", "Drama"),
        ("ecchi", "Ecchi"),
        ("fantasy", "Fantasy"),
        ("harem", "Harem"),
        ("isekai", "Isekai"),
        ("manhwa", "Manhwa"),
        ("mature", "Mature"),
        ("romance", "Romance"),
        ("smut", "Smut"),
        ("supernatural", "Supernatural"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session.headers.update(self._headers())

    def _headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "x-cfg-auth": CFG_AUTH,
            "Referer": f"{SITE}/",
            "Origin": SITE,
        }

    def _ensure_session(self):
        if not self.session.cookies.get("__st"):
            try:
                self.session.get(SITE, headers=self._headers(), timeout=10)
            except Exception:
                pass

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        self._ensure_session()
        inp = quote(json.dumps({"0": {"json": {"query": query, "page": page, "limit": limit}}}))
        url = f"{SITE}/api/trpc/search.query?batch=1&input={inp}"

        try:
            resp = self.session.get(url, headers=self._headers(), timeout=12)
            if resp.status_code == 200:
                json_arr = resp.json()
                res_obj = json_arr[0].get("result", {}).get("data", {}).get("json", {})
                hits = res_obj.get("hits") or (res_obj if isinstance(res_obj, list) else [])
                results = []
                for s in hits[:limit]:
                    title = s.get("title") or "Untitled"
                    slug = s.get("slug") or ""
                    href = f"{SITE}/manga/{slug}" if slug else ""
                    cover = s.get("coverImage") or s.get("coverUrl")
                    stype = classify_type(text=s.get("type")) or self.default_series_type

                    results.append(self._result(
                        title, href, cover=cover,
                        series_type=stype,
                    ))
                return results
        except Exception as e:
            logger.error("hiperdex search failed: %s", e)
            return []

    def browse(self, sort: str = "Trending", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        self._ensure_session()
        page = max(1, int(page or 1))

        if page == 1 and not genre and sort == "Trending":
            inp = quote(json.dumps({"0": {"json": {}}}))
            url = f"{SITE}/api/trpc/recommendations.trending?batch=1&input={inp}"
        else:
            q_term = genre if genre else ""
            inp = quote(json.dumps({"0": {"json": {"query": q_term, "page": page, "limit": limit}}}))
            url = f"{SITE}/api/trpc/search.query?batch=1&input={inp}"

        try:
            resp = self.session.get(url, headers=self._headers(), timeout=12)
            if resp.status_code == 200:
                json_arr = resp.json()
                res_data = json_arr[0].get("result", {}).get("data", {}).get("json", {})
                if isinstance(res_data, dict):
                    items = res_data.get("hits") or res_data.get("items") or []
                elif isinstance(res_data, list):
                    items = res_data
                else:
                    items = []

                results = []
                for s in items[:limit]:
                    title = s.get("title") or "Untitled"
                    slug = s.get("slug") or ""
                    href = f"{SITE}/manga/{slug}" if slug else ""
                    cover = s.get("coverImage") or s.get("coverUrl")
                    stype = classify_type(text=s.get("type")) or self.default_series_type

                    results.append(self._result(
                        title, href, cover=cover,
                        series_type=stype,
                    ))
                return results
        except Exception as e:
            logger.error("hiperdex browse failed: %s", e)
            return []

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    @staticmethod
    def _extract_slug(url: str) -> str:
        match = re.search(r"/manga/([^/?#]+)", url)
        if match:
            return match.group(1)
        path = urlparse(url).path.rstrip("/")
        parts = [p for p in path.split("/") if p and p != "manga"]
        return parts[0] if parts else ""

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        slug = self._extract_slug(manga_url)
        if not slug:
            raise ScrapeError(f"Could not extract slug from {manga_url}")

        self._ensure_session()
        inp = quote(json.dumps({"0": {"json": {"slug": slug}}}))
        url = f"{SITE}/api/trpc/series.bySlug?batch=1&input={inp}"

        resp = self.session.get(url, headers=self._headers(), timeout=12)
        if resp.status_code != 200:
            raise ScrapeError(f"Hiperdex series.bySlug failed: HTTP {resp.status_code}")

        json_arr = resp.json()
        d = json_arr[0].get("result", {}).get("data", {}).get("json", {})
        title = d.get("title") or slug.title()
        cover = d.get("coverImage") or d.get("coverUrl")
        desc = d.get("synopsis") or d.get("description")
        status = (d.get("status") or "Ongoing").title()
        genres = [g["name"] for g in d.get("genres", []) if isinstance(g, dict) and g.get("name")]
        stype = classify_type(tags=genres, text=d.get("type")) or self.default_series_type

        return {
            "url": f"{SITE}/manga/{slug}",
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": genres[:25],
            "status": status,
            "authors": [a["name"] for a in d.get("authors", []) if isinstance(a, dict) and a.get("name")],
            "artists": [],
            "series_type": stype,
            "source": self.id,
            "source_name": self.name,
            "series_id": d.get("id"),
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        info = self.get_manga_info(manga_url)
        series_id = info.get("series_id")
        slug = self._extract_slug(manga_url)
        if not series_id:
            return []

        self._ensure_session()
        inp = quote(json.dumps({"0": {"json": {"seriesId": series_id}}}))
        url = f"{SITE}/api/trpc/series.chapters?batch=1&input={inp}"

        resp = self.session.get(url, headers=self._headers(), timeout=12)
        if resp.status_code != 200:
            return []

        items = resp.json()[0].get("result", {}).get("data", {}).get("json", [])
        chapters = []
        for it in items:
            ch_num = it.get("number")
            ch_id = it.get("id")
            title = it.get("title") or ""
            name = f"Chapter {ch_num}"
            if title and title != "[END]":
                name += f": {title}"
            elif title == "[END]":
                name += " [END]"

            # Pack info into chapter URL query
            ch_url = f"{SITE}/manga/{slug}/chapter/{ch_num}?cid={ch_id}&sid={series_id}"
            chapters.append({
                "url": ch_url,
                "name": name,
                "referer": f"{SITE}/manga/{slug}",
                "source": self.id,
                "chapter_id": ch_id,
                "chapter_num": ch_num,
                "series_slug": slug,
            })

        # Oldest first
        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        
        # 1. Extract slug from chapter dict or URL
        slug = chapter.get("series_slug") if isinstance(chapter, dict) else None
        if not slug:
            slug_match = re.search(r"/manga/([^/?#]+)", chapter_url)
            slug = slug_match.group(1) if slug_match else self._extract_slug(chapter_url)

        # 2. Extract chapterId and chapterNumber
        cid_match = re.search(r"cid=(\d+)", chapter_url)
        num_match = re.search(r"/chapter/([\d.]+)", chapter_url)
        cid = int(chapter.get("chapter_id") if isinstance(chapter, dict) and chapter.get("chapter_id") else (cid_match.group(1) if cid_match else 0))
        num_raw = chapter.get("chapter_num") if isinstance(chapter, dict) and chapter.get("chapter_num") is not None else (num_match.group(1) if num_match else 1)
        num = int(float(num_raw)) if float(num_raw).is_integer() else float(num_raw)

        if not cid or not slug:
            return []

        self._ensure_session()
        inp = quote(json.dumps({"0": {"json": {"seriesSlug": slug, "chapterNumber": num, "chapterId": cid}}}))
        url = f"{SITE}/api/trpc/reader.chapterPages?batch=1&input={inp}"

        resp = self.session.get(url, headers=self._headers(), timeout=12)
        if resp.status_code != 200:
            return []

        pages = resp.json()[0].get("result", {}).get("data", {}).get("json", [])
        images = []
        for p in pages:
            u = p.get("webpUrl") or p.get("avifUrl") or p.get("url") or p.get("imageUrl")
            if u and u.strip():
                images.append(u.strip())
        return images
