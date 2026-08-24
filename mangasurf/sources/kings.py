"""Kings Manga (kings-manga.com / kingsmanga.net) source scraper for Mangasurf.

High-speed scraper for action manhwa and manga series.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://kings-manga.com"


class KingsSource(Source):
    id = "kings"
    name = "Kings Manga"
    base_url = SITE
    domains = (
        "kings-manga.com", "www.kings-manga.com",
        "kingsmanga.net", "www.kingsmanga.net",
        "kingscans.com", "www.kingscans.com",
    )

    default_series_type = "Manhwa"
    cover_needs_referer = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Relevance", "Latest", "Popular", "Rating")
    browse_sorts = ("Trending", "Latest", "Popular", "Rating")

    GENRES = (
        ("action", "Action"),
        ("adventure", "Adventure"),
        ("comedy", "Comedy"),
        ("drama", "Drama"),
        ("fantasy", "Fantasy"),
        ("martial-arts", "Martial Arts"),
        ("murim", "Murim"),
        ("reincarnation", "Reincarnation"),
        ("shounen", "Shounen"),
        ("supernatural", "Supernatural"),
        ("system", "System"),
        ("webtoons", "Webtoons"),
    )

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 24, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        url = f"{self.base_url}/page/{page}/?s={quote(query)}"
        resp = self.fetch(url, timeout=12)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for card in soup.select(".bsx, .animposx, .listupd .bs, .film-item, article"):
            link_el = card.select_one("a[href]")
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)

            title_el = card.select_one(".tt, .title, h4, h3, .entry-title") or link_el
            title = title_el.get_text(strip=True) if title_el else "Untitled"

            img_el = card.select_one("img[src], img[data-src], img[data-lazy-src]")
            cover = None
            if img_el:
                cover = img_el.get("data-src") or img_el.get("data-lazy-src") or img_el.get("src")
                if cover and cover.startswith("//"):
                    cover = "https:" + cover
                elif cover and not cover.startswith("http"):
                    cover = urljoin(self.base_url, cover)

            stype = classify_type(text=title) or self.default_series_type
            results.append(self._result(
                title, href, cover=cover,
                series_type=stype,
            ))
            if len(results) >= limit:
                break

        return results

    def browse(self, sort: str = "Trending", genre: str = None,
               page: int = 1, limit: int = 24, **_):
        page = max(1, int(page or 1))
        if genre:
            url = f"{self.base_url}/genres/{genre}/page/{page}/"
        elif sort == "Latest":
            url = f"{self.base_url}/manga/?page={page}&order=update"
        elif sort == "Popular":
            url = f"{self.base_url}/manga/?page={page}&order=popular"
        else:
            url = f"{self.base_url}/manga/?page={page}&order=trending"

        resp = self.fetch(url, timeout=12)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for card in soup.select(".bsx, .animposx, .listupd .bs, .film-item, article"):
            link_el = card.select_one("a[href]")
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)

            title_el = card.select_one(".tt, .title, h4, h3, .entry-title") or link_el
            title = title_el.get_text(strip=True) if title_el else "Untitled"

            img_el = card.select_one("img[src], img[data-src], img[data-lazy-src]")
            cover = None
            if img_el:
                cover = img_el.get("data-src") or img_el.get("data-lazy-src") or img_el.get("src")
                if cover and cover.startswith("//"):
                    cover = "https:" + cover
                elif cover and not cover.startswith("http"):
                    cover = urljoin(self.base_url, cover)

            stype = classify_type(text=title) or self.default_series_type
            results.append(self._result(
                title, href, cover=cover,
                series_type=stype,
            ))
            if len(results) >= limit:
                break

        return results

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        resp = self.fetch(manga_url, timeout=12)
        if resp.status_code != 200:
            raise ScrapeError(f"Kings manga failed: HTTP {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")
        title_el = soup.select_one("h1.entry-title, .entry-title, .manga-title, h1")
        title = title_el.get_text(strip=True) if title_el else "Untitled"

        cover_el = soup.select_one(".thumb img, .infox img, .imgdesc img, .seriestucontentr img")
        cover = None
        if cover_el:
            cover = cover_el.get("data-src") or cover_el.get("data-lazy-src") or cover_el.get("src")
            if cover and cover.startswith("//"):
                cover = "https:" + cover
            elif cover and not cover.startswith("http"):
                cover = urljoin(self.base_url, cover)

        desc_el = soup.select_one(".entry-content, .synopsis, .desc, .seriestuhead p")
        desc = desc_el.get_text(strip=True) if desc_el else ""

        genres = [g.get_text(strip=True) for g in soup.select(".seriestugenre a, .genres-content a, .mgen a")]
        status_el = soup.select_one(".status, span:contains('Status')")
        status = "Ongoing"
        if status_el:
            txt = status_el.get_text(strip=True)
            if "completed" in txt.lower():
                status = "Completed"

        authors = [a.get_text(strip=True) for a in soup.select(".author, .author-content a, .tsinfo .imptdt:contains('Author') i")]
        stype = classify_type(tags=genres, text=title) or self.default_series_type

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": genres[:25],
            "status": status,
            "authors": authors or ["Kings Team"],
            "artists": [],
            "series_type": stype,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        resp = self.fetch(manga_url, timeout=12)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        chapters = []

        for li in soup.select("#chapterlist li, .eplister li, .clstyle li, .chapter-list li"):
            link_el = li.select_one("a[href]")
            if not link_el:
                continue
            href = link_el["href"]
            if not href.startswith("http"):
                href = urljoin(self.base_url, href)

            num_el = li.select_one(".chapternum, .chapter-name, .ch-num") or link_el
            name = num_el.get_text(strip=True) if num_el else "Chapter"
            date_el = li.select_one(".chapterdate, .ch-date, .date")
            date_str = date_el.get_text(strip=True) if date_el else ""

            chapters.append({
                "url": href,
                "name": name,
                "date": date_str,
                "referer": manga_url,
                "source": self.id,
            })

        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        resp = self.fetch(chapter_url, timeout=12)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        images = []

        # Check standard reader container
        for img in soup.select("#readerarea img, .reader-area img, .ts-main-image, .chapter-image img"):
            u = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if u:
                u = u.strip()
                if u.startswith("//"):
                    u = "https:" + u
                elif not u.startswith("http"):
                    u = urljoin(self.base_url, u)
                images.append(u)

        # Fallback to embedded script JSON images
        if not images:
            script_matches = re.findall(r'ts_reader\.run\((.*?)\);', resp.text, re.DOTALL)
            for sm in script_matches:
                try:
                    data = json.loads(sm)
                    sources = data.get("sources", [])
                    if sources and isinstance(sources, list):
                        for img_obj in sources[0].get("images", []):
                            if isinstance(img_obj, str) and img_obj.startswith("http"):
                                images.append(img_obj)
                except Exception:
                    pass

        return images
