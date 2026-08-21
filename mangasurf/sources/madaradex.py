"""MadaraDex (madaradex.org) source scraper for Mangasurf.

Madara-powered reader for Manga, Manhwa, and Adult Webtoons.
"""

import logging
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://madaradex.org"


class MadaraDexSource(Source):
    id = "madaradex"
    name = "MadaraDex"
    base_url = SITE
    domains = ("madaradex.org", "www.madaradex.org")

    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Relevance",)
    browse_sorts = ("Latest Updates", "Popularity", "Rating", "Title")

    _ORDER = {
        "Latest Updates": "latest",
        "Trending": "trending",
        "Popularity": "views",
        "Rating": "rating",
        "Title": "alphabet",
    }

    GENRES = (
        ("action", "Action"),
        ("adult", "Adult"),
        ("drama", "Drama"),
        ("ecchi", "Ecchi"),
        ("fantasy", "Fantasy"),
        ("harem", "Harem"),
        ("isekai", "Isekai"),
        ("manhwa", "Manhwa"),
        ("mature", "Mature"),
        ("romance", "Romance"),
        ("smut", "Smut"),
        ("uncensored", "Uncensored"),
    )

    @staticmethod
    def _clean_title(item, title_a, href) -> str:
        title = (title_a.get("title") or "").strip() if title_a else ""
        if not title or title.lower() in ("18+", "18+ uncensored", "uncensored", "manga"):
            pt = item.select_one(".post-title, h3, h4, h5")
            if pt:
                title = pt.get_text(" ", strip=True)
        title = re.sub(r"^(?:18\+\s*(?:Uncensored)?|Uncensored)\s*", "", title, flags=re.I).strip()
        if not title or title.lower() in ("18+", "18+ uncensored", "uncensored", "manga"):
            slug = urlparse(href).path.rstrip("/").split("/")[-1]
            title = slug.replace("-", " ").title()
        return title

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        page = max(1, int(page or 1))
        if query:
            url = f"{SITE}/?s={quote(query)}&post_type=wp-manga"
            if page > 1:
                url = f"{SITE}/page/{page}/?s={quote(query)}&post_type=wp-manga"
        else:
            return self.browse(limit=limit, page=page)

        try:
            resp = self.fetch(url)
            soup = BeautifulSoup(resp.content, "html.parser")
            results, seen = [], set()

            for item in soup.select(".row.c-tabs-item__content, .c-tabs-item__content, .page-item-detail"):
                title_a = item.select_one(".post-title a, h3 a, h4 a, a[href*='/title/']")
                if not title_a or not title_a.get("href"):
                    continue
                href = urljoin(SITE, title_a["href"])
                if href in seen or "/title/" not in href:
                    continue

                title = self._clean_title(item, title_a, href)
                if not title:
                    continue

                cover = None
                img = item.select_one("img")
                if img:
                    cover = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
                    if cover and "dflazy" in cover:
                        cover = img.get("data-src") or img.get("data-lazy-src")
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
        except Exception as e:
            logger.error("madaradex search failed: %s", e)
            return []

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._ORDER.get(sort or "", "latest")
        if genre:
            url = f"{SITE}/genre/{quote(genre.lower().replace(' ', '-'))}/"
            if page > 1:
                url += f"page/{page}/"
        else:
            url = f"{SITE}/page/{page}/?m_orderby={order}&post_type=wp-manga" if page > 1 else f"{SITE}/?m_orderby={order}&post_type=wp-manga"

        try:
            resp = self.fetch(url)
            soup = BeautifulSoup(resp.content, "html.parser")
            results, seen = [], set()

            for item in soup.select(".page-item-detail, .c-tabs-item__content, .item-thumb"):
                title_a = item.select_one(".post-title a, h3 a, h4 a, a[href*='/title/']")
                if not title_a or not title_a.get("href"):
                    continue
                href = urljoin(SITE, title_a["href"])
                if href in seen or "/title/" not in href:
                    continue

                title = self._clean_title(item, title_a, href)
                if not title:
                    continue

                cover = None
                img = item.select_one("img")
                if img:
                    cover = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
                    if cover and "dflazy" in cover:
                        cover = img.get("data-src") or img.get("data-lazy-src")
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
        except Exception as e:
            logger.error("madaradex browse failed: %s", e)
            return []

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.content, "html.parser")

        h1 = soup.select_one(".post-title h1, h1")
        title = h1.get_text(" ", strip=True) if h1 else "Unknown"

        cover = None
        img = soup.select_one(".summary_image img, .tab-summary img")
        if img:
            cover = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if cover and "dflazy" in cover:
                cover = img.get("data-src") or img.get("data-lazy-src")
            if cover:
                cover = urljoin(SITE, cover)

        desc_el = soup.select_one(".description-summary, .summary__content, .manga-excerpt")
        desc = desc_el.get_text(" ", strip=True) if desc_el else None

        tags = [a.get_text(strip=True) for a in soup.select(".genres-content a, .tags-content a")]
        stype = classify_type(tags=tags) or self.default_series_type

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": tags[:25],
            "status": "Ongoing",
            "authors": [a.get_text(strip=True) for a in soup.select(".author-content a")],
            "artists": [a.get_text(strip=True) for a in soup.select(".artist-content a")],
            "series_type": stype,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.content, "html.parser")

        chapters, seen = [], set()
        for a in soup.select(".wp-manga-chapter a, li.wp-manga-chapter a"):
            href = a.get("href")
            if not href or href in seen:
                continue
            name = a.get_text(" ", strip=True)
            match = re.search(r"(Chapter\s*[\d.]+)", name, re.I)
            if match:
                name = match.group(1)

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
        resp = self.fetch(chapter_url)
        soup = BeautifulSoup(resp.content, "html.parser")

        images = []
        for img in soup.select(".page-break img, .reading-content img, #readerarea img, img.wp-manga-chapter-img"):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if src and not src.startswith("data:"):
                clean = src.strip()
                if "dflazy" not in clean and clean not in images:
                    images.append(clean)
        return images
