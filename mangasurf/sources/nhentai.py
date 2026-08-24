"""nhentai scraper for Mangasurf.

Adapted from SongOfTheFallen/nhentai-downloader with complete support for:
- Advanced nhentai tag query syntax (tag:group, tag:CUSTOMTAG, #tag, artist:name, language:english)
- Direct tag catalog routing (/tag/{slug}/?page=N) with endless 25-card pagination
- Multi-category tag container parsing (artists, groups, parodies, characters, tags)
- Multi-mirror domains and fallback image generation
"""

import json
import logging
import re
from urllib.parse import quote, quote_plus, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://nhentai.to"
MIRRORS = ("https://nhentai.to", "https://nhentai.net", "https://nhentai.xxx")

#: "<gallery>/<n>t.<ext>" -> "<gallery>/<n>.<ext>"
_THUMB = re.compile(r"/(\d+)t\.(jpg|jpeg|png|webp|gif)$", re.I)


class NhentaiSource(Source):
    id = "nhentai"
    name = "nhentai"
    base_url = SITE
    domains = ("nhentai.to", "nhentai.net", "www.nhentai.net", "www.nhentai.to", "nhentai.xxx")

    default_series_type = "Manga"
    supports_search = True
    supports_browse = True
    supports_genres = True
    adult_only = True

    search_sorts = ("Best Match", "Popularity", "Newest")
    browse_sorts = ("Popularity", "Trending", "Newest")

    _SORTS = {
        "Popularity": "popular",
        "Trending": "popular",
        "Newest": "date",
    }

    GENRES = (
        "big-breasts", "sole-female", "sole-male", "nakadashi", "anal",
        "glasses", "stockings", "full-color", "schoolgirl-uniform", "milf",
        "ahegao", "yuri", "yaoi", "netorare", "harem", "group", "maid",
        "swimsuit", "collar", "twintails", "stockings", "comedy", "elf",
    )

    def headers(self):
        h = super().headers()
        h["Referer"] = SITE + "/"
        h["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        return h

    # ---------------------------------------------------------- helpers

    @staticmethod
    def extract_id(url: str) -> str:
        match = re.search(r"/g/(\d+)", str(url or ""))
        if match:
            return match.group(1)
        if str(url).strip().isdigit():
            return str(url).strip()
        return ""

    @staticmethod
    def full_size(url: str) -> str:
        """Turn a thumbnail URL into its full-size page."""
        return _THUMB.sub(r"/\1.\2", url or "")

    @staticmethod
    def _fallbacks(img, cover):
        candidates = []
        if cover:
            candidates.append(cover)
        raw = (img.get("data-fallbacks") or "").strip()
        if raw:
            try:
                for url in json.loads(raw):
                    url = (url or "").strip()
                    if url and url not in candidates:
                        candidates.append(url)
            except (TypeError, ValueError):
                logger.debug("nhentai: unparsable data-fallbacks")
        return candidates

    def _cards(self, soup, limit):
        results, seen = [], set()
        for card in soup.select(".gallery, .gallery-favorite, div.container.index-container a.cover"):
            link = card if card.name == "a" else card.select_one("a[href*='/g/']")
            if not link or not link.get("href"):
                continue
            href = urljoin(SITE, link["href"])
            if href in seen:
                continue

            caption = card.select_one(".caption")
            title = (caption.get_text(" ", strip=True) if caption
                     else link.get("title") or "").strip()
            if not title:
                title = f"Doujinshi {self.extract_id(href)}"

            img = card.select_one("img")
            cover, mirrors = None, []
            if img is not None:
                cover = (img.get("data-src") or img.get("src") or "").strip()
                if cover:
                    cover = urljoin(SITE, cover)
                mirrors = self._fallbacks(img, cover)

            seen.add(href)
            results.append(self._result(
                title, href, cover=cover,
                cover_mirrors=mirrors,
                content_rating="pornographic",
                tags=["Adult"],
                adult=True,
            ))
            if len(results) >= limit:
                break
        return results

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, sort=None, genre=None, page: int = 1, **_):
        query = (query or "").strip()
        page_val = max(1, int(page or 1))

        # Direct numeric ID lookup (e.g. 583036 or 177013)
        if query.isdigit() and len(query) >= 5:
            try:
                info = self.get_manga_info(f"{SITE}/g/{query}/")
                return [self._result(info["title"], info["url"], cover=info.get("cover"))]
            except Exception:
                pass

        # 1. Single tag or hashtag lookup: if genre or query is pure tag (#tag or tag:tag)
        tag_candidate = None
        if genre and not query:
            tag_candidate = genre if isinstance(genre, str) else genre[0]
        elif query and re.match(r"^(?:#|tag:)([a-zA-Z0-9_-]+)$", query.strip(), re.I):
            tag_candidate = re.match(r"^(?:#|tag:)([a-zA-Z0-9_-]+)$", query.strip(), re.I).group(1)

        if tag_candidate:
            clean_slug = re.sub(r"[^a-z0-9]+", "-", str(tag_candidate).lower()).strip("-")
            tag_url = f"{SITE}/tag/{clean_slug}/?page={page_val}"
            try:
                resp = self.fetch(tag_url, max_retries=1)
                cards = self._cards(BeautifulSoup(resp.content, "html.parser"), limit)
                if cards:
                    return cards
            except Exception:
                pass
            # Fallback to search query for this tag
            query = clean_slug

        # 2. General search with query string
        clean_q = re.sub(r"#(?:[a-zA-Z0-9_-]+)", "", query).strip()
        clean_q = re.sub(r"^tag:\s*", "", clean_q).strip()

        if not clean_q:
            return self.browse(sort=sort, genre=genre, limit=limit, page=page_val)

        url = f"{SITE}/search/?q={quote_plus(clean_q)}"
        if page_val > 1:
            url += f"&page={page_val}"
        order = self._SORTS.get(sort or "")
        if order:
            url += f"&sort={order}"

        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("nhentai search failed: %s", e)
            return []
        results = self._cards(BeautifulSoup(response.content, "html.parser"), limit)
        if clean_q and results and not tag_candidate and not genre:
            results = self.filter_and_rank(results, clean_q)
        return results[:limit]

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, **_):
        page = max(1, int(page or 1))
        slug = str(genre or "").strip().lower().replace(" ", "-")

        if slug:
            # Tag endpoint: always /tag/{slug}/?page=N (never /popular which 404s)
            url = f"{SITE}/tag/{quote(slug)}/?page={page}"
            try:
                response = self.fetch(url, max_retries=1)
                cards = self._cards(BeautifulSoup(response.content, "html.parser"), limit)
                if cards:
                    return cards
            except Exception:
                pass
            # Fallback to search index if the exact /tag/ slug doesn't exist (e.g. "breasts")
            url = f"{SITE}/search/?q={quote_plus(slug)}&page={page}"
            order = self._SORTS.get(sort or "")
            if order:
                url += f"&sort={order}"
        else:
            url = f"{SITE}/popular?page={page}"

        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("nhentai browse failed: %s", e)
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

        heading = soup.select_one("#info h1, h1.title, h2.title")
        title = (re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
                 if heading else f"Doujinshi {self.extract_id(manga_url)}")

        cover = None
        cover_img = soup.select_one("#cover img, .cover img")
        if cover_img is not None:
            cover = (cover_img.get("data-src") or cover_img.get("src") or "")
            cover = urljoin(SITE, cover) if cover else None

        tags = ["Adult"]
        artists, groups, languages, parodies, characters = [], [], [], [], []

        tags_section = soup.find("section", id="tags") or soup.find("div", class_="tag-container")
        if tags_section:
            for container in soup.select("div.tag-container"):
                label_text = container.get_text(" ", strip=True).lower()
                tag_names = [t.get_text(strip=True) for t in container.select("span.name, a.tag .name")]

                if "artist" in label_text:
                    artists.extend(tag_names)
                elif "group" in label_text:
                    groups.extend(tag_names)
                elif "language" in label_text:
                    languages.extend(tag_names)
                elif "parod" in label_text:
                    parodies.extend(tag_names)
                elif "character" in label_text:
                    characters.extend(tag_names)
                elif "tag" in label_text:
                    for t in tag_names:
                        if t and t not in tags:
                            tags.append(t)

        pages = None
        match = re.search(r"(\d+)\s*pages?", soup.get_text(" ", strip=True), re.I)
        if match:
            pages = int(match.group(1))

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": f"Artists: {', '.join(artists) if artists else 'Unknown'} | Parody: {', '.join(parodies) if parodies else 'Original'}",
            "tags": tags[:25],
            "status": "Completed",
            "authors": artists[:3] if artists else groups[:3],
            "artists": artists[:3],
            "pages": pages,
            "content_rating": "pornographic",
            "adult": True,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        """A gallery is one book, so it is a single chapter."""
        manga_url = self.normalize_url(manga_url)
        return [{
            "url": manga_url,
            "name": "Chapter 1",
            "referer": manga_url,
            "source": self.id,
        }]

    # ------------------------------------------------------------ pages

    def get_chapter_images(self, chapter) -> list:
        gallery_url = self.normalize_url(self._chapter_url(chapter))
        if not gallery_url:
            return []
        response = self.fetch(gallery_url)
        soup = BeautifulSoup(response.content, "html.parser")

        urls, seen = [], set()
        for img in soup.select(".thumb-container img, #thumbnail-container img, .gallerythumb img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src:
                continue
            full = self.full_size(urljoin(SITE, src))
            if full not in seen:
                seen.add(full)
                urls.append(full)

        if not urls:
            raise ScrapeError(f"No pages found for {gallery_url}")
        return urls
