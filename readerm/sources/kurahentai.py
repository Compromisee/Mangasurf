"""KuraHentai (kurahentai.com) source scraper for Mangasurf.

High-resolution Hentai Manga, Doujinshi, and Adult Comics gallery reader.
Backed by Supabase REST API for instant multi-page discovery and gallery streaming.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://kurahentai.com"
SUPABASE_REST = "https://ikqewfksewzgnkcvtvor.supabase.co/rest/v1"
SUPABASE_KEY = "sb_publishable_wUsGyZzpiMfbcsk5IrYYSw_zIqZ56ds"


class KuraHentaiSource(Source):
    id = "kurahentai"
    name = "KuraHentai"
    base_url = SITE
    domains = ("kurahentai.com", "www.kurahentai.com", "hentai.shadowabyss.com", "shadowabyss.com")

    default_series_type = "Manga"
    cover_needs_referer = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Recent", "Popular")
    browse_sorts = ("Recent", "Popular")

    GENRES = (
        ("sole-female", "Sole Female"),
        ("sole-male", "Sole Male"),
        ("big-breasts", "Big Breasts"),
        ("milf", "MILF"),
        ("schoolgirl-uniform", "Schoolgirl"),
        ("maid", "Maid"),
        ("stockings", "Stockings"),
        ("glasses", "Glasses"),
        ("nakadashi", "Nakadashi"),
        ("collar", "Collar"),
        ("swimsuit", "Swimsuit"),
        ("ahegao", "Ahegao"),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"{SITE}/",
            "Origin": SITE,
        })

    def _api_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        }

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 25, page: int = 1, **_):
        query = (query or "").strip()
        page = max(1, int(page or 1))
        offset = (page - 1) * limit

        # 1. Supabase REST API
        try:
            url = f"{SUPABASE_REST}/hentai?select=id,full_title,num_pages,favorites,cover_url&order=id.desc&limit={limit}&offset={offset}"
            if query:
                clean_q = quote(f"*{query}*")
                url += f"&full_title=ilike.{clean_q}"

            resp = self.session.get(url, headers=self._api_headers(), timeout=8)
            if resp.status_code == 200:
                items = resp.json()
                results = []
                for it in items:
                    gid = it.get("id")
                    title = it.get("full_title") or f"Gallery {gid}"
                    href = f"{SITE}/gallery/{gid}"
                    cover = it.get("cover_url") or f"https://hentai.shadowabyss.com/hentai/{gid}/cover/cover.webp"
                    num_pages = it.get("num_pages")
                    latest = f"{num_pages} pages" if num_pages else None

                    results.append(self._result(
                        title, href, cover=cover,
                        latest=latest, series_type="Manga",
                    ))
                return results
        except Exception as e:
            logger.debug("kurahentai supabase search failed: %s; falling back to html", e)

        # 2. HTML fallback
        html_url = f"{SITE}/?q={quote(query)}" if query else f"{SITE}/?page={page}"
        try:
            resp = self.fetch(html_url)
            soup = BeautifulSoup(resp.content, "html.parser")
            results, seen = [], set()

            for card in soup.select(".card, a[href*='/gallery/']"):
                a = card if card.name == "a" else card.find("a", href=True)
                if not a or not a.get("href"):
                    continue
                href = urljoin(SITE, a["href"])
                if href in seen or "/gallery/" not in href:
                    continue

                title_el = card.select_one(".caption, .title, .name") or a
                title = title_el.get_text(" ", strip=True) if title_el else ""
                if not title:
                    continue

                cover = None
                img = card.find("img")
                if img:
                    cover = img.get("data-src") or img.get("src")
                    if cover:
                        cover = urljoin(SITE, cover)

                seen.add(href)
                results.append(self._result(
                    title, href, cover=cover,
                    series_type="Manga",
                ))
                if len(results) >= limit:
                    break
            return results
        except Exception as e:
            logger.error("kurahentai search failed: %s", e)
            return []

    def browse(self, sort: str = "Recent", genre: str = None,
               page: int = 1, limit: int = 25, **_):
        page = max(1, int(page or 1))
        offset = (page - 1) * limit
        order_col = "favorites.desc" if sort == "Popular" else "id.desc"

        try:
            url = f"{SUPABASE_REST}/hentai?select=id,full_title,num_pages,favorites,cover_url&order={order_col}&limit={limit}&offset={offset}"
            resp = self.session.get(url, headers=self._api_headers(), timeout=8)
            if resp.status_code == 200:
                items = resp.json()
                results = []
                for it in items:
                    gid = it.get("id")
                    title = it.get("full_title") or f"Gallery {gid}"
                    href = f"{SITE}/gallery/{gid}"
                    cover = it.get("cover_url") or f"https://hentai.shadowabyss.com/hentai/{gid}/cover/cover.webp"
                    num_pages = it.get("num_pages")
                    latest = f"{num_pages} pages" if num_pages else None

                    results.append(self._result(
                        title, href, cover=cover,
                        latest=latest, series_type="Manga",
                    ))
                return results
        except Exception as e:
            logger.debug("kurahentai supabase browse failed: %s", e)

        return self.search("", limit=limit, page=page)

    def genres(self) -> list:
        return [{"id": slug, "name": label} for slug, label in self.GENRES]

    # ------------------------------------------------------------- info

    @staticmethod
    def _extract_id(url: str) -> str:
        match = re.search(r"/gallery/(\d+)", url)
        return match.group(1) if match else ""

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        gid = self._extract_id(manga_url)
        gallery_url = f"{SITE}/gallery/{gid}" if gid else manga_url

        resp = self.fetch(gallery_url)
        soup = BeautifulSoup(resp.content, "html.parser")

        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else f"Gallery {gid}"

        cover = None
        img = soup.select_one(".cover img, img[src*='cover']")
        if img:
            cover = img.get("data-src") or img.get("src")
        if not cover and gid:
            cover = f"https://hentai.shadowabyss.com/hentai/{gid}/cover/cover.webp"

        tags = [a.get_text(strip=True) for a in soup.select(".tag, .tags a, a[href*='/tag/'], a[href*='/artist/']")]

        return {
            "url": gallery_url,
            "title": title,
            "cover": cover,
            "description": None,
            "tags": tags[:25],
            "status": "Completed",
            "authors": [],
            "artists": [],
            "series_type": "Manga",
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        gid = self._extract_id(manga_url)
        gallery_url = f"{SITE}/gallery/{gid}" if gid else manga_url

        return [{
            "url": gallery_url,
            "name": "Full Gallery",
            "referer": gallery_url,
            "source": self.id,
        }]

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        gid = self._extract_id(chapter_url)
        resp = self.fetch(chapter_url)

        # 1. Match all pages from shadowabyss CDN
        pages = re.findall(r'https://hentai\.shadowabyss\.com/hentai/' + gid + r'/pages/(\d+)t?\.webp', resp.text)
        if pages:
            # Sort page numbers numerically
            page_nums = sorted(set(map(int, pages)))
            return [
                f"https://hentai.shadowabyss.com/hentai/{gid}/pages/{p:04d}.webp"
                for p in page_nums
            ]

        # 2. Extract DOM thumbnails and convert to full-res
        soup = BeautifulSoup(resp.content, "html.parser")
        images = []
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("src") or ""
            if "/pages/" in src and src.endswith(".webp"):
                clean = src.replace("t.webp", ".webp")
                if clean not in images:
                    images.append(clean)
        return images
