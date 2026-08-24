"""Kagane source scraper for Mangasurf.

Adapted from kagane-downloader with full integration for the Mangasurf Source API.
Uses Kagane REST API and HTML scraping with multi-mirror CDN fallbacks.
"""

import logging
import re
from urllib.parse import quote, urljoin

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://kagane.to"
API_BASE = "https://kagane.to/api/v2"
API_MIRRORS = (
    "https://kagane.to/api/v2",
    "https://kstatic.to/api/v2",
    "https://api.kagane.to/api/v2",
    "https://kagane.to/api",
)
IMAGE_BASE = "https://kstatic.to/image"

SERIES_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?kagane\.to/series/([a-zA-Z0-9-]+)",
    re.IGNORECASE,
)
UUID_PATTERN = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$",
    re.IGNORECASE,
)


class KaganeSource(Source):
    id = "kagane"
    name = "Kagane"
    base_url = SITE
    domains = ("kagane.to", "www.kagane.to", "kstatic.to")
    needs_flaresolverr = True

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Popularity", "Latest", "Alphabetical", "Rating")
    browse_sorts = ("Trending", "Popularity", "Latest Updates", "Rating")

    GENRES = (
        "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy",
        "Gender Bender", "Harem", "Historical", "Horror", "Isekai",
        "Josei", "Martial Arts", "Mature", "Mecha", "Mystery",
        "Psychological", "Romance", "School Life", "Sci-Fi", "Seinen",
        "Shoujo", "Shounen", "Slice of Life", "Sports", "Supernatural",
        "Tragedy", "Webtoon",
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
    def extract_series_id(cls, url_or_id: str) -> str:
        if not url_or_id:
            return ""
        url_or_id = url_or_id.strip()
        match = SERIES_URL_PATTERN.search(url_or_id)
        if match:
            return match.group(1)
        if UUID_PATTERN.match(url_or_id):
            return url_or_id
        parts = url_or_id.rstrip("/").split("/")
        for part in parts:
            if UUID_PATTERN.match(part):
                return part
        return parts[-1] if parts else url_or_id

    def genres(self) -> list:
        return [{"id": name.lower(), "name": name} for name in self.GENRES]

    def _resolve_cover(self, item: dict) -> str:
        if not isinstance(item, dict):
            return ""
        cover_id = item.get("cover_image_id") or item.get("image_id")
        if cover_id:
            return f"{IMAGE_BASE}/{cover_id}"
        covers = item.get("series_covers")
        if covers and isinstance(covers, list) and isinstance(covers[0], dict):
            cid = covers[0].get("image_id") or covers[0].get("cover_image_id")
            if cid:
                return f"{IMAGE_BASE}/{cid}"
        cover_url = item.get("cover") or item.get("cover_url") or item.get("poster")
        if cover_url:
            return str(cover_url)
        return ""

    def search(self, query: str, limit: int = 32, page: int = 1, **_) -> list:
        query_str = (query or "").strip()
        if not query_str:
            return []

        if UUID_PATTERN.match(query_str):
            try:
                info = self.get_manga_info(query_str)
                return [self._result(info["title"], info["url"], cover=info.get("cover"))]
            except Exception:
                pass

        page_val = max(1, int(page or _.get("page", 1) or 1))
        data = None
        for base in API_MIRRORS:
            for endpoint, key_name in [("series", "query"), ("series", "search"), ("series", "q"), ("search", "q")]:
                try:
                    url = f"{base}/{endpoint}"
                    data = self.fetch_json(url, params={key_name: query_str, "limit": max(limit, 40), "page": page_val}, timeout=4)
                    if data and (isinstance(data, list) or data.get("data") or data.get("results") or data.get("series")):
                        break
                except Exception:
                    continue
            if data:
                break

        results = []
        if data:
            items = data.get("data") or data.get("results") or data.get("series") or (data if isinstance(data, list) else [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                series_id = item.get("series_id") or item.get("id") or item.get("slug")
                if not series_id:
                    continue
                title = item.get("title") or "Unknown"
                cover_url = self._resolve_cover(item)

                results.append(
                    self._result(
                        title,
                        f"{SITE}/series/{series_id}",
                        cover=cover_url,
                        status=item.get("publication_status") or item.get("status"),
                        type=item.get("format") or item.get("type"),
                    )
                )

        # Fallback to HTML search scraping if API produced no results
        if not results:
            try:
                from bs4 import BeautifulSoup
                search_url = f"{SITE}/series"
                resp = self.fetch(search_url, params={"search": query_str, "q": query_str, "page": page_val}, timeout=6)
                soup = BeautifulSoup(resp.content, "html.parser")
                cards = soup.select("div[class*='series-card'], div[class*='comic-item'], div[class*='card'], a[href*='/series/']")
                for card in cards:
                    link_el = card if card.name == "a" else card.select_one("a[href*='/series/']")
                    if not link_el or not link_el.get("href"):
                        continue
                    href = link_el["href"]
                    series_url = urljoin(SITE, href)
                    title_el = card.select_one("h2, h3, h4, .title, .name") or link_el
                    title = title_el.get_text(strip=True) if title_el else "Unknown"
                    img = card.select_one("img")
                    cover = img.get("src") or img.get("data-src") if img else None
                    if cover and not cover.startswith("http"):
                        cover = urljoin(SITE, cover)
                    results.append(self._result(title, series_url, cover=cover))
            except Exception as e:
                logger.debug("Kagane HTML search fallback failed: %s", e)

        if query_str and results:
            results = self.filter_and_rank(results, query_str)

        return results[:limit]

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 32, **_) -> list:
        page = max(1, int(page or 1))
        data = None
        for base in API_MIRRORS:
            try:
                url = f"{base}/series"
                params = {"page": page, "limit": min(limit, 50)}
                if genre:
                    params["genre"] = genre
                data = self.fetch_json(url, params=params, timeout=4)
                if data:
                    break
            except Exception:
                continue

        results = []
        if data:
            items = data.get("data") or data.get("results") or (data if isinstance(data, list) else [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                series_id = item.get("series_id") or item.get("id") or item.get("slug")
                if not series_id:
                    continue
                title = item.get("title") or "Unknown"
                cover_url = self._resolve_cover(item)

                results.append(
                    self._result(
                        title,
                        f"{SITE}/series/{series_id}",
                        cover=cover_url,
                        status=item.get("publication_status") or item.get("status"),
                        type=item.get("format") or item.get("type"),
                    )
                )
                if len(results) >= limit:
                    break

        if not results:
            try:
                from bs4 import BeautifulSoup
                browse_url = f"{SITE}/series"
                resp = self.fetch(browse_url, params={"page": page}, timeout=6)
                soup = BeautifulSoup(resp.content, "html.parser")
                for card in soup.select("div[class*='series-card'], div[class*='comic-item'], div[class*='card'], a[href*='/series/']"):
                    link_el = card if card.name == "a" else card.select_one("a[href*='/series/']")
                    if not link_el or not link_el.get("href"):
                        continue
                    href = link_el["href"]
                    series_url = urljoin(SITE, href)
                    title_el = card.select_one("h2, h3, h4, .title, .name") or link_el
                    title = title_el.get_text(strip=True) if title_el else "Unknown"
                    img = card.select_one("img")
                    cover = img.get("src") or img.get("data-src") if img else None
                    if cover and not cover.startswith("http"):
                        cover = urljoin(SITE, cover)
                    results.append(self._result(title, series_url, cover=cover))
                    if len(results) >= limit:
                        break
            except Exception as e:
                logger.debug("Kagane HTML browse fallback failed: %s", e)

        return results

    def get_manga_info(self, manga_url: str) -> dict:
        series_id = self.extract_series_id(manga_url)
        if not series_id:
            raise ScrapeError(f"Could not extract Kagane series ID from {manga_url}")

        data = None
        for base in API_MIRRORS:
            try:
                api_url = f"{base}/series/{series_id}"
                data = self.fetch_json(api_url, timeout=4)
                if data and isinstance(data, dict):
                    break
            except Exception:
                continue

        if data and isinstance(data, dict):
            title = data.get("title") or series_id
            description = data.get("description") or data.get("summary") or ""
            cover_url = self._resolve_cover(data)

            alt_titles = [
                t.get("title") for t in data.get("series_alternate_titles", [])
                if isinstance(t, dict) and t.get("title")
            ]

            tags = []
            for g in data.get("genres", []):
                if isinstance(g, dict) and g.get("genre_name"):
                    tags.append(g["genre_name"])
                elif isinstance(g, str):
                    tags.append(g)
            for t in data.get("tags", []):
                if isinstance(t, dict) and t.get("tag_name"):
                    tags.append(t["tag_name"])
                elif isinstance(t, str):
                    tags.append(t)

            authors, artists = [], []
            for s in data.get("series_staff", []):
                if not isinstance(s, dict):
                    continue
                name = s.get("name")
                role = (s.get("role") or "").lower()
                if not name:
                    continue
                if "art" in role:
                    artists.append(name)
                else:
                    authors.append(name)

            return {
                "url": f"{SITE}/series/{series_id}",
                "title": title,
                "alt_titles": alt_titles,
                "cover": cover_url,
                "description": description,
                "tags": tags,
                "status": data.get("publication_status") or data.get("status") or "Ongoing",
                "authors": authors,
                "artists": artists,
                "source": self.id,
                "source_name": self.name,
                "format": data.get("format"),
                "rating": data.get("average_rating"),
            }

        # Fallback to HTML parsing
        from bs4 import BeautifulSoup
        resp = self.fetch(manga_url)
        soup = BeautifulSoup(resp.content, "html.parser")
        title = soup.select_one("h1").get_text(strip=True) if soup.select_one("h1") else series_id
        img = soup.select_one("img[src*='cover'], img[alt*='cover'], .series-cover img, img")
        cover = img.get("src") or img.get("data-src") if img else None
        if cover and not cover.startswith("http"):
            cover = urljoin(SITE, cover)
        desc = soup.select_one("p.description, div.description, .synopsis, p")
        description = desc.get_text(strip=True) if desc else ""
        tags = [a.get_text(strip=True) for a in soup.select("a[href*='/genre/'], .genre-tag, .chip")]

        return {
            "url": f"{SITE}/series/{series_id}",
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags,
            "status": "Ongoing",
            "authors": [],
            "artists": [],
            "source": self.id,
            "source_name": self.name,
        }

    def get_chapters(self, manga_url: str) -> list:
        series_id = self.extract_series_id(manga_url)
        if not series_id:
            return []

        data = None
        for base in API_MIRRORS:
            try:
                api_url = f"{base}/series/{series_id}"
                data = self.fetch_json(api_url, timeout=4)
                if data and isinstance(data, dict):
                    break
            except Exception:
                continue

        books = []
        if data and isinstance(data, dict):
            books = data.get("series_books") or data.get("books") or data.get("chapters") or []
        elif isinstance(data, list):
            books = data

        chapters = []
        for book in books:
            if not isinstance(book, dict):
                continue
            book_id = book.get("book_id") or book.get("id")
            if not book_id:
                continue

            ch_no = str(book.get("chapter_no", "") or book.get("number", "")).strip()
            ch_title = str(book.get("title", "")).strip()

            if ch_no and ch_title and ch_no != ch_title:
                name = f"Chapter {ch_no} - {ch_title}"
            elif ch_no:
                name = f"Chapter {ch_no}"
            elif ch_title:
                name = ch_title
            else:
                name = f"Chapter {book.get('sort_no', 0)}"

            chapters.append({
                "url": f"{SITE}/series/{series_id}/reader/{book_id}",
                "name": name,
                "date": book.get("created_at") or book.get("updated_at"),
                "source": self.id,
                "book_id": book_id,
                "sort_no": float(book.get("sort_no", 0) or ch_no if ch_no.replace('.', '', 1).isdigit() else 0),
            })

        if not chapters:
            try:
                from bs4 import BeautifulSoup
                resp = self.fetch(manga_url)
                soup = BeautifulSoup(resp.content, "html.parser")
                links = soup.select("a[href*='/reader/'], a[href*='/chapter/'], .chapter-item a")
                for link in links:
                    href = link.get("href")
                    if not href:
                        continue
                    ch_url = urljoin(SITE, href)
                    name = link.get_text(strip=True) or "Chapter"
                    chapters.append({
                        "url": ch_url,
                        "name": name,
                        "source": self.id,
                        "sort_no": float(re.search(r"(\d+(?:\.\d+)?)", name).group(1)) if re.search(r"(\d+(?:\.\d+)?)", name) else 0.0,
                    })
            except Exception as e:
                logger.debug("Kagane HTML chapters fallback failed: %s", e)

        chapters.sort(key=lambda c: c.get("sort_no", 0))
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        parts = chapter_url.strip("/").split("/")
        book_id = parts[-1]

        for base in API_MIRRORS:
            try:
                api_url = f"{base}/books/{book_id}"
                data = self.fetch_json(api_url, timeout=4)
                if data and isinstance(data, dict):
                    if "pages" in data and isinstance(data["pages"], list):
                        return [
                            f"{IMAGE_BASE}/{p['image_id'] if isinstance(p, dict) and 'image_id' in p else p}"
                            if not str(p).startswith("http") else str(p)
                            for p in data["pages"]
                        ]
                    page_count = int(data.get("page_count", 0))
                    if page_count > 0:
                        return [f"https://kstatic.to/api/v2/books/{book_id}/page/{i}.webp" for i in range(1, page_count + 1)]
            except Exception:
                continue

        try:
            resp = self.fetch(chapter_url)
            html = resp.text
            urls = re.findall(r'https?://[^\s"\']+(?:kstatic\.to|kagane\.to)[^\s"\']+\.(?:webp|jpg|jpeg|png)', html)
            if urls:
                return sorted(list(set(urls)))
        except Exception as e:
            logger.warning("Kagane HTML page fallback failed: %s", e)

        return [f"https://kstatic.to/api/v2/books/{book_id}/page/{i}.webp" for i in range(1, 30)]

