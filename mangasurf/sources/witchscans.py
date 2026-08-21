"""Witchtoons (formerly Witch Scans) source scraper for Mangasurf.

Supports full high-speed searching, browsing, chapter reading and downloads
from witchtoons.net / witchtoons.com / witchscans.com.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://witchtoons.net"
ALT_SITES = ("https://witchtoons.net", "https://witchtoons.com", "https://witchscans.com")

#: ``ts_reader.run({... "sources":[{"images":[...]}] ...})``
_TS_READER = re.compile(r"ts_reader\.run\((\{.*?\})\);", re.S)


class WitchScansSource(Source):
    id = "witchscans"
    name = "Witchtoons"
    base_url = SITE
    domains = (
        "witchtoons.net", "www.witchtoons.net",
        "witchtoons.com", "www.witchtoons.com",
        "witchscans.com", "www.witchscans.com",
        "media.witchtoons.net",
    )

    default_series_type = "Manhua"
    cover_needs_referer = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Popularity", "Rating", "Title", "Views")

    _ORDER = {
        "Latest Updates": "latest",
        "Trending": "popular",
        "Popularity": "popular",
        "Rating": "rating",
        "Title": "title",
        "Views": "views",
    }

    GENRES = (
        ("action", "Action"),
        ("adventure", "Adventure"),
        ("comedy", "Comedy"),
        ("cultivation", "Cultivation"),
        ("drama", "Drama"),
        ("ecchi", "Ecchi"),
        ("fantasy", "Fantasy"),
        ("harem", "Harem"),
        ("historical", "Historical"),
        ("horror", "Horror"),
        ("isekai", "Isekai"),
        ("magic", "Magic"),
        ("martial-arts", "Martial Arts"),
        ("murim", "Murim"),
        ("mystery", "Mystery"),
        ("romance", "Romance"),
        ("shounen", "Shounen"),
        ("supernatural", "Supernatural"),
        ("system", "System"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{SITE}/",
            "Origin": SITE,
        })

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        # 1. High-speed JSON API search
        api_url = f"{SITE}/api/search?q={quote(query)}"
        try:
            resp = self.fetch(api_url)
            data = resp.json() if resp.status_code == 200 else {}
            series_list = data.get("series") or []
            if series_list:
                results = []
                for s in series_list[:limit]:
                    title = s.get("title") or "Untitled"
                    slug = s.get("slug") or s.get("urlSlug") or ""
                    href = f"{SITE}/series/comic/{slug}" if slug else ""
                    cover = s.get("coverImage")
                    if cover:
                        cover = urljoin(SITE, cover)
                    stype = classify_type(text=s.get("type")) or self.default_series_type
                    ch_count = s.get("chapterCount")
                    latest = f"Chapter {ch_count}" if ch_count else None
                    results.append(self._result(
                        title, href, cover=cover,
                        latest=latest, series_type=stype,
                    ))
                return results
        except Exception as e:
            logger.debug("witchtoons api search failed: %s; falling back to html", e)

        # 2. Fallback to HTML /series?search=
        url = f"{SITE}/series?search={quote(query)}&page={page}"
        try:
            response = self.fetch(url)
            return self._cards_from_html(BeautifulSoup(response.content, "html.parser"), limit)
        except ScrapeError as e:
            logger.error("witchtoons search failed: %s", e)
            return []

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._ORDER.get(sort or "", "latest")
        
        # 1. High-speed JSON API browse
        api_url = f"{SITE}/api/series?page={page}&limit={limit}&sort={order}"
        if genre:
            api_url += f"&genre={self._genre_slug(genre)}"
        
        try:
            resp = self.fetch(api_url)
            if resp.status_code == 200:
                data = resp.json().get("data") or []
                if data:
                    results = []
                    for s in data[:limit]:
                        title = s.get("title") or "Untitled"
                        slug = s.get("slug") or s.get("urlSlug") or ""
                        href = f"{SITE}/series/comic/{slug}" if slug else ""
                        cover = s.get("coverImage")
                        if cover:
                            cover = urljoin(SITE, cover)
                        stype = classify_type(text=s.get("type")) or self.default_series_type
                        
                        latest = None
                        chapters = s.get("chapters") or []
                        if chapters:
                            ch_num = chapters[0].get("number") or chapters[0].get("title")
                            if ch_num:
                                latest = f"Chapter {ch_num}"

                        results.append(self._result(
                            title, href, cover=cover,
                            latest=latest, series_type=stype,
                        ))
                    return results
        except Exception as e:
            logger.debug("witchtoons api browse failed: %s; falling back to html", e)

        # 2. HTML Fallback
        url = f"{SITE}/series?page={page}&sort={order}"
        if genre:
            url += f"&genre={self._genre_slug(genre)}"
        try:
            response = self.fetch(url)
            return self._cards_from_html(BeautifulSoup(response.content, "html.parser"), limit)
        except ScrapeError as e:
            logger.error("witchtoons browse failed: %s", e)
            return []

    def _cards_from_html(self, soup, limit):
        results, seen = [], set()
        for link in soup.select('a[href*="/series/comic/"]'):
            href = urljoin(SITE, link["href"].split("?")[0])
            if href in seen or href == f"{SITE}/series/comic":
                continue
            
            title = link.get("title") or link.get_text(" ", strip=True)
            if not title:
                continue

            cover = None
            img = link.select_one("img")
            if img:
                cover = (img.get("data-src") or img.get("src") or "").strip()
                if cover:
                    cover = urljoin(SITE, cover)

            seen.add(href)
            results.append(self._result(
                title, href, cover=cover,
                series_type=self.default_series_type,
            ))
            if len(results) >= limit:
                break
        return results

    @classmethod
    def _genre_slug(cls, genre) -> str:
        wanted = str(genre or "").strip().lower()
        for slug, label in cls.GENRES:
            if wanted in (slug.lower(), label.lower()):
                return slug
        return quote(wanted.replace(" ", "-"))

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    @staticmethod
    def _extract_slug(manga_url: str) -> str:
        path = urlparse(manga_url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        if parts:
            return parts[-1]
        return ""

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        slug = self._extract_slug(manga_url)
        series_page_url = f"{SITE}/series/comic/{slug}" if slug else manga_url

        response = self.fetch(series_page_url)
        soup = BeautifulSoup(response.content, "html.parser")

        title = slug.replace("-", " ").title() if slug else "Unknown"
        cover = None
        description = None
        tags = []
        stype = self.default_series_type

        # Check JSON-LD Book schema for the exact series metadata
        for s_tag in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(s_tag.string or "")
                if ld.get("@type") == "Book":
                    title = ld.get("name") or title
                    if ld.get("image"):
                        cover = urljoin(SITE, ld["image"])
                    description = ld.get("description")
                    tags = ld.get("genre") or []
                    break
            except Exception:
                pass

        if title == "Unknown" or title == "JavaScript Required":
            h1 = soup.select_one("h1.entry-title, h1")
            if h1 and "JavaScript Required" not in h1.text:
                title = h1.get_text(" ", strip=True)

        if not cover:
            meta = soup.select_one('meta[property="og:image"]')
            cover = (meta.get("content") or "").strip() if meta else ""
            if cover:
                cover = urljoin(SITE, cover)

        return {
            "url": series_page_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:20],
            "status": "Ongoing",
            "authors": [],
            "artists": [],
            "series_type": classify_type(tags=tags) or stype,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        slug = self._extract_slug(manga_url)
        series_base = f"{SITE}/series/comic/{slug}" if slug else manga_url

        # 1. Fetch RSS Feed (cleanest, includes all published chapters with names & URLs)
        feed_url = f"{series_base}/feed.xml"
        try:
            feed_resp = self.fetch(feed_url)
            if feed_resp.status_code == 200:
                root = ET.fromstring(feed_resp.content)
                channel = root.find("channel")
                if channel is not None:
                    items = channel.findall("item")
                    if items:
                        chapters = []
                        for it in items:
                            t_el = it.find("title")
                            l_el = it.find("link")
                            name = t_el.text.strip() if (t_el is not None and t_el.text) else "Chapter"
                            ch_url = l_el.text.strip() if (l_el is not None and l_el.text) else ""
                            if ch_url:
                                chapters.append({
                                    "url": ch_url,
                                    "name": name,
                                    "referer": series_base,
                                    "source": self.id,
                                })
                        # RSS is newest first; engine expects oldest first
                        chapters.reverse()
                        return chapters
        except Exception as e:
            logger.debug("witchtoons feed.xml fetch failed: %s", e)

        # 2. HTML Fallback
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        total_pages = 0
        for s_tag in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(s_tag.string or "")
                if ld.get("@type") == "Book" and ld.get("numberOfPages"):
                    total_pages = int(ld["numberOfPages"])
                    break
            except Exception:
                pass

        if total_pages > 0 and slug:
            return [{
                "url": f"{SITE}/series/comic/{slug}/chapter/{i}",
                "name": f"Chapter {i}",
                "referer": series_base,
                "source": self.id,
            } for i in range(1, total_pages + 1)]

        # 3. DOM chapter links fallback
        chapters, seen = [], set()
        for link in soup.select('a[href*="/chapter/"]'):
            href = urljoin(SITE, link.get("href") or "")
            if not href or href in seen:
                continue
            name = link.get_text(" ", strip=True) or href.rstrip("/").rsplit("/", 1)[-1].title()
            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)

        # Extract /uploads/comic-pages/<slug>/<chapter>/page-<num>.webp?sig=...&exp=...
        raw_matches = re.findall(r'/uploads/comic-pages/[^\s"\'<>\\]+', response.text)
        if raw_matches:
            images, seen = [], set()
            for m in raw_matches:
                clean = m.replace(r"\u0026", "&").replace("&amp;", "&")
                full_url = urljoin(SITE, clean)
                if full_url not in seen:
                    seen.add(full_url)
                    images.append(full_url)
            if images:
                return images

        # Legacy ts_reader fallback
        match = _TS_READER.search(response.text or "")
        if match:
            try:
                payload = json.loads(match.group(1))
                images = []
                for source in payload.get("sources") or []:
                    for url in source.get("images") or []:
                        url = (url or "").strip()
                        if url and url not in images:
                            images.append(url)
                if images:
                    return images
            except Exception:
                pass

        # Legacy #readerarea img tags fallback
        soup = BeautifulSoup(response.content, "html.parser")
        images = []
        for img in soup.select("#readerarea img, .reading-content img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if src:
                full_src = urljoin(SITE, src)
                if full_src not in images:
                    images.append(full_src)
        return images


# Aliases
WitchtoonsSource = WitchScansSource
