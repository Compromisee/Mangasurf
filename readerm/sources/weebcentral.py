"""WeebCentral source scraper for Mangasurf.

Adapted from weebcentral_downloader with full integration for the Mangasurf Source API.
Features:
- Long strip image extraction
- Rate limit mitigation and exponential backoff
- Natural sort chapter & image handling
- Full chapter list retrieval via /full-chapter-list
- Cloudflare fallback support via FlareSolverr
"""

import logging
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://weebcentral.com"


def natural_sort_key(text):
    """Natural sort key for filenames and chapter titles."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", str(text))]


class WeebCentralSource(Source):
    id = "weebcentral"
    name = "Weeb Central"
    base_url = SITE
    domains = ("weebcentral.com", "www.weebcentral.com")

    supports_search = True
    supports_browse = True
    supports_genres = True
    needs_flaresolverr = True
    search_sorts = (
        "Best Match",
        "Alphabet",
        "Popularity",
        "Subscribers",
        "Recently Added",
        "Latest Updates",
    )
    browse_sorts = (
        "Trending",
        "Popularity",
        "Subscribers",
        "Recently Added",
        "Latest Updates",
        "Alphabet",
    )

    GENRES = (
        "Action", "Adult", "Adventure", "Comedy", "Doujinshi", "Drama",
        "Ecchi", "Fantasy", "Gender Bender", "Harem", "Hentai", "Historical",
        "Horror", "Isekai", "Josei", "Lolicon", "Martial Arts", "Mature",
        "Mecha", "Mystery", "Psychological", "Romance", "School Life",
        "Sci-fi", "Seinen", "Shotacon", "Shoujo", "Shoujo Ai", "Shounen",
        "Shounen Ai", "Slice of Life", "Smut", "Sports", "Supernatural",
        "Tragedy", "Yaoi", "Yuri",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"{SITE}/",
        })
        return h

    # ---------------------------------------------------------- browse

    def genres(self) -> list:
        return [{"id": name, "name": name} for name in self.GENRES]

    def browse(
        self,
        sort: str = "Trending",
        genre: str = None,
        page: int = 1,
        limit: int = 32,
        status=None,
        series_type=None,
        **_,
    ) -> list:
        page = max(1, int(page or 1))
        limit = max(1, min(100, limit))
        api_sort = "Popularity" if sort in ("Trending", "Popularity") else sort
        if api_sort not in self.search_sorts:
            api_sort = "Popularity"

        url = (
            f"{SITE}/search/data?limit={limit}&offset={(page - 1) * limit}"
            f"&text=&sort={quote(api_sort)}&order=Descending&official=Any"
            f"&display_mode=Full%20Display"
        )
        if genre:
            url += f"&included_tag={quote(str(genre))}"
        if status and status != "Any":
            url += f"&included_status={quote(str(status))}"
        if series_type and series_type != "Any":
            url += f"&included_type={quote(str(series_type))}"

        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("WeebCentral browse failed: %s", e)
            return []
        return self._parse_articles(response, limit)

    # ---------------------------------------------------------- search

    def search(
        self,
        query: str,
        limit: int = 32,
        sort: str = "Best Match",
        order: str = "Ascending",
        official: str = "Any",
        status: str = None,
        series_type: str = None,
        page: int = 1,
        **_,
    ) -> list:
        query = (query or "").strip()
        if not query:
            return []

        if sort not in self.search_sorts:
            sort = "Best Match"
        if order not in ("Ascending", "Descending"):
            order = "Ascending"
        if official not in ("Any", "True", "False"):
            official = "Any"

        page_val = max(1, int(page or _.get("page", 1) or 1))
        offset = (page_val - 1) * limit

        url = (
            f"{SITE}/search/data?limit={limit}&offset={offset}&text={quote(query)}"
            f"&sort={quote(sort)}&order={quote(order)}&official={official}"
            f"&display_mode=Full%20Display"
        )
        if status and status != "Any":
            url += f"&included_status={quote(status)}"
        if series_type and series_type != "Any":
            url += f"&included_type={quote(series_type)}"

        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.warning("WeebCentral search failed: %s", e)
            return []
        return self._parse_articles(response, limit)

    def _parse_articles(self, response, limit=32):
        soup = BeautifulSoup(response.content, "html.parser")
        results, seen = [], set()

        for article in soup.select("article"):
            link = article.select_one("a[href*='/series/']")
            if not link:
                continue
            href = urljoin(SITE, link["href"])
            if href in seen:
                continue
            seen.add(href)

            img = article.select_one("img")
            title = None
            for a in article.select("a[href*='/series/']"):
                if a.find("article") or a.find("img"):
                    continue
                text = a.get_text(strip=True)
                if text:
                    title = text
                    break
            if not title and img is not None:
                title = re.sub(r"\s*cover\s*$", "", img.get("alt", ""), flags=re.I).strip()

            cover = None
            if img is not None and img.get("src"):
                cover = urljoin(SITE, img["src"])

            results.append(
                self._result(
                    title or "Unknown Manga",
                    href,
                    cover=cover,
                )
            )
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------------ info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        title_el = (
            soup.select_one("section[x-data] > section:nth-of-type(2) h1")
            or soup.select_one("h1.text-2xl")
            or soup.select_one("h1")
        )
        title = title_el.get_text(strip=True) if title_el else "Unknown Manga"

        cover = None
        cover_el = soup.select_one("img[alt$='cover']") or soup.select_one("section img")
        if cover_el and cover_el.get("src"):
            cover = urljoin(SITE, cover_el["src"])

        description = None
        desc_el = soup.select_one("li:has(strong:-soup-contains('Description')) p") or soup.select_one("p.text-sm")
        if desc_el:
            description = desc_el.get_text(strip=True)

        tags = [
            a.get_text(strip=True)
            for a in soup.select("li:has(strong:-soup-contains('Tag')) a, a[href*='/tag/']")
            if a.get_text(strip=True)
        ]
        status_el = soup.select_one("li:has(strong:-soup-contains('Status')) a")
        authors = [
            a.get_text(strip=True)
            for a in soup.select("li:has(strong:-soup-contains('Author')) a, a[href*='/author/']")
            if a.get_text(strip=True)
        ]

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags,
            "status": status_el.get_text(strip=True) if status_el else None,
            "authors": authors,
            "artists": [],
            "source": self.id,
            "source_name": self.name,
        }

    # -------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        parsed_url = urlparse(manga_url)
        path_parts = parsed_url.path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] == "series":
            series_id = path_parts[1]
            list_url = f"{SITE}/series/{series_id}/full-chapter-list"
        else:
            list_url = f"{manga_url.rstrip('/')}/full-chapter-list"

        try:
            response = self.fetch(list_url)
        except Exception:
            response = self.fetch(manga_url)

        soup = BeautifulSoup(response.content, "html.parser")
        chapters = []
        chapter_elements = soup.select("div[x-data] > a") or soup.select("a[href*='/chapters/']")

        for element in reversed(chapter_elements):
            href = element.get("href")
            if isinstance(href, list):
                href = href[0]
            if not href or "/chapters/" not in href:
                continue

            name_el = element.select_one("span.flex > span") or element.select_one("span")
            name = name_el.get_text(strip=True) if name_el else "Unknown Chapter"

            date_el = element.select_one("time")
            date_str = date_el.get_text(strip=True) if date_el else None

            chapters.append({
                "url": urljoin(SITE, href),
                "name": name,
                "date": date_str,
                "source": self.id,
            })

        return chapters

    # ----------------------------------------------------------- pages

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        images_url = f"{chapter_url.split('?')[0]}/images?reading_style=long_strip"
        response = self.fetch(images_url)
        soup = BeautifulSoup(response.content, "html.parser")

        urls = []
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src")
            if isinstance(src, list):
                src = src[0]
            if src and "broken_image" not in src and not src.endswith("loading.gif"):
                if not src.startswith("http"):
                    src = urljoin(SITE, src)
                urls.append(src)

        return urls
