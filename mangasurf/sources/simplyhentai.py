"""SimplyHentai source scraper for Mangasurf.

Supports full metadata extraction, multi-tag combinations (tag/<tag1>/tag-1-<tag2>),
series browsing, and full-resolution image downloads.
"""

import json
import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://www.simply-hentai.com"


class SimplyHentaiSource(Source):
    id = "simplyhentai"
    name = "SimplyHentai"
    base_url = SITE
    domains = ("simply-hentai.com", "www.simply-hentai.com", "sh-cdn.com", "images.sh-cdn.com")
    adult_only = True

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Latest", "Popularity", "Rating")
    browse_sorts = ("Trending", "Popularity", "Latest Updates")

    GENRES = (
        "sole-male", "sole-female", "big-breasts", "stockings", "schoolgirl-uniform",
        "maid", "swimsuit", "glasses", "milf", "nakadashi", "ahegao", "anal",
        "yuri", "yaoi", "netorare", "harem", "group", "collar", "twintails",
        "elf", "blowjob", "paizuri", "imouto", "cheating", "masturbation",
    )

    def headers(self) -> dict:
        h = super().headers()
        h.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Referer": f"{SITE}/",
        })
        return h

    def genres(self) -> list:
        return [{"id": name, "name": name.replace("-", " ").title()} for name in self.GENRES]

    @staticmethod
    def _extract_next_data(html_content: str) -> dict:
        try:
            soup = BeautifulSoup(html_content, "html.parser")
            script = soup.select_one("script#__NEXT_DATA__")
            if script and script.string:
                return json.loads(script.string)
        except Exception as e:
            logger.debug("Failed to extract __NEXT_DATA__: %s", e)
        return {}

    def _build_tag_url(self, tags: list, page: int = 1) -> str:
        """Construct SimplyHentai tag combination URL: /tag/<tag1>/tag-1-<tag2>/tag-2-<tag3>."""
        if not tags:
            return f"{SITE}/series?page={page}"
        clean_tags = [re.sub(r"[^a-z0-9]+", "-", str(t).lower()).strip("-") for t in tags if str(t).strip()]
        if not clean_tags:
            return f"{SITE}/series?page={page}"

        first = clean_tags[0]
        rest = clean_tags[1:]
        url_path = f"/tag/{first}"
        for idx, tag in enumerate(rest, 1):
            url_path += f"/tag-{idx}-{tag}"

        if page > 1:
            url_path += f"?page={page}"
        return urljoin(SITE, url_path)

    def _parse_manga_items(self, props: dict) -> list:
        """Extract albums or mangas from pageProps."""
        items = (
            props.get("mangas")
            or props.get("albums")
            or (props.get("series", {}).get("albums") if isinstance(props.get("series"), dict) else None)
            or props.get("series")
            or props.get("popular")
            or props.get("newest")
            or props.get("hottest")
            or []
        )
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or "Unknown Album"
            slug = item.get("slug")
            if not slug:
                continue

            series_slug = ""
            if isinstance(item.get("series"), dict):
                series_slug = item["series"].get("slug") or ""
            elif isinstance(props.get("series"), dict):
                series_slug = props["series"].get("slug") or ""

            if series_slug and series_slug != slug:
                url = f"{SITE}/{series_slug}/{slug}"
            else:
                url = f"{SITE}/series/{slug}"

            preview = item.get("preview") or {}
            sizes = preview.get("sizes") or {}
            cover = sizes.get("thumb") or sizes.get("full") or sizes.get("small_thumb") or sizes.get("giant_thumb")

            results.append(self._result(
                title,
                url,
                cover=cover,
                content_rating="pornographic",
                adult=True,
                tags=["Adult"],
            ))
        return results

    def search(self, query: str, limit: int = 32, sort=None, genre=None, page: int = 1, **_) -> list:
        query = (query or "").strip()
        page_val = max(1, int(page or 1))

        # 1. Parse tag lists from genre and query (e.g. #sole-female #sole-male)
        tags_list = []
        if genre:
            for g in ([genre] if isinstance(genre, str) else (genre or [])):
                if isinstance(g, str) and g.strip():
                    tags_list.append(g.strip().lower().replace("tag:", ""))

        if "#" in query:
            for tag_match in re.findall(r"#([a-zA-Z0-9_-]+)", query):
                tags_list.append(tag_match.replace("_", "-").lower())
            query = re.sub(r"#[a-zA-Z0-9_-]+", "", query).strip()

        # If pure tag query or tag combination
        if tags_list and not query:
            tag_url = self._build_tag_url(tags_list, page=page_val)
            try:
                resp = self.fetch(tag_url, timeout=6)
                data = self._extract_next_data(resp.text)
                props = data.get("props", {}).get("pageProps", {})
                results = self._parse_manga_items(props)
                if results:
                    return results[:limit]
            except Exception as e:
                logger.debug("SimplyHentai tag search failed on %s: %s", tag_url, e)

        # Series search by slug
        clean_q = re.sub(r"[^a-zA-Z0-9_-]+", "-", query.lower()).strip("-")
        if clean_q:
            series_url = f"{SITE}/series/{clean_q}"
            if page_val > 1:
                series_url += f"?page={page_val}"
            try:
                resp = self.fetch(series_url, timeout=6)
                data = self._extract_next_data(resp.text)
                props = data.get("props", {}).get("pageProps", {})
                results = self._parse_manga_items(props)
                if results:
                    return results[:limit]
            except Exception:
                pass

        # Fallback to general browse
        return self.browse(sort=sort, genre=genre, page=page_val, limit=limit)

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 32, **_) -> list:
        page_val = max(1, int(page or 1))
        if genre:
            tag_url = self._build_tag_url([genre], page=page_val)
        else:
            tag_url = f"{SITE}/series?page={page_val}" if page_val > 1 else f"{SITE}/"

        try:
            resp = self.fetch(tag_url, timeout=6)
            data = self._extract_next_data(resp.text)
            props = data.get("props", {}).get("pageProps", {})
            results = self._parse_manga_items(props)
            return results[:limit]
        except Exception as e:
            logger.warning("SimplyHentai browse failed: %s", e)
            return []

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        resp = self.fetch(manga_url, timeout=6)
        data = self._extract_next_data(resp.text)
        props = data.get("props", {}).get("pageProps", {})

        manga = props.get("manga") or props.get("data") or props.get("album") or props.get("series") or {}
        title = manga.get("title") or manga.get("name") or "SimplyHentai Album"
        description = manga.get("description") or ""

        preview = manga.get("preview") or {}
        sizes = preview.get("sizes") or {}
        cover = sizes.get("full") or sizes.get("thumb") or sizes.get("giant_thumb")

        tags = ["Adult"]
        for t in manga.get("tags") or []:
            if isinstance(t, dict) and t.get("title"):
                tags.append(t["title"])
            elif isinstance(t, str):
                tags.append(t)

        artists = [a.get("title") if isinstance(a, dict) else str(a) for a in (manga.get("artists") or [])]
        pages = int(manga.get("image_count") or len(manga.get("images") or []) or 1)

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:25],
            "status": "Completed",
            "authors": artists,
            "artists": artists,
            "pages": pages,
            "content_rating": "pornographic",
            "adult": True,
            "source": self.id,
            "source_name": self.name,
        }

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        return [{
            "url": manga_url,
            "name": "Full Album",
            "source": self.id,
            "sort_no": 1.0,
        }]

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self._chapter_url(chapter)
        if not chapter_url:
            return []

        resp = self.fetch(chapter_url, timeout=6)
        data = self._extract_next_data(resp.text)
        props = data.get("props", {}).get("pageProps", {})

        manga = props.get("manga") or props.get("data") or props.get("album") or props.get("series") or {}
        images = manga.get("images") or []
        urls = []
        for img in images:
            if isinstance(img, dict) and img.get("sizes"):
                full = img["sizes"].get("full") or img["sizes"].get("giant_thumb") or img["sizes"].get("thumb")
                if full:
                    urls.append(full)
            elif isinstance(img, str):
                urls.append(img)
        return urls
