"""Mangadass source (HTML scraping of mangadass.com).

Notes from probing the live site (2026-07):

Search
    ``/?s=<term>`` looks like the usual WordPress search this theme ships
    with, but it is a **decoy**: it returns the homepage grid unchanged. The
    same 24 titles came back for ``?s=naruto``, ``?s=daddy`` and for the bare
    homepage, so anything built on it would silently return "latest updates"
    for every query.

    ``/search?q=<term>`` is the real endpoint and genuinely filters --
    ``?q=daddy`` returned "Single Daddy Raw", "Do Me, Daddy", "Sugar Daddy".
    It pages with ``&page=N``.

Cards
    ``.page-item-detail`` blocks holding ``.item-title a`` (the title is on
    the ``title`` attribute as well as the link text) and an ``img`` whose
    ``data-src``/``src`` both carry the cover.

Chapters
    The series page lists ``/manga/<slug>/chapter-N`` links. It also carries
    "Read First"/"Read Last" shortcut buttons pointing at chapters, so hrefs
    are de-duplicated and those two labels are rewritten from the URL.

Images
    ``.read-content img`` on the chapter page, served from
    ``img01.mangadass.com``. Measured: the CDN hotlinks fine -- 200 and the
    identical 1,064,703 bytes with and without a Referer.
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://mangadass.com"


class MangadassSource(Source):
    id = "mangadass"
    name = "Mangadass"
    base_url = SITE
    domains = ("mangadass.com", "img01.mangadass.com")

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True
    #: The catalogue is overwhelmingly adult manhwa, so results are stamped
    #: pornographic and the source is flagged like Manhwa18 / nhentai.
    adult_only = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Trending")

    #: Genre slugs are exposed as ``/manga-genre/<slug>`` on every page.
    GENRES = (
        "action", "adventure", "comedy", "cooking", "doujinshi", "drama",
        "ecchi", "fantasy", "gender-bender", "harem", "historical", "horror",
        "isekai", "josei", "manhua", "manhwa", "martial-arts", "mature",
        "mystery", "psychological", "romance", "school-life", "sci-fi",
        "seinen", "shoujo", "shounen", "slice-of-life", "smut", "sports",
        "supernatural", "thriller", "tragedy", "webtoon", "yaoi", "yuri",
    )

    # ---------------------------------------------------------- helpers

    def _cards(self, soup, limit):
        """Parse a ``.page-item-detail`` grid. Shared by search and browse."""
        results, seen = [], set()
        for card in soup.select(".page-item-detail"):
            link = card.select_one(".item-title a") or card.select_one("a[href]")
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            if href in seen:
                continue

            title = (link.get("title") or link.get_text(" ", strip=True) or "").strip()
            if not title:
                continue

            cover = None
            img = card.select_one("img")
            if img is not None:
                cover = (img.get("data-src") or img.get("src") or "").strip()
                if cover:
                    cover = urljoin(SITE, cover)

            # The newest chapter is listed on the card; surface it so the
            # chapter-count filters have something to judge.
            latest = None
            chapter = card.select_one(".chapter-item a, .chapter a")
            if chapter is not None:
                latest = chapter.get_text(" ", strip=True) or None

            seen.add(href)
            results.append(self._result(
                title, href, cover=cover,
                latest=latest,
                content_rating="pornographic",
                tags=["Adult"],
                adult=True,
            ))
            if len(results) >= limit:
                break
        return results

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        # /?s= is a decoy that ignores the term -- /search?q= is the real one.
        url = f"{SITE}/search?q={quote(query)}"
        page = max(1, int(page or 1))
        if page > 1:
            url += f"&page={page}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("mangadass search failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        page = max(1, int(page or 1))
        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            url = f"{SITE}/manga-genre/{quote(slug)}"
            if page > 1:
                url += f"?page={page}"
        else:
            url = SITE if page == 1 else f"{SITE}/?page={page}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("mangadass browse failed: %s", e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def genres(self) -> list:
        return [{"id": slug, "name": slug.replace("-", " ").title()}
                for slug in self.GENRES]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        heading = soup.select_one(".post-title h1, .post-title h3, h1")
        title = heading.get_text(" ", strip=True) if heading else "Unknown"

        cover = None
        img = soup.select_one(".summary_image img, .tab-summary img, "
                              ".item-thumb img")
        if img is not None:
            cover = (img.get("data-src") or img.get("src") or "").strip()
            if cover:
                cover = urljoin(SITE, cover)

        description = None
        block = soup.select_one(".description-summary, .summary__content, "
                                ".manga-excerpt")
        if block is not None:
            description = re.sub(r"\s+", " ", block.get_text(" ", strip=True)) or None

        tags = ["Adult"]
        for link in soup.select('a[href*="/manga-genre/"]'):
            label = link.get_text(strip=True)
            if label and label not in tags:
                tags.append(label)

        authors = [a.get_text(strip=True)
                   for a in soup.select('a[href*="/manga-author/"]')
                   if a.get_text(strip=True)]

        status = None
        match = re.search(r"Status\s*:?\s*(Ongoing|Completed|Hiatus|Dropped|OnGoing)",
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

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        # Restrict to this series -- the page advertises other titles too.
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
            # "Read First" / "Read Last" shortcut buttons carry no label.
            if not name or re.fullmatch(r"read\s+(first|last)", name, re.I):
                name = path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        # Document order cannot be trusted: the "Read First"/"Read Last"
        # shortcut buttons sit *above* the list and point at real chapters,
        # so a plain reverse() left Chapter 1 stranded at the end (measured:
        # 2,3,4,5,6,7,8,1). Sort on the number parsed out of the URL, which
        # is stable, and keep unparsable entries at the end in page order.
        def sort_key(entry):
            match = re.search(r"chapter-(\d+(?:[-.]\d+)?)",
                              entry["url"], re.I)
            if not match:
                return (1, 0.0)
            return (0, float(match.group(1).replace("-", ".")))

        chapters.sort(key=sort_key)
        return chapters

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)
        soup = BeautifulSoup(response.content, "html.parser")

        images = []
        for img in soup.select(".read-content img, .reading-content img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src:
                continue
            src = urljoin(SITE, src)
            # skip the site chrome (logo etc.) that shares the container
            if "/images/" in src and "logo" in src.lower():
                continue
            if src not in images:
                images.append(src)
        return images
