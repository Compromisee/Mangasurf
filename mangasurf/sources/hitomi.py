"""Hitomi.la (pornographic) source scraper for Mangasurf.

Supports full gallery extraction, Nozomi binary search, browsing, and image streaming.
Uses the modern gold-usergeneratedcontent.net CDN architecture.
"""

import json
import logging
import re
import struct
from urllib.parse import quote, urljoin

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://hitomi.la"
LTN_BASE = "https://ltn.gold-usergeneratedcontent.net"
DOMAIN2 = "gold-usergeneratedcontent.net"

# Cache for gg.js data (gg_b path prefix and gg_m set)
_GG_CACHE = {"b": "1786888801/", "m_cases": None}


def _ensure_gg_data(source: Source = None):
    if _GG_CACHE["m_cases"] is not None:
        return _GG_CACHE["b"], _GG_CACHE["m_cases"]
    try:
        url = f"{LTN_BASE}/gg.js"
        text = ""
        if source:
            resp = source.fetch(url, timeout=5)
            text = resp.text
        if text:
            # Extract gg.b
            b_match = re.search(r"b\s*:\s*['\"]([^'\"]+)['\"]", text)
            if b_match:
                _GG_CACHE["b"] = b_match.group(1)
            # Extract case numbers
            cases = set()
            for m in re.finditer(r"case\s+(\d+)\s*:", text):
                cases.add(int(m.group(1)))
            _GG_CACHE["m_cases"] = cases
            return _GG_CACHE["b"], cases
    except Exception as e:
        logger.debug("Failed to fetch gg.js: %s", e)
    
    _GG_CACHE["m_cases"] = set()
    return _GG_CACHE["b"], _GG_CACHE["m_cases"]


def _full_image_url(file_info: dict, source: Source = None) -> str:
    h = file_info.get("hash", "")
    if not h or len(h) < 3:
        return ""
    b_val, m_cases = _ensure_gg_data(source)
    try:
        g = int(h[-1] + h[-3:-1], 16)
    except Exception:
        g = 0
    m_val = 1 if g in m_cases else 0

    has_avif = bool(file_info.get("hasavif", 0) or file_info.get("hasavif") is True)
    has_webp = bool(file_info.get("haswebp", 0) or file_info.get("haswebp") is True)
    ext = "avif" if has_avif else ("webp" if has_webp else (file_info.get("name", "page.jpg").split(".")[-1]))

    sub = ("a" if ext == "avif" else ("w" if ext == "webp" else "b")) + str(1 + m_val)
    return f"https://{sub}.{DOMAIN2}/{b_val}{g}/{h}.{ext}"


def _thumbnail_url(file_info: dict, source: Source = None) -> str:
    h = file_info.get("hash", "")
    if not h or len(h) < 3:
        return ""
    _, m_cases = _ensure_gg_data(source)
    try:
        g = int(h[-1] + h[-3:-1], 16)
    except Exception:
        g = 0
    m_val = 1 if g in m_cases else 0
    sub = chr(97 + m_val) + "tn"
    return f"https://{sub}.{DOMAIN2}/avifsmalltn/{h[-1]}/{h[-3:-1]}/{h}.avif"


class HitomiSource(Source):
    id = "hitomi"
    name = "Hitomi.la"
    base_url = SITE
    domains = (
        "hitomi.la", "www.hitomi.la", "ltn.hitomi.la",
        "gold-usergeneratedcontent.net", "ltn.gold-usergeneratedcontent.net",
    )
    adult_only = True
    cover_needs_referer = True
    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Latest", "Popularity", "Alphabetical")
    browse_sorts = ("All", "Manga", "Doujinshi", "English", "Japanese")

    GENRES = (
        "female:sole_female", "male:sole_male", "female:big_breasts", "female:stockings",
        "female:schoolgirl_uniform", "female:maid", "female:swimsuit", "female:glasses",
        "manga", "doujinshi", "artistcg", "gamecg", "anime",
        "romance", "comedy", "drama", "fantasy", "school_life",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "Accept": "application/json, text/html, */*",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Referer": f"{SITE}/",
        })
        return h

    @classmethod
    def extract_gallery_id(cls, url_or_id: str) -> str:
        if not url_or_id:
            return ""
        url_or_id = url_or_id.strip()
        if url_or_id.isdigit():
            return url_or_id
        match = re.search(r"[-/](\d+)\.html", url_or_id)
        if match:
            return match.group(1)
        match_end = re.search(r"/(\d+)/?$", url_or_id)
        if match_end:
            return match_end.group(1)
        match_any = re.search(r"\b(\d{5,8})\b", url_or_id)
        if match_any:
            return match_any.group(1)
        return url_or_id

    def genres(self) -> list:
        return [{"id": name, "name": name.replace("_", " ").title()} for name in self.GENRES]

    def _fetch_gallery_info(self, gallery_id: str) -> dict:
        url = f"{LTN_BASE}/galleries/{gallery_id}.js"
        resp = self.fetch(url, timeout=6)
        text = resp.text
        match = re.search(r"var\s+galleryinfo\s*=\s*(\{.*?\});?\s*$", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        try:
            return resp.json()
        except Exception:
            return json.loads(text.replace("var galleryinfo = ", "").rstrip(";"))

    def _fetch_nozomi_ids(self, nozomi_url: str, page: int = 1, limit: int = 24) -> list:
        page = max(1, int(page or 1))
        start = (page - 1) * limit * 4
        end = start + (limit * 4) - 1
        headers = self.headers()
        headers["Range"] = f"bytes={start}-{end}"
        try:
            resp = self.fetch(nozomi_url, headers=headers, timeout=6)
            data = resp.content
            return [struct.unpack(">I", data[i:i+4])[0] for i in range(0, len(data), 4) if i + 4 <= len(data)]
        except Exception as e:
            logger.debug("Failed to fetch nozomi index %s: %s", nozomi_url, e)
            return []

    def browse(self, sort: str = "All", genre: str = None, page: int = 1, limit: int = 24, **_) -> list:
        page_val = max(1, int(page or 1))
        sort_lower = str(sort or "").strip().lower()

        nozomi_url = f"{LTN_BASE}/index-all.nozomi"
        if sort_lower == "manga" or genre == "manga":
            nozomi_url = f"{LTN_BASE}/type/manga-all.nozomi"
        elif sort_lower == "doujinshi" or genre == "doujinshi":
            nozomi_url = f"{LTN_BASE}/type/doujinshi-all.nozomi"
        elif sort_lower == "english":
            nozomi_url = f"{LTN_BASE}/index-english.nozomi"
        elif sort_lower == "japanese":
            nozomi_url = f"{LTN_BASE}/index-japanese.nozomi"

        ids = self._fetch_nozomi_ids(nozomi_url, page=page_val, limit=limit)
        results = []
        for gid in ids:
            try:
                info = self._fetch_gallery_info(str(gid))
                title = info.get("title") or info.get("japanese_title") or f"Gallery {gid}"
                files = info.get("files") or []
                cover = _thumbnail_url(files[0], self) if files else None
                results.append(self._result(
                    title,
                    f"{SITE}/reader/{gid}.html",
                    cover=cover,
                    type=info.get("type", "Manga"),
                ))
            except Exception:
                continue

        return results

    def search(self, query: str, limit: int = 24, page: int = 1, **_) -> list:
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        # Check if query is a numeric gallery ID
        if query.isdigit() and len(query) >= 5:
            try:
                info = self.get_manga_info(query)
                return [self._result(info["title"], info["url"], cover=info.get("cover"))]
            except Exception:
                pass

        page_val = max(1, int(page or 1))
        q_lower = query.lower()

        # Check for type or language filters in query
        if "manga" in q_lower:
            return self.browse(sort="Manga", page=page_val, limit=limit)
        if "doujinshi" in q_lower:
            return self.browse(sort="Doujinshi", page=page_val, limit=limit)
        if "english" in q_lower:
            return self.browse(sort="English", page=page_val, limit=limit)
        if "japanese" in q_lower:
            return self.browse(sort="Japanese", page=page_val, limit=limit)

        # General browse with filtering
        all_results = self.browse(sort="All", page=page_val, limit=max(limit, 30))
        if query and all_results:
            all_results = self.filter_and_rank(all_results, query)
        return all_results[:limit]

    def get_manga_info(self, manga_url: str) -> dict:
        gid = self.extract_gallery_id(manga_url)
        if not gid:
            raise ScrapeError(f"Could not extract Hitomi gallery ID from {manga_url}")

        info = self._fetch_gallery_info(gid)
        title = info.get("title") or info.get("japanese_title") or f"Gallery {gid}"
        tags = []
        for t in info.get("tags") or []:
            if isinstance(t, dict):
                t_name = t.get("tag")
                if t.get("female"):
                    t_name = f"female:{t_name}"
                elif t.get("male"):
                    t_name = f"male:{t_name}"
                if t_name:
                    tags.append(t_name)
            elif isinstance(t, str):
                tags.append(t)

        authors = [a.get("artist") if isinstance(a, dict) else str(a) for a in (info.get("artists") or [])]
        files = info.get("files") or []
        cover = _thumbnail_url(files[0], self) if files else None

        return {
            "url": f"{SITE}/reader/{gid}.html",
            "title": title,
            "cover": cover,
            "description": f"Hitomi.la gallery {gid} - {info.get('type', 'Manga')} ({info.get('language', 'all')})",
            "tags": tags,
            "status": "Completed",
            "authors": authors,
            "artists": authors,
            "source": self.id,
            "source_name": self.name,
            "format": info.get("type", "Manga"),
        }

    def get_chapters(self, manga_url: str) -> list:
        gid = self.extract_gallery_id(manga_url)
        if not gid:
            return []

        return [{
            "url": f"{SITE}/reader/{gid}.html",
            "name": f"Full Gallery ({gid})",
            "source": self.id,
            "sort_no": 1.0,
        }]

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        gid = self.extract_gallery_id(chapter_url)
        if not gid:
            return []

        try:
            info = self._fetch_gallery_info(gid)
            files = info.get("files") or []
            return [_full_image_url(f, self) for f in files if f.get("hash")]
        except Exception as e:
            logger.warning("Hitomi get_chapter_images failed: %s", e)

        return []
