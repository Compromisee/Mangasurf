"""MangaDistrict source scraper for Mangasurf.

Supports search, browse, series details, and chapter image downloads from mangadistrict.com.
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://mangadistrict.com"


class MangaDistrictSource(Source):
    id = "mangadistrict"
    name = "MangaDistrict"
    base_url = SITE
    domains = ("mangadistrict.com", "www.mangadistrict.com")
    needs_flaresolverr = False

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Relevance", "Latest", "Rating", "Trending", "Alphabetical")
    browse_sorts = ("Trending", "Popularity", "Latest Updates", "Rating")

    _SORTS = {
        "Trending": "trending",
        "Popularity": "views",
        "Latest Updates": "latest",
        "Latest": "latest",
        "Rating": "rating",
        "Alphabetical": "alphabet",
        "Relevance": "relevance",
    }

    GENRES = (
        "Action", "Adult", "Adventure", "Anime", "Cartoon", "Comedy", "Comic",
        "Cooking", "Detective", "Doujinshi", "Drama", "Ecchi", "Fantasy",
        "Gender Bender", "Harem", "Historical", "Horror", "Isekai", "Josei",
        "Live action", "Magic", "Manga", "Manhua", "Manhwa", "Martial Arts",
        "Mature", "Mecha", "Medical", "Mystery", "One shot", "Psychological",
        "Romance", "School Life", "Sci-fi", "Seinen", "Shoujo", "Shounen",
        "Slice of Life", "Smut", "Sports", "Super Power", "Supernatural",
        "Thriller", "Tragedy", "Webtoon", "Yaoi", "Yuri",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Referer": f"{SITE}/",
        })
        return h

    @staticmethod
    def slug_of(url: str) -> str:
        url = url.rstrip("/")
        parts = url.split("/")
        return parts[-1] if parts else ""

    def genres(self) -> list:
        return [{"id": name.lower(), "name": name} for name in self.GENRES]

    def _parse_cards(self, soup: BeautifulSoup, limit: int = 32) -> list:
        results, seen = [], set()
        cards = soup.select(
            "div.c-tabs-item__content, div.page-item-detail, div.manga-item, div.row.c-row > div, div.tab-thumb"
        )
        if not cards:
            cards = soup.select("a[href*='/read-scan/'], a[href*='/manga/']")

        for card in cards:
            link = card if card.name == "a" else card.select_one("a[href*='/read-scan/'], a[href*='/manga/'], .post-title a")
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"].strip())
            if href in seen or "/chapter" in href or "/page/" in href:
                continue
            seen.add(href)

            title_el = card.select_one(".post-title a, .post-title h3, h3 a, h4 a, h3, h4") or link
            title = title_el.get_text(strip=True) if title_el else link.get("title", "Unknown")

            img = card.select_one("img")
            cover = None
            if img is not None:
                cover = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
                if cover and cover.startswith("/"):
                    cover = urljoin(SITE, cover)

            status_el = card.select_one(".status, .mg_status, .post-status")
            status = status_el.get_text(strip=True) if status_el else None

            results.append(self._result(title, href, cover=cover, status=status))
            if len(results) >= limit:
                break
        return results

    def search(self, query: str, limit: int = 32, sort: str = None, page: int = 1, **_) -> list:
        query_str = (query or "").strip()
        if not query_str:
            return self.browse(sort=sort, limit=limit, page=page)

        page_val = max(1, int(page or 1))
        if page_val > 1:
            url = f"{SITE}/page/{page_val}/?s={quote(query_str)}&post_type=wp-manga"
        else:
            url = f"{SITE}/?s={quote(query_str)}&post_type=wp-manga"

        if sort and sort in self._SORTS:
            url += f"&m_orderby={self._SORTS[sort]}"

        try:
            resp = self.fetch(url, timeout=7)
            soup = BeautifulSoup(resp.content, "html.parser")
            results = self._parse_cards(soup, limit)
            if query_str and results:
                results = self.filter_and_rank(results, query_str)
            return results[:limit]
        except ScrapeError as e:
            logger.warning("MangaDistrict search failed: %s", e)
            return []

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 32, **_) -> list:
        page_val = max(1, int(page or 1))
        order = self._SORTS.get(sort or "Trending", "views")

        if genre:
            slug = genre.strip().lower().replace(" ", "-")
            url = f"{SITE}/manga-genre/{quote(slug)}/page/{page_val}/?m_orderby={order}"
        else:
            url = f"{SITE}/read-scan/page/{page_val}/?m_orderby={order}"

        try:
            resp = self.fetch(url, timeout=7)
            soup = BeautifulSoup(resp.content, "html.parser")
            return self._parse_cards(soup, limit)
        except ScrapeError:
            # Fallback to /manga/ prefix
            try:
                url_alt = f"{SITE}/manga/page/{page_val}/?m_orderby={order}"
                resp_alt = self.fetch(url_alt, timeout=7)
                return self._parse_cards(BeautifulSoup(resp_alt.content, "html.parser"), limit)
            except Exception as e:
                logger.warning("MangaDistrict browse failed: %s", e)
                return []

    def get_manga_info(self, manga_url: str) -> dict:
        slug = self.slug_of(manga_url)
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.content, "html.parser")

        title_el = soup.select_one("div.post-title h1, div.post-title h3, h1")
        title = title_el.get_text(strip=True) if title_el else slug.replace("-", " ").title()

        img = soup.select_one("div.summary_image img, div.tab-summary img, .summary_image img")
        cover = img.get("data-src") or img.get("src") if img else None
        if cover and cover.startswith("/"):
            cover = urljoin(SITE, cover)

        desc_el = soup.select_one("div.description-summary, div.summary__content, .manga-excerpt")
        description = desc_el.get_text("\n", strip=True) if desc_el else ""

        tags = [
            a.get_text(strip=True) for a in soup.select("div.genres-content a, .genres a")
            if a.get_text(strip=True)
        ]

        authors = [
            a.get_text(strip=True) for a in soup.select("div.author-content a, .author a")
            if a.get_text(strip=True) and a.get_text(strip=True).lower() != "updating"
        ]

        artists = [
            a.get_text(strip=True) for a in soup.select("div.artist-content a, .artist a")
            if a.get_text(strip=True) and a.get_text(strip=True).lower() != "updating"
        ]

        status_el = soup.select_one("div.post-status div.summary-content, .post-status")
        status = status_el.get_text(strip=True) if status_el else "Ongoing"

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags,
            "status": status,
            "authors": authors,
            "artists": artists,
            "source": self.id,
            "source_name": self.name,
        }

    def get_chapters(self, manga_url: str) -> list:
        # Try loading chapters directly from manga HTML or AJAX endpoint
        try:
            resp = self.fetch(manga_url)
            soup = BeautifulSoup(resp.content, "html.parser")
            chapters = self._parse_chapters(soup)
            if chapters:
                return chapters
        except Exception:
            pass

        # Try AJAX chapters endpoint
        try:
            ajax_url = f"{manga_url.rstrip('/')}/ajax/chapters/"
            resp_ajax = self.session.post(ajax_url, headers=self.headers(), timeout=6)
            if resp_ajax.ok and resp_ajax.content:
                soup_ajax = BeautifulSoup(resp_ajax.content, "html.parser")
                chapters = self._parse_chapters(soup_ajax)
                if chapters:
                    return chapters
        except Exception as e:
            logger.debug("MangaDistrict AJAX chapters fallback: %s", e)

        return []

    def _parse_chapters(self, soup: BeautifulSoup) -> list:
        chapters = []
        rows = soup.select("li.wp-manga-chapter, ul.sub-chap-list li, .listing-chapters_sub-head li")
        for row in rows:
            link = row.select_one("a")
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"].strip())
            name = link.get_text(strip=True) or "Chapter"
            date_el = row.select_one("span.chapter-release-date, i")
            date = date_el.get_text(strip=True) if date_el else ""

            match = re.search(r"(\d+(?:\.\d+)?)", name)
            sort_val = float(match.group(1)) if match else 0.0

            chapters.append({
                "url": href,
                "name": name,
                "date": date,
                "source": self.id,
                "sort_no": sort_val,
            })

        chapters.sort(key=lambda c: c.get("sort_no", 0))
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        resp = self.fetch(chapter_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        images = []

        for img in soup.select("div.reading-content img, div.page-break img, img.wp-manga-chapter-img"):
            src = (
                img.get("data-src")
                or img.get("data-lazy-src")
                or img.get("data-full-url")
                or img.get("src")
                or ""
            ).strip()
            if src and src.startswith("http") and not src.endswith("loading.gif"):
                images.append(src)

        return images
