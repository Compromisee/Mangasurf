"""Webtoons source (HTML scraping of webtoons.com).

Notes from probing the live site:

Search
    ``/en/search?keyword=<term>`` returns cards under ``._card_item``.
    Series links look like ``/en/<genre>/<slug>/list?title_no=<id>``, and the
    numeric ``title_no`` is the real identifier -- the genre segment in the
    path varies and cannot be relied on.

Episodes
    The list page shows only the most recent page of episodes. Older ones are
    paged via ``&page=N``, so the list is walked until a page repeats or runs
    out. Episode links carry ``episode_no``.

Images
    Viewer pages hold the pages in ``#_imageList img`` with the real URL on
    ``data-url`` (``src`` is a placeholder). The CDN is hotlink-protected:
    measured **403 without a Referer and 200 with** ``https://www.webtoons.com/``,
    so every chapter carries one.
"""

import logging
import re
from urllib.parse import parse_qs, quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://www.webtoons.com"


class WebtoonsSource(Source):
    id = "webtoons"
    name = "Webtoons"
    base_url = SITE
    domains = ("webtoons.com",)

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True
    #: pstatic.net answers 403 to any request whose Referer is not
    #: webtoons.com -- measured 403 with no Referer / file:// / example.com,
    #: 200 with https://www.webtoons.com/. The GUI cannot send that header
    #: from an <img> tag, so covers are proxied through the Python side.
    cover_needs_referer = True
    search_sorts = ("Best Match", "Popularity", "Latest Updates")
    browse_sorts = ("Trending", "Popularity", "Latest Updates")

    GENRES = (
        "action", "romance", "fantasy", "comedy", "drama", "thriller",
        "horror", "slice-of-life", "sci-fi", "supernatural", "sports",
        "historical", "heartwarming", "informative", "mystery",
    )

    def headers(self):
        h = super().headers()
        # the whole site 403s image requests without this
        h["Referer"] = SITE + "/"
        return h

    # ------------------------------------------------------------ helpers

    @staticmethod
    def title_no(url):
        """The numeric series id, which is the only stable identifier."""
        query = parse_qs(urlparse(url or "").query)
        value = (query.get("title_no") or [None])[0]
        return value

    def _card_results(self, soup, limit):
        results, seen = [], set()
        for link in soup.select('a[href*="title_no="]'):
            href = urljoin(SITE, link.get("href") or "")
            if "/viewer" in href:
                continue
            number = self.title_no(href)
            if not number or number in seen:
                continue

            title_el = link.select_one(".subj, .info_text .subj, strong")
            title = (title_el.get_text(" ", strip=True) if title_el
                     else link.get_text(" ", strip=True))
            title = re.sub(r"\s+", " ", title or "").strip()
            if not title:
                continue

            img = link.select_one("img")
            cover = None
            if img is not None:
                cover = img.get("data-url") or img.get("src")

            author_el = link.select_one(".author")
            seen.add(number)
            results.append(self._result(
                title, href, cover=cover,
                title_no=number,
                authors=[author_el.get_text(strip=True)] if author_el else [],
            ))
            if len(results) >= limit:
                break
        return results

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, genre=None, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(genre=genre, limit=limit)
        try:
            response = self.fetch(f"{SITE}/en/search?keyword={quote(query)}")
        except ScrapeError as e:
            logger.error("Webtoons search failed: %s", e)
            return []
        soup = BeautifulSoup(response.content, "html.parser")
        return self._card_results(soup, limit)

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, **_):
        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            url = f"{SITE}/en/genres/{quote(slug)}"
        else:
            url = f"{SITE}/en/originals"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("Webtoons browse failed: %s", e)
            return []
        soup = BeautifulSoup(response.content, "html.parser")
        return self._card_results(soup, limit)

    def genres(self) -> list:
        return [{"id": slug, "name": slug.replace("-", " ").title()}
                for slug in self.GENRES]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        title = None
        heading = soup.select_one("h1.subj, .info .subj, h3.subj")
        if heading is not None:
            title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
        if not title:
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                title = og["content"].split("|")[0].strip()

        cover = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            cover = og_image["content"]

        description = None
        summary = soup.select_one(".summary, p.summary, .detail_body .summary")
        if summary is not None:
            description = re.sub(r"\s+", " ", summary.get_text(" ", strip=True))
        if not description:
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                description = og_desc["content"].strip()

        authors = [a.get_text(strip=True)
                   for a in soup.select(".author, .author_area")
                   if a.get_text(strip=True)][:3]
        tags = [g.get_text(strip=True) for g in soup.select(".genre, .g_theme")
                if g.get_text(strip=True)][:10]

        return {
            "url": manga_url,
            "title": title or "Unknown",
            "cover": cover,
            "description": description,
            "tags": tags,
            "status": None,
            "authors": authors,
            "artists": [],
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        number = self.title_no(manga_url)
        if not number:
            raise ScrapeError(f"Not a Webtoons series URL: {manga_url}")

        base = manga_url.split("?")[0]
        chapters, seen, page = [], set(), 1

        while page <= 60:
            url = f"{base}?title_no={number}&page={page}"
            try:
                response = self.fetch(url)
            except ScrapeError:
                break
            soup = BeautifulSoup(response.content, "html.parser")
            rows = soup.select("#_listUl li a")
            if not rows:
                break

            added = 0
            for link in rows:
                href = urljoin(SITE, link.get("href") or "")
                if "episode_no=" not in href or href in seen:
                    continue
                seen.add(href)
                label = link.select_one(".subj span, .subj")
                name = (label.get_text(" ", strip=True) if label
                        else link.get_text(" ", strip=True))
                chapters.append({
                    "url": href,
                    "name": re.sub(r"\s+", " ", name or "Episode").strip(),
                    "referer": manga_url,
                    "source": self.id,
                })
                added += 1
            if not added:
                break
            page += 1

        from ..utils import chapter_number
        chapters.sort(key=lambda c: chapter_number(c["name"]))
        return chapters

    # ------------------------------------------------------------ pages

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        if not chapter_url:
            return []
        response = self.fetch(chapter_url)
        soup = BeautifulSoup(response.content, "html.parser")

        urls = []
        for img in soup.select("#_imageList img, ._images"):
            # the visible src is a placeholder; data-url holds the real page
            src = (img.get("data-url") or img.get("src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            if "bg_transparency" in src or "Thumb" in src:
                continue
            urls.append(src)

        if not urls:
            raise ScrapeError(f"No page images found for {chapter_url}")
        return urls

    def download_file(self, url, filepath, referer=None, max_retries=5, headers=None):
        # pstatic.net answers 403 without a webtoons.com Referer
        return super().download_file(url, filepath, referer or SITE + "/",
                                     max_retries, headers)
