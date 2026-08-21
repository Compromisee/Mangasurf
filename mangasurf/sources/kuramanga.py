"""KuraManga (kuramanga.com) source scraper for Mangasurf.

High-quality reader for Manhwa, Manga, and Webtoons with direct CDN image delivery.
"""

import logging
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://kuramanga.com"


class KuraMangaSource(Source):
    id = "kuramanga"
    name = "KuraManga"
    base_url = SITE
    domains = ("kuramanga.com", "www.kuramanga.com", "shadowabyss.com", "www.shadowabyss.com")

    default_series_type = "Manhwa"
    cover_needs_referer = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Trending", "Rating", "Title")

    GENRES = (
        ("action", "Action"),
        ("adventure", "Adventure"),
        ("comedy", "Comedy"),
        ("drama", "Drama"),
        ("fantasy", "Fantasy"),
        ("isekai", "Isekai"),
        ("martial-arts", "Martial Arts"),
        ("mystery", "Mystery"),
        ("romance", "Romance"),
        ("school-life", "School Life"),
        ("sci-fi", "Sci-Fi"),
        ("shounen", "Shounen"),
        ("supernatural", "Supernatural"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{SITE}/",
            "Origin": SITE,
        })

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 18, page: int = 1, **_):
        query = (query or "").strip()
        page = max(1, int(page or 1))
        if not query:
            return self.browse(limit=limit, page=page)

        # 1. AJAX ID list + Batch Pick query for infinite multi-page pagination
        try:
            r_ids = self.session.get(f"{SITE}/search?ajax=1&ids=1&keyword={quote(query)}", timeout=8)
            if r_ids.status_code == 200:
                all_ids = r_ids.json().get("ids", [])
                if all_ids:
                    start = (page - 1) * limit
                    page_ids = all_ids[start : start + limit]
                    if page_ids:
                        ids_str = ",".join(map(str, page_ids))
                        r_pick = self.session.get(f"{SITE}/search?ajax=1&pick={ids_str}", timeout=8)
                        if r_pick.status_code == 200:
                            data = r_pick.json().get("data", [])
                            results = []
                            for item in data:
                                title = item.get("title") or "Untitled"
                                norm = item.get("normalized_title") or item.get("slug") or ""
                                href = f"{SITE}/{norm}" if norm else ""
                                cover = item.get("thumb") or f"https://shadowabyss.com/manhwa/{norm}/cover/cover.webp"
                                genres = item.get("genres") or []
                                stype = classify_type(tags=genres) or self.default_series_type
                                ch = item.get("latestChapter")
                                latest = f"Ch. {ch}" if ch else None

                                results.append(self._result(
                                    title, href, cover=cover,
                                    latest=latest, series_type=stype,
                                ))
                            return results
        except Exception as e:
            logger.debug("kuramanga id-pick search failed: %s; falling back", e)

        return self.browse(limit=limit, page=page)

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 18, **_):
        page = max(1, int(page or 1))

        # 1. AJAX ID list + Batch Pick for infinite browse pagination
        try:
            genre_param = f"&genre={quote(genre)}" if genre else ""
            r_ids = self.session.get(f"{SITE}/search?ajax=1&ids=1{genre_param}", timeout=8)
            if r_ids.status_code == 200:
                all_ids = r_ids.json().get("ids", [])
                if all_ids:
                    start = (page - 1) * limit
                    page_ids = all_ids[start : start + limit]
                    if page_ids:
                        ids_str = ",".join(map(str, page_ids))
                        r_pick = self.session.get(f"{SITE}/search?ajax=1&pick={ids_str}", timeout=8)
                        if r_pick.status_code == 200:
                            data = r_pick.json().get("data", [])
                            results = []
                            for item in data:
                                title = item.get("title") or "Untitled"
                                norm = item.get("normalized_title") or item.get("slug") or ""
                                href = f"{SITE}/{norm}" if norm else ""
                                cover = item.get("thumb") or f"https://shadowabyss.com/manhwa/{norm}/cover/cover.webp"
                                genres = item.get("genres") or []
                                stype = classify_type(tags=genres) or self.default_series_type

                                results.append(self._result(
                                    title, href, cover=cover,
                                    series_type=stype,
                                ))
                            return results
        except Exception as e:
            logger.debug("kuramanga id-pick browse failed: %s", e)

        # 2. Homepage HTML fallback (page 1 only)
        try:
            resp = self.fetch(SITE)
            soup = BeautifulSoup(resp.content, "html.parser")
            results, seen = [], set()

            for item in soup.select(".update-item, .manga-glide .glide__slide, .card"):
                a = item.find("a", href=True)
                if not a or not a["href"] or a["href"] in seen:
                    continue
                href = urljoin(SITE, a["href"])
                if href == SITE or "/search" in href:
                    continue

                title_el = item.select_one(".title, .name, h3, strong, a")
                title = title_el.get_text(" ", strip=True) if title_el else a.get_text(" ", strip=True)
                if not title or len(title) < 2:
                    continue

                cover = None
                img = item.find("img")
                if img:
                    cover = img.get("data-src") or img.get("src")
                    if cover:
                        cover = urljoin(SITE, cover)

                seen.add(href)
                results.append(self._result(
                    title, href, cover=cover,
                    series_type=self.default_series_type,
                ))
                if len(results) >= limit:
                    break
            return results
        except Exception as e:
            logger.error("kuramanga browse failed: %s", e)
            return []

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    @staticmethod
    def _extract_slug(url: str) -> str:
        path = urlparse(url).path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        return parts[0] if parts else ""

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        slug = self._extract_slug(manga_url)
        series_url = f"{SITE}/{slug}" if slug else manga_url

        resp = self.fetch(series_url)
        soup = BeautifulSoup(resp.content, "html.parser")

        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else (slug.title() if slug else "Unknown")

        cover = None
        img = soup.select_one(".cover img, .poster img, .manga-thumb img, img.card")
        if img:
            cover = img.get("data-src") or img.get("src")
        if not cover and slug:
            cover = f"https://shadowabyss.com/manhwa/{slug}/cover/cover.webp"

        desc_el = soup.select_one(".description, .summary, .synopsis, p.lead")
        desc = desc_el.get_text(" ", strip=True) if desc_el else None

        tags = [a.get_text(strip=True) for a in soup.select("a[href*='genre='], .tags a, .genres a")]
        stype = classify_type(tags=tags) or self.default_series_type

        return {
            "url": series_url,
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": tags[:20],
            "status": "Ongoing",
            "authors": [],
            "artists": [],
            "series_type": stype,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        slug = self._extract_slug(manga_url)
        series_url = f"{SITE}/{slug}" if slug else manga_url

        resp = self.fetch(series_url)
        soup = BeautifulSoup(resp.content, "html.parser")

        chapters, seen = [], set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/chapter-" in href or "/chapter/" in href:
                full_href = urljoin(SITE, href)
                if full_href in seen:
                    continue
                name = a.get_text(" ", strip=True)
                match = re.search(r"(Chapter\s*[\d.]+)", name, re.I)
                if match:
                    name = match.group(1)
                elif not name:
                    name = href.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()

                seen.add(full_href)
                chapters.append({
                    "url": full_href,
                    "name": name,
                    "referer": series_url,
                    "source": self.id,
                })

        # Oldest first
        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        resp = self.fetch(chapter_url)

        # Scrape direct shadowabyss CDN images
        cdn_images = re.findall(r'https://shadowabyss\.com/manhwa/[^\s"\'<>]+\.webp', resp.text)
        if cdn_images:
            imgs, seen = [], set()
            for u in cdn_images:
                if u not in seen and "/cover/" not in u:
                    seen.add(u)
                    imgs.append(u)
            if imgs:
                return imgs

        soup = BeautifulSoup(resp.content, "html.parser")
        images = []
        for img in soup.select(".chapter-images img, .reader-images img, #reader img, img"):
            src = img.get("data-src") or img.get("src")
            if src and any(src.endswith(ext) for ext in (".webp", ".jpg", ".jpeg", ".png")):
                full = urljoin(SITE, src)
                if full not in images and "brand_logo" not in full and "logo" not in full:
                    images.append(full)
        return images
