"""ManhwaRead source (HTML scraping).

Two things about this site are easy to get wrong, both established by
inspecting live pages:

Page images are not in the markup
    The reader renders every page as a ``blob:`` URL created in JavaScript,
    so scraping ``<img src>`` returns nothing usable. The real list is
    embedded in an inline script as base64-encoded JSON::

        var chapterData = {"base": "https://manread.xyz/7077",
                           "data": "<base64>"};

    Decoding ``data`` yields ``[{"src": "126682/mr_001.jpg", "w":…, "h":…},…]``
    and the page URL is simply ``{base}/{src}``.

Image CDN requires a Referer
    ``manread.xyz`` answers **403** with no Referer and **200** with
    ``https://manhwaread.com/``. Every chapter therefore carries an explicit
    ``referer`` so the download engine sends it. Covers are on a different
    host (``mancover.xyz``) and hotlink freely.
"""

import base64
import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://manhwaread.com"

# var chapterData = { ... };  -- the object is small and always one line
_CHAPTER_DATA = re.compile(r"var\s+chapterData\s*=\s*(\{.*?\})\s*;", re.S)


def _b64_decode(data):
    """Decode base64 that may have had its ``=`` padding stripped.

    The site emits the payload without padding whenever the length is not a
    multiple of four, and Python's ``base64.b64decode`` is strict about it.
    Measured over twelve consecutive chapters of one series, one (chapter 03,
    ``len % 4 == 2``) raised ``binascii.Error: Incorrect padding`` while the
    other eleven decoded fine -- which is why single-chapter downloads
    usually worked and a bulk range reliably lost chapters.

    Re-padding to the next multiple of four restores it; the same bytes then
    parse as the normal page list.
    """
    if isinstance(data, bytes):
        data = data.decode("ascii", "ignore")
    data = re.sub(r"\s+", "", data or "")
    data += "=" * (-len(data) % 4)
    return base64.b64decode(data)


class ManhwaReadSource(Source):
    id = "manhwaread"
    name = "ManhwaRead"
    base_url = SITE
    domains = ("manhwaread.com", "manread.xyz", "mancover.xyz")

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Best Match", "Latest Updates", "Popularity", "New")
    browse_sorts = ("Trending", "Latest Updates", "Popularity", "New")

    _SORTS = {
        "Trending": "trending",
        "Popularity": "views",
        "Latest Updates": "latest",
        "New": "new",
    }

    GENRES = (
        "action", "adult", "adventure", "comedy", "drama", "fantasy",
        "harem", "historical", "horror", "josei", "mature", "mystery",
        "psychological", "romance", "school-life", "sci-fi", "seinen",
        "shoujo", "slice-of-life", "supernatural", "thriller", "tragedy",
    )

    def headers(self):
        h = super().headers()
        h["Referer"] = SITE + "/"
        return h

    # ---------------------------------------------------------- listing

    def _parse_listing(self, response, limit):
        """Parse a grid of series cards, shared by search and browse.

        The anchor text on this theme is the literal word "Read" (it is a
        hover button), and the visible title lives on the cover image's
        ``alt`` attribute. Reading the link text yields a grid of items all
        called "Read", so the image alt is the primary source of the title.
        """
        soup = BeautifulSoup(response.content, "html.parser")
        results, seen = [], set()

        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not re.search(r"/(?:manhwa|manga|webtoon)/[^/]+/?$", href):
                continue
            if "/chapter" in href:
                continue
            full = urljoin(SITE, href)
            if full in seen:
                continue

            # climb to the card root, which holds the cover and the title
            card, img = link, None
            for _ in range(6):
                if card is None:
                    break
                img = card.find("img") if hasattr(card, "find") else None
                if img is not None:
                    break
                card = card.parent

            title = ""
            if img is not None:
                title = (img.get("alt") or "").strip()
            if not title:
                heading = None
                if card is not None and hasattr(card, "select_one"):
                    heading = card.select_one(
                        ".manga-item__title, h3, h2, .post-title")
                if heading is not None:
                    title = heading.get_text(" ", strip=True)
            if not title:
                candidate = (link.get("title")
                             or link.get_text(" ", strip=True) or "").strip()
                # "Read" is the hover button label, not a title
                if candidate.lower() not in ("read", "read now", ""):
                    title = candidate
            if not title:
                # last resort: humanise the slug
                title = href.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            if len(title) < 2:
                continue

            cover = None
            if img is not None:
                cover = (img.get("src") or img.get("data-src")
                         or img.get("data-lazy-src"))
                if cover:
                    cover = urljoin(SITE, cover)

            seen.add(full)
            results.append(self._result(title, full, cover=cover))
            if len(results) >= limit:
                break
        return results

    def search(self, query: str, limit: int = 32, genre=None, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(genre=genre, limit=limit)
        url = f"{SITE}/?s={quote(query)}&post_type=wp-manga"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("ManhwaRead search failed: %s", e)
            return []
        return self._parse_listing(response, limit)

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, **_):
        page = max(1, int(page or 1))
        if genre:
            slug = str(genre).strip().lower().replace(" ", "-")
            url = f"{SITE}/genre/{quote(slug)}/"
        else:
            url = f"{SITE}/"
        if page > 1:
            url = url.rstrip("/") + f"/page/{page}/"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("ManhwaRead browse failed: %s", e)
            return []
        return self._parse_listing(response, limit)

    def genres(self) -> list:
        return [{"id": slug, "name": slug.replace("-", " ").title()}
                for slug in self.GENRES]

    # ------------------------------------------------------------ info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        # The <h1> is the site banner on this theme, so prefer og:title.
        title = None
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            raw = og_title["content"]
            # strip site furniture: "Title - #12341 - Read ... | ManhwaRead"
            raw = raw.split("|")[0]
            raw = re.split(r"\s+-\s+#\d+", raw)[0]
            raw = re.sub(r"\s+-\s+Read\b.*$", "", raw, flags=re.I)
            title = raw.strip()
        if not title:
            heading = soup.select_one("h1.entry-title, .post-title h1, h1")
            title = heading.get_text(strip=True) if heading else "Unknown"

        cover = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            cover = og_image["content"]
        if not cover:
            img = soup.select_one(".summary_image img, .thumb img")
            if img is not None:
                cover = img.get("src") or img.get("data-src")

        description = None
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            description = og_desc["content"].strip()
        if not description:
            block = soup.select_one(".description-summary, .summary__content")
            if block is not None:
                description = re.sub(r"\s+", " ",
                                     block.get_text(" ", strip=True)).strip()

        tags, authors, status = [], [], None
        for link in soup.select('a[href*="/genre/"]'):
            label = link.get_text(strip=True)
            if label and label not in tags:
                tags.append(label)
        for link in soup.select('a[href*="/author/"], a[href*="/artist/"]'):
            label = link.get_text(strip=True)
            if label and label not in authors:
                authors.append(label)
        text = soup.get_text(" ", strip=True)
        match = re.search(r"Status\s*:?\s*(Ongoing|Completed|Hiatus|Dropped)",
                          text, re.I)
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
            "source": self.id,
            "source_name": self.name,
        }

    # -------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        # Only keep chapters belonging to THIS series: the page also lists
        # "latest updates" for unrelated titles.
        series_path = self.series_path(manga_url)
        chapters, seen = [], set()

        for link in soup.select('a[href*="/chapter"]'):
            href = link.get("href") or ""
            full = urljoin(SITE, href)
            path = re.sub(r"^https?://[^/]+", "", full)
            if not path.startswith(series_path + "/"):
                continue
            if full in seen:
                continue
            name = link.get_text(" ", strip=True)
            # The shortcut buttons render as "Read First Chapter 01"; keep
            # only the chapter part so numbering parses correctly.
            name = re.sub(r"^\s*read\s+(first|last)\s*", "", name, flags=re.I).strip()
            if not name:
                name = path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            seen.add(full)
            chapters.append({
                "url": full,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })

        from ..utils import chapter_number
        chapters.sort(key=lambda c: chapter_number(c["name"]))
        return chapters

    # ----------------------------------------------------------- pages

    @staticmethod
    def decode_payload(data):
        """Decode the chapter payload, tolerating missing base64 padding."""
        return _b64_decode(data).decode("utf-8", "replace")

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        if not chapter_url:
            return []
        response = self.fetch(chapter_url)
        html = response.text

        match = _CHAPTER_DATA.search(html)
        if not match:
            raise ScrapeError(
                f"No chapterData block found for {chapter_url} "
                "(the site layout may have changed)")

        try:
            payload = json.loads(match.group(1))
            pages = json.loads(self.decode_payload(payload["data"]))
        except Exception as e:
            raise ScrapeError(f"Could not decode chapterData for {chapter_url}: {e}")

        base = (payload.get("base") or "").rstrip("/")
        urls = []
        for page in pages:
            src = (page or {}).get("src") if isinstance(page, dict) else page
            if not src:
                continue
            urls.append(src if str(src).startswith("http")
                        else f"{base}/{str(src).lstrip('/')}")

        if not urls:
            raise ScrapeError(f"chapterData held no pages for {chapter_url}")
        return urls

    def download_file(self, url, filepath, referer=None, max_retries=5, headers=None):
        # manread.xyz returns 403 without a Referer; the site origin works.
        return super().download_file(url, filepath, referer or SITE + "/",
                                     max_retries, headers)
