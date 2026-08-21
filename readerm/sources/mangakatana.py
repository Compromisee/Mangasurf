"""Mangakatana source scraper for Mangasurf.

Adapted from mangakatana-downloader with full integration for the Mangasurf Source API.
Features:
- JS array extraction (var thzq and obfuscated dynamic array variables)
- Genre mapping and filtering
- Search by book name and author
- Fast natural page sorting
- Clean metadata and status parsing
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://mangakatana.com"

_JS_ARRAY = re.compile(r"=\s*\[\s*((?:'https?://[^']+'\s*,?\s*)+)\]")
_JS_URL = re.compile(r"'(https?://[^']+)'")

GENRE_MAP = {
    1: "4-koma", 2: "Action", 3: "Adult", 4: "Adventure", 5: "Artbook",
    6: "Award Winning", 7: "Comedy", 8: "Cooking", 9: "Doujinshi", 10: "Drama",
    11: "Ecchi", 12: "Erotica", 13: "Fantasy", 14: "Gender Bender", 15: "Gore",
    16: "Harem", 17: "Historical", 18: "Horror", 19: "Isekai", 20: "Josei",
    21: "Manhua", 22: "Manhwa", 23: "Martial Arts", 24: "Mature", 25: "Mecha",
    26: "Medical", 27: "Musical", 28: "Mystery", 29: "One Shot", 30: "Psychological",
    31: "Romance", 32: "School Life", 33: "Sci-fi", 34: "Seinen", 35: "Shoujo",
    36: "Shoujo Ai", 37: "Shounen", 38: "Shounen Ai", 39: "Slice of Life", 40: "Smut",
    41: "Sports", 42: "Supernatural", 43: "Tragedy", 44: "Webtoon", 45: "Yaoi", 46: "Yuri",
}


class MangakatanaSource(Source):
    id = "mangakatana"
    name = "Mangakatana"
    base_url = SITE
    domains = ("mangakatana.com", "www.mangakatana.com")

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Latest Updates", "New", "Popularity", "Alphabet")
    browse_sorts = ("Trending", "Latest Updates", "New", "Alphabet")

    _SORTS = {
        "Trending": "numc",
        "Popularity": "numc",
        "Latest Updates": "latest",
        "New": "new",
        "Alphabet": "az",
    }

    GENRES = (
        "4-koma", "action", "adult", "adventure", "artbook", "award-winning",
        "comedy", "cooking", "doujinshi", "drama", "ecchi", "erotica",
        "fantasy", "gender-bender", "gore", "harem", "historical", "horror",
        "isekai", "josei", "manhua", "manhwa", "martial-arts", "mature",
        "mecha", "medical", "musical", "mystery", "one-shot", "psychological",
        "romance", "school-life", "sci-fi", "seinen", "shoujo", "shoujo-ai",
        "shounen", "shounen-ai", "slice-of-life", "smut", "sports",
        "supernatural", "tragedy", "webtoon", "yaoi", "yuri",
    )

    def headers(self) -> dict:
        h = super().headers()
        h["Referer"] = SITE + "/"
        return h

    def genres(self) -> list:
        return [{"id": slug, "name": slug.replace("-", " ").title()} for slug in self.GENRES]

    def browse(
        self,
        sort: str = "Trending",
        genre: str = None,
        page: int = 1,
        limit: int = 32,
        status=None,
        **_,
    ) -> list:
        page = max(1, int(page or 1))
        order = self._SORTS.get(sort, "numc")

        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            url = f"{SITE}/genre/{quote(slug)}"
            if page > 1:
                url += f"/page/{page}"
            url += f"?filter=1&order={order}"
        elif page > 1:
            url = f"{SITE}/page/{page}?filter=1&order={order}"
        else:
            url = f"{SITE}/?filter=1&order={order}"

        if status and status != "Any":
            url += f"&status={quote(str(status).lower())}"

        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("Mangakatana browse failed: %s", e)
            return []
        return self._parse_listing(response, limit)

    def search(
        self,
        query: str,
        limit: int = 32,
        sort: str = None,
        status: str = None,
        search_by: str = "book_name",
        page: int = 1,
        **_,
    ) -> list:
        query = (query or "").strip()
        if not query:
            return []

        page_val = max(1, int(page or _.get("page", 1) or 1))
        by = "author" if search_by in ("author", "m_author") else "book_name"
        if page_val > 1:
            url = f"{SITE}/page/{page_val}?search={quote(query)}&search_by={by}"
        else:
            url = f"{SITE}/?search={quote(query)}&search_by={by}"
        if sort and sort in self._SORTS:
            url += f"&order={self._SORTS[sort]}"
        if status and status != "Any":
            url += f"&status={quote(status.lower())}"

        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.warning("Mangakatana search failed: %s", e)
            return []

        final_url = str(getattr(response, "url", "") or "")
        if "/manga/" in final_url and "search" not in final_url:
            try:
                info = self.get_manga_info(final_url)
                return [
                    self._result(
                        info["title"],
                        info["url"],
                        cover=info.get("cover"),
                        status=info.get("status"),
                        authors=info.get("authors", []),
                    )
                ]
            except Exception:
                pass

        return self._parse_listing(response, limit)

    def _parse_listing(self, response, limit=32):
        soup = BeautifulSoup(response.content, "html.parser")
        results, seen = [], set()

        items = soup.select("#book_list .item") or soup.select(".book_list .item") or soup.select("div.item")

        for item in items:
            link = item.select_one('a[href*="/manga/"]')
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            if re.search(r"/manga/[^/]+/c[\d.]+", href) or href in seen:
                continue
            seen.add(href)

            title_el = item.select_one("h3.title a, .title a, h3 a")
            title = title_el.get_text(strip=True) if title_el else None
            if not title:
                title = (link.get("title") or link.get_text(strip=True) or "").strip()

            cover = None
            img = item.select_one("img")
            if img is not None:
                cover = img.get("src") or img.get("data-src")
                source_tag = item.select_one("source[srcset]")
                if source_tag and source_tag.get("srcset"):
                    cover = source_tag["srcset"].split()[0]
                if cover:
                    cover = urljoin(SITE, cover)

            status_el = item.select_one(".status")
            latest_el = item.select_one(".chapter a")

            results.append(
                self._result(
                    title or "Unknown Manga",
                    href,
                    cover=cover,
                    status=status_el.get_text(strip=True) if status_el else None,
                    latest=latest_el.get_text(strip=True) if latest_el else None,
                )
            )
            if len(results) >= limit:
                break

        return results

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        title_el = soup.select_one("h1.heading") or soup.select_one("h1")
        title = title_el.get_text(strip=True) if title_el else "Unknown Manga"

        cover = None
        cover_el = soup.select_one("div.cover img") or soup.select_one(".media img")
        if cover_el is not None:
            cover = cover_el.get("src") or cover_el.get("data-src")
            if cover:
                cover = urljoin(SITE, cover)

        description = None
        desc_el = soup.select_one("div.summary p") or soup.select_one("div.summary")
        if desc_el is not None:
            description = re.sub(r"\s+", " ", desc_el.get_text(" ", strip=True)).strip()
            description = re.sub(r"^Description\s*", "", description).strip() or None

        meta = {}
        for li in soup.select("ul.meta li, .meta.d-table li"):
            label_el = li.select_one(".label")
            value_el = li.select_one(".value")
            if not label_el or value_el is None:
                continue
            label = label_el.get_text(strip=True).rstrip(":").lower()
            links = [a.get_text(strip=True) for a in value_el.select("a")]
            meta[label] = {
                "text": re.sub(r"\s+", " ", value_el.get_text(" ", strip=True)).strip(),
                "links": links,
            }

        def pick(*keys):
            for key in keys:
                for label, value in meta.items():
                    if key in label:
                        return value
            return None

        authors_meta = pick("author", "artist")
        genres_meta = pick("genre")
        status_meta = pick("status")
        alt_meta = pick("alt name")
        updated_meta = pick("update")

        authors = []
        if authors_meta:
            authors = authors_meta["links"] or [
                a.strip() for a in re.split(r"[,;/]", authors_meta["text"]) if a.strip()
            ]

        tags = []
        if genres_meta:
            tags = genres_meta["links"] or [
                g.strip() for g in re.split(r"[,;]", genres_meta["text"]) if g.strip()
            ]

        alt_titles = []
        if alt_meta:
            alt_titles = [
                a.strip() for a in re.split(r"[;|]", alt_meta["text"]) if a.strip()
            ]

        return {
            "url": manga_url,
            "title": title,
            "alt_titles": alt_titles,
            "cover": cover,
            "description": description,
            "tags": tags,
            "status": status_meta["text"] if status_meta else None,
            "authors": authors,
            "artists": [],
            "updated": updated_meta["text"] if updated_meta else None,
            "source": self.id,
            "source_name": self.name,
        }

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        rows = soup.select("div.chapters table tr")
        if not rows:
            rows = soup.select("div.chapters .chapter")

        chapters = []
        for row in rows:
            link = row.select_one('a[href*="/manga/"]')
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            name = link.get("title") or link.get_text(strip=True)
            if not name:
                continue
            date_el = row.select_one(".update_time")
            chapters.append({
                "url": href,
                "name": re.sub(r"\s+", " ", name).strip(),
                "date": date_el.get_text(strip=True) if date_el else None,
                "source": self.id,
            })

        chapters.reverse()
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        if not chapter_url:
            return []
        response = self.fetch(chapter_url)
        html = response.text

        thzq_match = re.search(r"var\s+thzq\s*=\s*\[(.*?)\];", html, re.DOTALL)
        if thzq_match:
            urls = re.findall(r"'([^']+\.jpg)'", thzq_match.group(1))
            if urls:
                return self._sort_pages(urls)

        candidates = []
        for match in _JS_ARRAY.finditer(html):
            urls = _JS_URL.findall(match.group(1))
            urls = [u for u in urls if self._looks_like_page(u)]
            if urls:
                candidates.append(urls)

        if candidates:
            best = max(candidates, key=len)
            return self._sort_pages(best)

        soup = BeautifulSoup(response.content, "html.parser")
        urls = []
        for img in soup.select("#imgs img, .wrap_content img, img"):
            src = img.get("data-src") or img.get("src")
            if src and src != "#" and self._looks_like_page(src):
                urls.append(urljoin(SITE, src))
        if urls:
            return urls

        raise ScrapeError(f"No page images found for {chapter_url}")

    @staticmethod
    def _looks_like_page(url: str) -> bool:
        if not url.startswith("http"):
            return False
        lowered = url.lower()
        if any(bad in lowered for bad in ("/imgs/cover/", "logo", "banner", "avatar")):
            return False
        return True

    @staticmethod
    def _sort_pages(urls):
        def key(item):
            index, url = item
            match = re.search(r"/(\d+)\.(?:jpg|jpeg|png|webp|gif)(?:\?|$)", url, re.I)
            return (int(match.group(1)) if match else index, index)

        indexed = list(enumerate(urls))
        ordered = sorted(indexed, key=key)
        return [url for _i, url in ordered]
