"""VyManga source scraper for Mangasurf.

Adapted from vymanga-downloader with full integration for the Mangasurf Source API.
Features:
- Automated adult warning bypass
- Robust chapter list extraction
- Vertical reader image parsing
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://mangavyvy.net"
ALT_SITES = ("https://mangavyvy.net", "https://mangavyvy.com", "https://vymanga.net", "https://vymanga.com")


class VymangaSource(Source):
    id = "vymanga"
    name = "VyManga"
    base_url = SITE
    domains = ("mangavyvy.net", "mangavyvy.com", "vymanga.net", "vymanga.com", "vymanga.co")

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Latest Updates", "Popularity", "Rating", "Alphabetical")
    browse_sorts = ("Trending", "Latest Updates", "Popularity", "Top Rated")

    GENRES = (
        "Action", "Adult", "Adventure", "Comedy", "Cooking", "Doujinshi",
        "Drama", "Ecchi", "Fantasy", "Gender Bender", "Harem", "Historical",
        "Horror", "Isekai", "Josei", "Manhua", "Manhwa", "Martial Arts",
        "Mature", "Mecha", "Medical", "Mystery", "Psychological", "Romance",
        "School Life", "Sci-Fi", "Seinen", "Shoujo", "Shounen",
        "Slice of Life", "Smut", "Sports", "Supernatural", "Tragedy", "Webtoons",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": f"{SITE}/",
            "Cookie": "warning=1; adult=1; over18=1",
        })
        return h

    def genres(self) -> list:
        return [{"id": name.lower().replace(" ", "-"), "name": name} for name in self.GENRES]

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 32, **_) -> list:
        page = max(1, int(page or 1))
        for site_url in ALT_SITES:
            try:
                if genre:
                    slug = genre.lower().replace(" ", "-")
                    url = f"{site_url}/genre/{slug}?page={page}"
                else:
                    url = f"{site_url}/?page={page}" if page > 1 else f"{site_url}/"

                response = self.fetch(url, max_retries=1, timeout=5)
                res = self._parse_listing(response, limit, base_site=site_url)
                if res:
                    return res
            except Exception as e:
                logger.debug("VyManga browse on %s failed: %s", site_url, e)
        return []

    def search(self, query: str, limit: int = 32, page: int = 1, **_) -> list:
        query_str = (query or "").strip()
        if not query_str:
            return []

        page_val = max(1, int(page or _.get("page", 1) or 1))
        for site_url in ALT_SITES:
            try:
                url = f"{site_url}/search?q={quote(query_str)}&page={page_val}" if page_val > 1 else f"{site_url}/search?q={quote(query_str)}"
                response = self.fetch(url, max_retries=1, timeout=5)
                results = self._parse_listing(response, limit=max(limit, 30), base_site=site_url)
                if results:
                    if query_str:
                        results = self.filter_and_rank(results, query_str)
                    return results[:limit]
            except Exception as e:
                logger.debug("VyManga search on %s failed: %s", site_url, e)
        return []

    def _parse_listing(self, response, limit=32, base_site=SITE):
        soup = BeautifulSoup(response.content, "html.parser")
        results, seen = [], set()

        items = soup.select("div.comic-item, div.item, div.row > div.col-md-6, a[href*='/manga/']")

        for item in items:
            link = item if item.name == "a" else item.select_one("a[href*='/manga/']")
            if not link or not link.get("href"):
                continue
            href = urljoin(base_site, link["href"])
            if href in seen or "/chapter" in href:
                continue
            seen.add(href)

            title_el = item.select_one(".comic-title, h3, h4, .title, strong")
            title = title_el.get_text(strip=True) if title_el else link.get("title", "Unknown")

            img = item.select_one("img")
            cover = None
            if img:
                cover = img.get("data-src") or img.get("src")
                if cover and cover.startswith("/"):
                    cover = urljoin(base_site, cover)

            results.append(self._result(title, href, cover=cover))
            if len(results) >= limit:
                break

        return results

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        title_el = soup.select_one("h1.title, h1")
        title = title_el.get_text(strip=True) if title_el else "Unknown Manga"

        cover = None
        img = soup.select_one("div.img-desc img, div.col-sm-4 img, img.thumbnail")
        if img:
            cover = img.get("data-src") or img.get("src")
            if cover:
                cover = urljoin(SITE, cover)

        desc_el = soup.select_one("div.content, div.description, p.desc")
        description = desc_el.get_text(strip=True) if desc_el else ""

        tags = [
            a.get_text(strip=True)
            for a in soup.select("a[href*='/genre/'], .genres a")
            if a.get_text(strip=True)
        ]

        authors = [
            a.get_text(strip=True)
            for a in soup.select("a[href*='/author/'], .author a")
            if a.get_text(strip=True)
        ]

        status_el = soup.select_one("span.status, div.status")
        status = status_el.get_text(strip=True) if status_el else "Ongoing"

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags,
            "status": status,
            "authors": authors,
            "artists": [],
            "source": self.id,
            "source_name": self.name,
        }

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        chapter_list_div = soup.find("div", class_="list")
        if chapter_list_div:
            chapter_links = chapter_list_div.find_all("a", class_="list-group-item")
        else:
            chapter_links = soup.select("a[id^=chapter-], a[href*='/chapter-']")

        chapters = []
        for link in reversed(chapter_links):
            href = link.get("href")
            if not href:
                continue
            href = urljoin(SITE, href)

            text = link.get_text(" ", strip=True)
            match = re.search(r"Chapter\s+(\d+(?:\.\d+)?)(?:\s*:\s*(.*))?", text, re.I)
            if match:
                ch_num = match.group(1)
                ch_title = match.group(2)
                name = f"Chapter {ch_num} - {ch_title}" if ch_title else f"Chapter {ch_num}"
                sort_num = float(ch_num)
            else:
                name = text
                sort_num = len(chapters) + 1.0

            chapters.append({
                "url": href,
                "name": name,
                "source": self.id,
                "sort_num": sort_num,
            })

        chapters.sort(key=lambda x: x.get("sort_num", 0))
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        response = self.fetch(chapter_url)
        soup = BeautifulSoup(response.content, "html.parser")

        urls = []
        for img in soup.select("#main_reader img, .reader-images img, img[data-src], img.chapter-img"):
            src = img.get("data-src") or img.get("src")
            if src and not src.endswith("loading.gif") and "placeholder" not in src:
                src = urljoin(SITE, src)
                urls.append(src)

        seen = set()
        clean = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                clean.append(u)
        return clean
