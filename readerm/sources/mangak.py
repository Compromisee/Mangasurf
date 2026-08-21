"""MangaK (mangak.io) source scraper for Mangasurf.

Fast Next.js SSR reader for high-quality Manhwa, Manga, and Manhua.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://mangak.io"


class MangaKSource(Source):
    id = "mangak"
    name = "MangaK"
    base_url = SITE
    domains = (
        "mangak.io", "www.mangak.io",
        "resmk.org", "rx.resmk.org",
        "qvzre.org", "rx.qvzre.org", "qvzra.org", "rx.qvzra.org",
    )

    default_series_type = "Manhwa"
    cover_needs_referer = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{SITE}/",
            "Origin": SITE,
        })

    search_sorts = ("Relevance",)
    browse_sorts = ("Trending", "Popular", "Newest", "Rating")

    GENRES = (
        ("action", "Action"),
        ("adventure", "Adventure"),
        ("comedy", "Comedy"),
        ("drama", "Drama"),
        ("fantasy", "Fantasy"),
        ("historical", "Historical"),
        ("horror", "Horror"),
        ("isekai", "Isekai"),
        ("magic", "Magic"),
        ("martial-arts", "Martial Arts"),
        ("mystery", "Mystery"),
        ("romance", "Romance"),
        ("sci-fi", "Sci-Fi"),
        ("shounen", "Shounen"),
        ("supernatural", "Supernatural"),
        ("webtoons", "Webtoons"),
    )

    @staticmethod
    def _parse_next_data(html: str) -> dict:
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        return {}

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        url = f"{SITE}/search?q={quote(query)}"
        if page > 1:
            url += f"&page={page}"

        try:
            resp = self.fetch(url)
            data = self._parse_next_data(resp.text)
            props = data.get("props", {}).get("pageProps", {})
            items = props.get("ssrItems") or props.get("items") or props.get("initialMangas") or []
            results = []
            for s in items[:limit]:
                title = s.get("name") or s.get("title") or "Untitled"
                slug_or_url = s.get("url") or s.get("slug") or ""
                href = urljoin(SITE, slug_or_url)
                cover = s.get("cover") or s.get("thumbnail") or s.get("coverUrl")
                stype = classify_type(text=s.get("type")) or self.default_series_type
                latest_ch = s.get("displayChapters") or (s.get("latestChapters", [{}])[0].get("name") if s.get("latestChapters") else None)

                results.append(self._result(
                    title, href, cover=cover,
                    latest=latest_ch, series_type=stype,
                ))
            return results
        except Exception as e:
            logger.error("mangak search failed: %s", e)
            return []

    def browse(self, sort: str = "Trending", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        if genre:
            url = f"{SITE}/genres/{quote(genre.lower().replace(' ', '-'))}"
        elif sort == "Popular":
            url = f"{SITE}/ranking"
        else:
            url = f"{SITE}/trending/manga"

        if page > 1:
            url += f"?page={page}"

        try:
            resp = self.fetch(url)
            data = self._parse_next_data(resp.text)
            props = data.get("props", {}).get("pageProps", {})
            items = props.get("items") or props.get("ssrItems") or props.get("trendingItems") or props.get("popularItems") or props.get("initialMangas") or []
            results = []
            for s in items[:limit]:
                title = s.get("name") or s.get("title") or "Untitled"
                slug_or_url = s.get("url") or s.get("slug") or ""
                href = urljoin(SITE, slug_or_url)
                cover = s.get("cover") or s.get("thumbnail") or s.get("coverUrl")
                stype = classify_type(text=s.get("type")) or self.default_series_type
                latest_ch = s.get("displayChapters")

                results.append(self._result(
                    title, href, cover=cover,
                    latest=latest_ch, series_type=stype,
                ))
            return results
        except Exception as e:
            logger.error("mangak browse failed: %s", e)
            return []

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        resp = self.fetch(manga_url)
        data = self._parse_next_data(resp.text)
        m = data.get("props", {}).get("pageProps", {}).get("initialManga") or {}

        if not m:
            soup = BeautifulSoup(resp.content, "html.parser")
            h1 = soup.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else "Unknown"
            return {
                "url": manga_url,
                "title": title,
                "cover": None,
                "description": None,
                "tags": [],
                "status": "Ongoing",
                "authors": [],
                "artists": [],
                "series_type": self.default_series_type,
                "source": self.id,
                "source_name": self.name,
            }

        title = m.get("name") or m.get("title") or "Unknown"
        cover = m.get("cover") or m.get("thumbnailUrl") or m.get("coverUrl")
        desc = m.get("summary") or m.get("description")
        status = (m.get("status") or "Ongoing").title()
        genres = [g["name"] for g in m.get("genres", []) if isinstance(g, dict) and g.get("name")]
        authors = [a["name"] for a in m.get("authors", []) if isinstance(a, dict) and a.get("name")]
        artists = [a["name"] for a in m.get("artists", []) if isinstance(a, dict) and a.get("name")]
        stype = classify_type(tags=genres, text=m.get("type")) or self.default_series_type

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": genres[:25],
            "status": status,
            "authors": authors,
            "artists": artists,
            "series_type": stype,
            "source": self.id,
            "source_name": self.name,
            "_raw_manga": m,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        resp = self.fetch(manga_url)
        data = self._parse_next_data(resp.text)
        m = data.get("props", {}).get("pageProps", {}).get("initialManga") or {}
        ch_list = m.get("chapters") or []

        chapters = []
        for ch in ch_list:
            name = ch.get("name") or f"Chapter {ch.get('number', '')}"
            ch_url = ch.get("url") or ""
            if ch_url:
                full_url = urljoin(SITE, ch_url)
                chapters.append({
                    "url": full_url,
                    "name": name,
                    "referer": manga_url,
                    "source": self.id,
                })

        # Reverse from newest-first to oldest-first
        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        resp = self.fetch(chapter_url)
        data = self._parse_next_data(resp.text)
        ch_data = data.get("props", {}).get("pageProps", {}).get("initialChapter") or {}
        images = ch_data.get("images") or ch_data.get("pages") or []

        if images:
            return [img.strip() for img in images if isinstance(img, str) and img.strip()]

        # HTML fallback
        soup = BeautifulSoup(resp.content, "html.parser")
        dom_imgs = []
        for img in soup.select("img.page-image, .reader-area img, img"):
            src = img.get("data-src") or img.get("src")
            if src and any(src.endswith(ext) for ext in (".webp", ".jpg", ".jpeg", ".png", ".avif")):
                full = urljoin(SITE, src)
                if full not in dom_imgs and "logo" not in full:
                    dom_imgs.append(full)
        return dom_imgs
