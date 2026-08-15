"""Natomanga source (the current Manganato / Mangakakalot successor).

Mostly HTML scraping, with one very useful exception: the chapter list is
served by a small JSON endpoint that the page itself calls on load.

Chapter list
    The manga page ships an empty ``#chapter-list-container`` carrying a
    ``data-api-url`` attribute; JavaScript then fetches::

        /api/manga/{slug}/chapters?offset=<n>&limit=<n>

    returning ``{"success": true, "data": {"chapters": [...],
    "pagination": {"total", "limit", "offset", "has_more"}}}``.
    Scraping the HTML alone therefore yields *zero* chapters, which is the
    trap here. ``limit`` is honoured (tested up to 200) while ``page`` is
    ignored -- paging must use ``offset``.

Images
    The reader emits real ``<img src>`` tags inside
    ``.container-chapter-reader`` pointing at ``*.2xstorage.com``. Hotlinking
    works without a Referer, but one is sent anyway to stay well-behaved.
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://www.natomanga.com"
PAGE_LIMIT = 200          # server honours this; keeps long series to few calls

#: Cover hosts seen in Natomanga markup.
#:
#: These are **shards, not mirrors**. An earlier version of this file treated
#: them as interchangeable and rewrote a cover URL onto every sibling host as
#: a fallback; re-measuring showed that is wrong and actively harmful.
#:
#: Measured 2026-07 over 10 consecutive search covers, each requested from
#: all three hosts:
#:
#:     host named in the page markup   10/10 HTTP 200
#:     img-r1.2xstorage.com             3/10
#:     img-r2.2xstorage.com             1/10
#:     imgs-2.2xstorage.com             6/10
#:
#: e.g. ``/thumb/naruto.webp`` is 200 on img-r1 and a hard 404 on img-r2.
#: A given thumbnail lives on exactly one shard, so the host printed in the
#: HTML is authoritative and every rewritten sibling is a probable 404.
#: The occasional real failure is a transient 429/503 on the correct host,
#: which a retry of the *same* URL fixes -- so that is what we do.
COVER_HOSTS = (
    "img-r1.2xstorage.com",
    "imgs-2.2xstorage.com",
    "img-r2.2xstorage.com",
)


class NatomangaSource(Source):
    id = "natomanga"
    name = "Natomanga"
    base_url = SITE
    domains = ("natomanga.com", "manganato.com", "mangakakalot.com",
               "nelomanga.com")

    supports_search = True
    supports_language = False
    supports_browse = True
    supports_genres = True
    search_sorts = ("Best Match", "Latest Updates", "Popularity", "Newest")
    browse_sorts = ("Trending", "Latest Updates", "Newest")

    _SORTS = {
        "Latest Updates": "latest",
        "Popularity": "topview",
        "Newest": "newest",
    }

    # /manga-list/<slug> feeds the site's own discovery pages
    _BROWSE_PATHS = {
        "Trending": "hot-manga",
        "Popularity": "hot-manga",
        "Latest Updates": "latest-manga",
        "Newest": "new-manga",
    }

    GENRES = (
        "action", "adventure", "comedy", "cooking", "doujinshi", "drama",
        "ecchi", "fantasy", "gender-bender", "harem", "historical", "horror",
        "isekai", "josei", "manhua", "manhwa", "martial-arts", "mature",
        "mecha", "medical", "mystery", "one-shot", "psychological", "romance",
        "school-life", "sci-fi", "seinen", "shoujo", "shoujo-ai", "shounen",
        "shounen-ai", "slice-of-life", "smut", "sports", "supernatural",
        "tragedy", "webtoons", "yaoi", "yuri",
    )

    def headers(self):
        h = super().headers()
        h["Referer"] = SITE + "/"
        return h

    # ------------------------------------------------------------ slug

    @staticmethod
    def cover_mirrors(url):
        """Alternative URLs for a cover, best-first.

        The hosts are content shards rather than mirrors (see COVER_HOSTS),
        so there is no sibling to fall back to: the URL in the markup is the
        only one that serves the file. Returning just it keeps the caller's
        retry-on-error path intact without sending it to guaranteed 404s.
        """
        return [url] if url else []

    @staticmethod
    def slug_of(manga_url: str) -> str:
        match = re.search(r"/manga/([^/?#]+)", manga_url or "")
        if not match:
            raise ScrapeError(f"Not a Natomanga manga URL: {manga_url}")
        return match.group(1)

    # ---------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, sort: str = None, **_):
        query = (query or "").strip()
        if not query:
            return []
        # the site slugifies the query: spaces -> underscores
        term = quote(re.sub(r"\s+", "_", query.lower()))
        url = f"{SITE}/search/story/{term}"
        if sort and sort in self._SORTS:
            url += f"?orby={self._SORTS[sort]}"

        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("Natomanga search failed: %s", e)
            return []

        soup = BeautifulSoup(response.content, "html.parser")
        results, seen = [], set()

        for item in soup.select(".story_item, .list-truyen-item-wrap, .search-story-item"):
            link = item.select_one('a[href*="/manga/"]')
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            # ignore direct chapter links inside the card
            if re.search(r"/chapter-", href):
                continue
            if href in seen:
                continue
            seen.add(href)

            title_el = item.select_one(".story_name a, h3 a, .item-title")
            title = title_el.get_text(strip=True) if title_el else None
            if not title:
                title = (link.get("title") or link.get_text(strip=True) or "").strip()

            img = item.select_one("img")
            cover = None
            if img is not None:
                cover = img.get("src") or img.get("data-src")
                if cover:
                    cover = urljoin(SITE, cover)

            author = None
            for span in item.select("span"):
                text = span.get_text(" ", strip=True)
                if text.lower().startswith("author"):
                    author = text.split(":", 1)[-1].strip()
                    break

            latest_el = item.select_one(".story_chapter a, .item-chapter a")
            results.append(self._result(
                title, href, cover=cover,
                cover_mirrors=self.cover_mirrors(cover),
                authors=[author] if author else [],
                latest=latest_el.get_text(strip=True) if latest_el else None,
            ))
            if len(results) >= limit:
                break
        return results

    # ---------------------------------------------------------- browse

    def genres(self) -> list:
        return [{"id": slug, "name": slug.replace("-", " ").title()}
                for slug in self.GENRES]

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, **_):
        page = max(1, int(page or 1))
        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            url = f"{SITE}/genre/{quote(slug)}"
            params = {"page": page}
            order = self._SORTS.get(sort)
            if order:
                params["type"] = order
        else:
            path = self._BROWSE_PATHS.get(sort, "hot-manga")
            url = f"{SITE}/manga-list/{path}"
            params = {"page": page}

        try:
            response = self.fetch(url, params=params)
        except ScrapeError as e:
            logger.error("Natomanga browse failed: %s", e)
            return []
        return self._parse_listing(response, limit)

    def _parse_listing(self, response, limit):
        """Parse a discovery grid. Shared by browse and genre listings."""
        soup = BeautifulSoup(response.content, "html.parser")
        results, seen = [], set()

        blocks = (soup.select(".list-comic-item-wrap")
                  or soup.select(".list-truyen-item-wrap")
                  or soup.select(".story_item"))
        for item in blocks:
            link = item.select_one('a[href*="/manga/"]')
            if not link or not link.get("href"):
                continue          # the grid carries a header row with no link
            href = urljoin(SITE, link["href"])
            if re.search(r"/chapter-", href) or href in seen:
                continue
            seen.add(href)

            title = (link.get("title") or link.get_text(strip=True) or "").strip()
            if not title:
                heading = item.select_one("h3 a, .story_name a")
                title = heading.get_text(strip=True) if heading else ""
            if not title:
                continue

            img = item.select_one("img")
            cover = None
            if img is not None:
                cover = img.get("src") or img.get("data-src")
                if cover:
                    cover = urljoin(SITE, cover)

            latest = item.select_one('a[href*="/chapter"]')
            results.append(self._result(
                title, href, cover=cover,
                cover_mirrors=self.cover_mirrors(cover),
                latest=latest.get_text(strip=True) if latest else None,
            ))
            if len(results) >= limit:
                break
        return results

    # ------------------------------------------------------------ info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        title_el = (soup.select_one(".manga-info-text h1")
                    or soup.select_one(".story-info-right h1")
                    or soup.select_one("h1"))
        title = title_el.get_text(strip=True) if title_el else "Unknown Manga"

        cover_el = (soup.select_one(".manga-info-pic img")
                    or soup.select_one(".info-image img")
                    or soup.select_one(".story-info-left img"))
        cover = None
        if cover_el is not None:
            cover = cover_el.get("src") or cover_el.get("data-src")
            if cover:
                cover = urljoin(SITE, cover)

        authors, status, updated, tags = [], None, None, []
        for li in soup.select(".manga-info-text li"):
            text = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
            low = text.lower()
            if low.startswith("author"):
                links = [a.get_text(strip=True) for a in li.select("a")]
                authors = links or [
                    p.strip() for p in text.split(":", 1)[-1].split(",") if p.strip()
                ]
            elif low.startswith("status"):
                status = text.split(":", 1)[-1].strip()
            elif low.startswith("last updated"):
                updated = text.split(":", 1)[-1].strip()
            elif low.startswith("genre"):
                tags = [a.get_text(strip=True) for a in li.select("a")]

        if not tags:
            tags = [a.get_text(strip=True) for a in soup.select(".genres a, .genre a")]

        desc_el = (soup.select_one("#contentBox")
                   or soup.select_one(".panel-story-info-description"))
        description = None
        if desc_el is not None:
            description = re.sub(r"\s+", " ", desc_el.get_text(" ", strip=True))
            description = re.sub(r"^.*?summary\s*:?\s*", "", description,
                                 flags=re.I).strip() or None

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "cover_mirrors": self.cover_mirrors(cover),
            "description": description,
            "tags": tags,
            "status": status,
            "authors": authors,
            "artists": [],
            "updated": updated,
            "source": self.id,
            "source_name": self.name,
        }

    # -------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        """Chapters oldest-first, via the JSON endpoint the page uses."""
        manga_url = self.normalize_url(manga_url)
        slug = self.slug_of(manga_url)

        chapters = self._chapters_from_api(slug, manga_url)
        if chapters:
            return chapters
        # Fall back to HTML in case the endpoint changes again.
        return self._chapters_from_html(manga_url)

    def _chapters_from_api(self, slug, manga_url):
        collected, offset = [], 0
        while True:
            try:
                payload = self.fetch_json(
                    f"{SITE}/api/manga/{slug}/chapters",
                    params={"offset": offset, "limit": PAGE_LIMIT},
                    headers={"Referer": manga_url,
                             "X-Requested-With": "XMLHttpRequest"},
                )
            except ScrapeError as e:
                logger.warning("Natomanga chapter API failed (%s); using HTML", e)
                return []

            data = (payload or {}).get("data") or {}
            batch = data.get("chapters") or []
            if not batch:
                break

            for entry in batch:
                chapter_slug = entry.get("chapter_slug")
                if not chapter_slug:
                    continue
                collected.append({
                    "url": f"{SITE}/manga/{slug}/{chapter_slug}",
                    "name": entry.get("chapter_name") or chapter_slug,
                    "number": entry.get("chapter_num"),
                    "date": (entry.get("updated_at") or "")[:10] or None,
                    "views": entry.get("view"),
                    "source": self.id,
                })

            pagination = data.get("pagination") or {}
            offset += len(batch)
            if not pagination.get("has_more") or offset >= (
                    pagination.get("total") or 0):
                break
            if offset > 20000:              # sanity stop
                break

        def sort_key(chapter):
            try:
                return (float(chapter.get("number")), 0)
            except (TypeError, ValueError):
                from ..utils import chapter_number
                return (chapter_number(chapter["name"]), 1)

        collected.sort(key=sort_key)
        return collected

    def _chapters_from_html(self, manga_url):
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")
        rows = (soup.select(".chapter-list .row")
                or soup.select("ul.row-content-chapter li"))

        chapters = []
        for row in rows:
            link = row.select_one("a[href]")
            if not link:
                continue
            href = urljoin(SITE, link["href"])
            if "/chapter" not in href:
                continue
            chapters.append({
                "url": href,
                "name": link.get_text(strip=True) or link.get("title") or "Chapter",
                "source": self.id,
            })
        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- pages

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        if not chapter_url:
            return []
        response = self.fetch(chapter_url)
        soup = BeautifulSoup(response.content, "html.parser")

        images = (soup.select(".container-chapter-reader img")
                  or soup.select(".chapter-reader img")
                  or soup.select("#vungdoc img"))

        urls = []
        for img in images:
            src = img.get("src") or img.get("data-src")
            if not src or src.startswith("data:"):
                continue
            src = urljoin(SITE, src)
            if any(bad in src.lower() for bad in ("logo", "banner", "/thumb/")):
                continue
            urls.append(src)

        if not urls:
            raise ScrapeError(f"No page images found for {chapter_url}")
        return urls

    def download_file(self, url, filepath, referer=None, max_retries=5, headers=None):
        # 2xstorage serves fine without one, but be polite and send it anyway
        return super().download_file(url, filepath, referer or SITE + "/",
                                     max_retries, headers)
