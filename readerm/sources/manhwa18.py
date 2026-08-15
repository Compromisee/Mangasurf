"""Manhwa18 source (HTML scraping).

Adult content
    This site is explicitly adult: every card on it carries an ``18+``
    badge and the site describes itself as hosting adult comics. Results are
    therefore stamped with ``content_rating: "pornographic"`` and an
    ``Adult`` tag, so the existing ``safe_mode`` content filter removes them
    and the source can be excluded wholesale from Settings like any other.

Layout
    Search:   ``/search?q=<term>`` -> ``.manga-item`` cards
    Series:   ``/webtoon/<slug>``
    Chapters: ``/webtoon/<slug>/chapter-N`` -- the series page also lists
              unrelated "latest update" links, so chapter hrefs must be
              filtered to the current series or you collect other titles.
    Images:   ``.read-content img`` on the chapter page, served from
              ``img01.manhwa18.cc``. The CDN hotlinks without a Referer.
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://manhwa18.cc"


class Manhwa18Source(Source):
    id = "manhwa18"
    name = "Manhwa18"
    base_url = SITE
    domains = ("manhwa18.cc", "img01.manhwa18.cc")

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True
    #: Everything here is adult; surfaced so the UI can warn and filter.
    adult_only = True

    search_sorts = ("Best Match", "Latest Updates", "Popularity", "New")
    browse_sorts = ("Trending", "Latest Updates", "Popularity", "New")

    _SORTS = {
        "Trending": "views",
        "Popularity": "views",
        "Latest Updates": "latest",
        "New": "new",
        "Best Match": "latest",
    }

    GENRES = (
        "action", "adult", "adventure", "comedy", "drama", "fantasy",
        "harem", "historical", "horror", "josei", "mature", "mystery",
        "psychological", "romance", "school-life", "seinen", "shoujo",
        "slice-of-life", "smut", "supernatural", "thriller", "tragedy",
        "yaoi", "yuri",
    )

    def headers(self):
        h = super().headers()
        h["Referer"] = SITE + "/"
        return h

    # ---------------------------------------------------------- helpers

    def _card_result(self, item):
        link = item.select_one('a[href*="/webtoon/"], a[href*="/manga/"]')
        if not link or not link.get("href"):
            return None
        href = urljoin(SITE, link["href"])
        if re.search(r"/chapter-", href):
            return None

        heading = item.select_one("h3 a, .data h3 a, h3")
        title = (heading.get_text(strip=True) if heading
                 else link.get("title") or link.get_text(strip=True) or "")
        title = re.sub(r"^\s*18\+\s*", "", title).strip()
        if not title:
            return None

        img = item.select_one("img")
        cover = None
        if img is not None:
            cover = img.get("data-src") or img.get("src")
            if cover:
                cover = urljoin(SITE, cover)

        latest = item.select_one('.chapter-item a, .list-chapter a')
        return self._result(
            title, href, cover=cover,
            latest=latest.get_text(strip=True) if latest else None,
            # let safe_mode drop these without any special-casing
            content_rating="pornographic",
            tags=["Adult"],
            adult=True,
        )

    def _parse_listing(self, response, limit):
        soup = BeautifulSoup(response.content, "html.parser")
        results, seen = [], set()
        for item in soup.select(".manga-item, .bsx, .page-item-detail"):
            row = self._card_result(item)
            if not row or row["url"] in seen:
                continue
            seen.add(row["url"])
            results.append(row)
            if len(results) >= limit:
                break
        return results

    # ---------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, genre=None, sort=None, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(genre=genre, sort=sort, limit=limit)
        try:
            response = self.fetch(f"{SITE}/search?q={quote(query)}")
        except ScrapeError as e:
            logger.error("Manhwa18 search failed: %s", e)
            return []
        return self._parse_listing(response, limit)

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, **_):
        page = max(1, int(page or 1))
        order = self._SORTS.get(sort or "", "views")
        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            # Measured 2026-07: /genres/, /genre/ and /manga-genre/ are all
            # 404 here. The site uses the singular, prefixed form, which
            # returns 24 cards per genre and pages with ?page=N.
            url = f"{SITE}/webtoon-genre/{quote(slug)}?page={page}"
        else:
            url = f"{SITE}/webtoons/{page}?orderby={order}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("Manhwa18 browse failed: %s", e)
            return []
        results = self._parse_listing(response, limit)
        if not results and page == 1:
            # fall back to the home grid if the listing path changed
            try:
                results = self._parse_listing(self.fetch(SITE + "/"), limit)
            except ScrapeError:
                pass
        return results

    def genres(self) -> list:
        return [{"id": slug, "name": slug.replace("-", " ").title()}
                for slug in self.GENRES]

    # ------------------------------------------------------------ info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        heading = soup.select_one("h1")
        title = heading.get_text(strip=True) if heading else "Unknown"
        title = re.sub(r"^\s*18\+\s*", "", title).strip()

        cover = None
        img = soup.select_one(".book-info img, .thumb img, .summary_image img")
        if img is not None:
            cover = img.get("data-src") or img.get("src")
            if cover:
                cover = urljoin(SITE, cover)

        description = None
        block = soup.select_one(".summary-content, .dsct, .detail-content, "
                                ".description-summary")
        if block is not None:
            text = re.sub(r"\s+", " ", block.get_text(" ", strip=True))
            text = re.sub(r"^.*?Average\s+[\d.]+\s*/\s*5.*?votes?\s*", "",
                          text, flags=re.I).strip()
            description = text or None

        tags = ["Adult"]
        for link in soup.select('a[href*="/webtoon-genre/"], a[href*="/genres/"], a[href*="/genre/"]'):
            label = link.get_text(strip=True)
            if label and label not in tags:
                tags.append(label)

        authors = [a.get_text(strip=True)
                   for a in soup.select('a[href*="/author"]')
                   if a.get_text(strip=True)]

        status = None
        match = re.search(r"Status\s*:?\s*(Ongoing|Completed|Hiatus|Dropped)",
                          soup.get_text(" ", strip=True), re.I)
        if match:
            status = match.group(1).title()

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:20],
            "status": status,
            "authors": authors[:5],
            "artists": [],
            "content_rating": "pornographic",
            "adult": True,
            "source": self.id,
            "source_name": self.name,
        }

    # -------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        # Restrict to this series: the page also advertises other titles.
        series_path = self.series_path(manga_url)
        chapters, seen = [], set()

        for link in soup.select('a[href*="/chapter-"]'):
            href = urljoin(SITE, link.get("href") or "")
            path = re.sub(r"^https?://[^/]+", "", href)
            if not path.startswith(series_path + "/"):
                continue
            if href in seen:
                continue
            name = link.get_text(" ", strip=True)
            if not name or re.fullmatch(r"read\s+(first|last)", name, re.I):
                # the shortcut buttons carry no chapter label
                name = path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        from ..utils import chapter_number
        chapters.sort(key=lambda c: chapter_number(c["name"]))
        return chapters

    # ----------------------------------------------------------- pages

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        if not chapter_url:
            return []
        response = self.fetch(chapter_url)
        soup = BeautifulSoup(response.content, "html.parser")

        urls = []
        for img in soup.select(".read-content img, #chapter-content img, "
                               ".chapter-content img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            src = urljoin(SITE, src)
            if any(bad in src.lower() for bad in ("logo", "banner", "avatar")):
                continue
            urls.append(src)

        if not urls:
            raise ScrapeError(f"No page images found for {chapter_url}")
        return urls
