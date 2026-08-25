"""MangaTitan (mangatitan.com) source scraper for Mangasurf.

MangaTitan is a fast global manga reader that mirrors hundreds of series
across ``/en/`` (English) and other language roots. Verified live:
- search  ``GET /en/?s=<q>&lang=en`` returns ``.series-card`` entries
- series  ``GET /en/manga/<slug>.html`` -> ``og:image`` cover, description
- chapters ``.chapters-list`` anchors (newest first; we re-order oldest first)
- pages   chapter page ``.entry-content img[data-src]`` lazy-loaded CDN images
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source

logger = logging.getLogger(__name__)

SITE = "https://www.mangatitan.com"


class MangaTitanSource(Source):
    id = "mangatitan"
    name = "MangaTitan"
    base_url = SITE
    domains = ("mangatitan.com", "cdn.mangatitan.com")

    supports_search = True
    supports_browse = True
    supports_genres = True
    default_series_type = None

    search_sorts = ("Relevance",)
    browse_sorts = ("Latest", "Popular")

    # Static taxonomy mirroring MangaTitan's genre labels so the genre picker
    # and multi-source genre aggregation have something stable to work with.
    GENRES = (
        "Action", "Adventure", "Comedy", "Cooking", "Doujinshi", "Drama",
        "Ecchi", "Fantasy", "Gender Bender", "Harem", "Historical", "Horror",
        "Isekai", "Josei", "Manhua", "Manhwa", "Martial Arts", "Mature",
        "Mecha", "Medical", "Mystery", "Psychological", "Romance", "School Life",
        "Sci-Fi", "Seinen", "Shoujo", "Shounen", "Slice of Life", "Smut",
        "Sports", "Supernatural", "Thriller", "Tragedy", "Webtoon", "Wuxia",
        "Yaoi", "Yuri",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0.0.0 Safari/537.36"),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{SITE}/en/",
        })
        return h

    # ------------------------------------------------------------ search
    def search(self, query: str, limit: int = 32, **_) -> list:
        page = self.fetch(
            f"{SITE}/en/", params={"s": query.strip(), "lang": "en"}
        )
        soup = BeautifulSoup(page.text, "html.parser")
        results = []
        for card in soup.select(".series-grid .series-card"):
            link = card.find("a", class_="series-card-link") or card.find("a", href=True)
            if link is None:
                continue
            url = link.get("href")
            if not url:
                continue
            title = link.get("title") or link.get_text(" ", strip=True)
            title = re.sub(r"^\d+", "", title or "").strip()  # drop chapter counters
            cover = self._cover_from_card(card)
            results.append(self._result(title, url, cover=cover))
            if len(results) >= limit:
                break
        return self.filter_and_rank(results, query)

    @staticmethod
    def _cover_from_card(card) -> str:
        thumb = card.select_one(".series-card-thumb")
        if thumb is None:
            return None
        style = thumb.get("style", "")
        m = re.search(r"url\(['\"]?(https?://[^)'\"]+)['\"]?\)", style)
        return m.group(1) if m else None

    # ------------------------------------------------------------ browse
    def browse(self, sort: str = "Latest", genre: str = None, page: int = 1,
               limit: int = 32, **_) -> list:
        page = max(1, int(page or 1))
        url = f"{SITE}/en/page/{page}/" if page > 1 else f"{SITE}/en/"
        resp = self.fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")

        results = []
        seen = set()

        # Homepage and most index pages render the compact ".series-card"
        # grid (one card per series, cover in the thumb background).
        cards = soup.select(".series-grid .series-card") or soup.select(".series-card")
        for card in cards:
            link = card.find("a", class_="series-card-link") or card.find("a", href=True)
            if link is None:
                continue
            url = link.get("href")
            if not url:
                continue
            if url in seen:
                continue
            seen.add(url)
            title = link.get("title") or link.get_text(" ", strip=True)
            title = re.sub(r"^\s*\d+\s*", "", title or "").strip()   # drop chapter counters
            results.append(self._result(title, url, cover=self._cover_from_card(card)))
            if len(results) >= limit:
                break

        # Paginated archive pages flip to a blog layout: each ".entry-archive"
        # is a per-chapter post, and the canonical series link lives in
        # ".entry-footer". Parse both the title and the series URL, and dedupe
        # so browsing page 2+ returns unique series (not 10x the same one).
        if len(results) < limit:
            for entry in soup.select(".entry-archive"):
                footer = entry.select_one(".entry-footer a[href*='/manga/']")
                if footer is None:
                    footer = entry.select_one(".entry-title a[href*='/manga/'], a[href*='/manga/']")
                if footer is None or not footer.get("href"):
                    continue
                series_url = urljoin(SITE, footer["href"])
                if series_url in seen:
                    continue
                seen.add(series_url)
                title = (entry.select_one(".entry-title") or entry).get_text(" ", strip=True)
                # strip the trailing ", Chapter N" suffix the title carries
                title = re.sub(r",?\s*Chapter\s+[\d.]+.*$", "", title, flags=re.I).strip()
                if not title:
                    title = re.sub(r"[^/]+$", "", series_url).strip("/").replace("-", " ").title()
                results.append(self._result(title, series_url))
                if len(results) >= limit:
                    break

        return results

    # ------------------------------------------------------------- info
    def get_manga_info(self, manga_url: str) -> dict:
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        title = self._series_title(soup, manga_url)
        cover = None
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            cover = og["content"]
        desc_meta = soup.find("meta", attrs={"name": "description"})
        desc = (desc_meta.get("content") or "").strip() if desc_meta else ""
        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": [],
            "status": None,
            "authors": [],
        }

    @staticmethod
    def _series_title(soup, url: str) -> str:
        link = soup.select_one(".series-title a, h1.series-title")
        if link:
            return link.get_text(" ", strip=True)
        raw = re.sub(r"https?://[^/]+", "", url).strip("/").split("/")[-1]
        return raw.replace("-", " ").replace(".html", "").title()

    # -------------------------------------------------------- chapters
    def get_chapters(self, manga_url: str) -> list:
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        seen = set()
        for a in soup.select(".chapters-list a[href]"):
            href = urljoin(manga_url, a["href"])
            if href in seen:
                continue
            seen.add(href)
            name = a.get_text(" ", strip=True) or a.get("title") or href.rsplit("/", 1)[-1]
            items.append({"url": href, "name": name})
        # The server renders newest-first; the engine expects OLDEST-first.
        items.reverse()
        return items

    # ---------------------------------------------------------- images
    def get_chapter_images(self, chapter) -> list:
        url = self._chapter_url(chapter)
        resp = self.fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for img in soup.select(".entry-content img[data-src], .entry-content noscript img"):
            src = img.get("data-src") or img.get("src")
            if not src:
                continue
            src = urljoin(url, src)
            if "data:image" in src:
                continue
            if src not in urls:
                urls.append(src)
        if not urls:
            # fall back to any CDN image in the reader
            for img in soup.find_all("img", src=True):
                src = img["src"]
                if "cdn.mangatitan.com" in src:
                    urls.append(src)
        return urls

    # -------------------------------------------------------- genres
    def genres(self) -> list:
        return [{
            "id": name.lower().replace(" ", "-").replace("'", ""),
            "name": name,
        } for name in self.GENRES]
