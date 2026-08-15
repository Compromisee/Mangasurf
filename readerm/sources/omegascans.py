"""Omega Scans source, built on its JSON API (api.omegascans.org).

Findings from probing the live API, since none of it is documented:

Endpoints
    ``GET /query``                 search and browse. Useful parameters:
                                   ``query_string``, ``page``, ``perPage``,
                                   ``adult``, ``series_type``, ``order``.
                                   Returns ``{"meta": {...}, "data": [...]}``.
    ``GET /series/{slug}``         full series record. Note that the
                                   ``seasons`` array comes back **empty**
                                   here, so chapters must be fetched
                                   separately -- reading chapters off the
                                   series record silently yields nothing.
    ``GET /chapter/query``         the real chapter list, keyed by
                                   ``series_id`` (the numeric ``id`` from the
                                   series record, *not* the slug).

Paid chapters
    Chapters carry a ``price`` field. A non-zero price means the chapter is
    coin-locked and its images are not served to anonymous clients, so those
    are filtered out rather than "downloading" an empty chapter.

Images
    The reader page embeds the page URLs directly as
    ``https://media.omegascans.org/file/...`` links, so the chapter HTML is
    parsed for them. The CDN hotlinks fine with no Referer (verified).
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import Source, ScrapeError

logger = logging.getLogger(__name__)

SITE = "https://omegascans.org"
API = "https://api.omegascans.org"
MEDIA = "https://media.omegascans.org"


class OmegaScansSource(Source):
    id = "omegascans"
    name = "Omega Scans"
    base_url = SITE
    domains = ("omegascans.org", "api.omegascans.org")

    #: Catalogue is entirely manhwa; used only as a fallback
    #: when a result reports no type of its own.
    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Best Match", "Latest Updates", "Popularity", "Title")
    browse_sorts = ("Trending", "Latest Updates", "Popularity", "Title")

    # `order` values accepted by /query
    _SORTS = {
        "Best Match": "desc",
        "Trending": "desc",
        "Popularity": "desc",
        "Latest Updates": "desc",
        "Title": "asc",
    }

    # The site is a scanlation group with a fixed, small tag set.
    GENRES = (
        "Action", "Adult", "Adventure", "Comedy", "Drama", "Fantasy",
        "Harem", "Historical", "Horror", "Josei", "Mature", "Mystery",
        "Psychological", "Romance", "School Life", "Sci-fi", "Seinen",
        "Shoujo", "Slice of Life", "Supernatural", "Thriller", "Tragedy",
    )

    def headers(self):
        h = super().headers()
        h["Accept"] = "application/json, text/html;q=0.9"
        h["Referer"] = SITE + "/"
        return h

    # ------------------------------------------------------------- slug

    @staticmethod
    def slug_of(url: str) -> str:
        match = re.search(r"/series/([^/?#]+)", url or "")
        if not match:
            raise ScrapeError(f"Not an Omega Scans series URL: {url}")
        return match.group(1)

    # ----------------------------------------------------------- helpers

    def _to_result(self, item):
        slug = item.get("series_slug")
        if not slug:
            return None
        return self._result(
            item.get("title") or "Unknown",
            f"{SITE}/series/{slug}",
            cover=item.get("thumbnail"),
            status=item.get("status"),
            authors=[item.get("author")] if item.get("author") else [],
            description=self._clean(item.get("description")),
            series_id=item.get("id"),
        )

    @staticmethod
    def _clean(html_text):
        if not html_text:
            return None
        text = BeautifulSoup(str(html_text), "html.parser").get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip() or None

    def _query(self, params):
        try:
            data = self.fetch_json(f"{API}/query", params=params)
        except ScrapeError as e:
            logger.error("Omega Scans query failed: %s", e)
            return []
        rows = (data or {}).get("data") or []
        return [r for r in (self._to_result(x) for x in rows) if r]

    # ---------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, sort: str = None,
               genre=None, **_):
        query_str = (query or "").strip()
        if not query_str:
            return self.browse(sort=sort, genre=genre, limit=limit)

        params = {
            "query_string": query_str,
            "search": query_str,
            "q": query_str,
            "page": 1,
            "perPage": max(1, min(100, max(limit, 40))),
            "adult": "true",
            "order": self._SORTS.get(sort or "", "desc"),
        }
        if genre:
            params["tags_ids[]"] = str(genre)
        results = self._query(params)

        if query_str and results:
            results = self.filter_and_rank(results, query_str)

        return results[:limit]

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, **_):
        params = {
            "query_string": "",
            "page": max(1, int(page or 1)),
            "perPage": max(1, min(100, limit)),
            "adult": "true",
            "order": self._SORTS.get(sort or "", "desc"),
        }
        results = self._query(params)
        # the API has no genre filter we can rely on, so narrow client-side
        if genre:
            wanted = str(genre).lower()
            narrowed = [r for r in results
                        if wanted in " ".join(r.get("tags") or []).lower()]
            return narrowed or results
        return results

    def genres(self) -> list:
        return [{"id": name, "name": name} for name in self.GENRES]

    # ------------------------------------------------------------ info

    def get_manga_info(self, manga_url: str) -> dict:
        slug = self.slug_of(self.normalize_url(manga_url))
        data = self.fetch_json(f"{API}/series/{slug}")

        tags = [t.get("name") for t in (data.get("tags") or []) if t.get("name")]
        alt = data.get("alternative_names") or []
        if isinstance(alt, str):
            alt = [a.strip() for a in alt.split(",") if a.strip()]

        return {
            "url": f"{SITE}/series/{slug}",
            "series_id": data.get("id"),
            "title": data.get("title") or "Unknown",
            "alt_titles": alt[:10],
            "cover": data.get("thumbnail"),
            "description": self._clean(data.get("description")),
            "tags": tags,
            "status": data.get("status"),
            "authors": [data.get("author")] if data.get("author") else [],
            "artists": [data.get("studio")] if data.get("studio") else [],
            "year": data.get("release_year"),
            "source": self.id,
            "source_name": self.name,
        }

    # -------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        """Chapters oldest-first, with coin-locked ones removed."""
        slug = self.slug_of(self.normalize_url(manga_url))

        # /series/{slug} returns seasons: [] so the numeric id is fetched
        # first and the dedicated chapter endpoint used instead.
        try:
            series = self.fetch_json(f"{API}/series/{slug}")
        except ScrapeError as e:
            raise ScrapeError(f"Omega Scans: could not load {slug}: {e}")
        series_id = series.get("id")
        if not series_id:
            return []

        chapters, page, locked = [], 1, 0
        while True:
            data = self.fetch_json(f"{API}/chapter/query", params={
                "page": page, "perPage": 100, "series_id": series_id,
            })
            rows = (data or {}).get("data") or []
            if not rows:
                break

            for row in rows:
                chapter_slug = row.get("chapter_slug")
                if not chapter_slug:
                    continue
                try:
                    price = float(row.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0
                if price > 0:
                    locked += 1          # coin-locked: pages are not served
                    continue
                chapters.append({
                    "url": f"{SITE}/series/{slug}/{chapter_slug}",
                    "name": row.get("chapter_name") or chapter_slug,
                    "date": (row.get("created_at") or "")[:10] or None,
                    "referer": f"{SITE}/series/{slug}",
                    "source": self.id,
                })

            meta = (data or {}).get("meta") or {}
            if page >= int(meta.get("last_page") or 1):
                break
            page += 1
            if page > 60:
                break

        if locked:
            logger.info("Omega Scans: skipped %d coin-locked chapter(s)", locked)

        from ..utils import chapter_number
        chapters.sort(key=lambda c: chapter_number(c["name"]))
        return chapters

    # ----------------------------------------------------------- pages

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        if not chapter_url:
            return []
        response = self.fetch(chapter_url)
        html = response.text

        # Page URLs are embedded as plain media links in the reader markup.
        urls, seen = [], set()
        for match in re.finditer(
                r'https://media\.omegascans\.org/file/[A-Za-z0-9/._%-]+'
                r'\.(?:jpg|jpeg|png|webp|gif)', html, re.I):
            url = match.group(0)
            # the series thumbnail also appears on the page
            if "/uploads/series/" not in url and "/uploads/" not in url:
                continue
            if url not in seen:
                seen.add(url)
                urls.append(url)

        if not urls:
            soup = BeautifulSoup(response.content, "html.parser")
            for img in soup.select("img"):
                src = img.get("src") or img.get("data-src") or ""
                if MEDIA in src and src not in seen:
                    seen.add(src)
                    urls.append(urljoin(SITE, src))

        if not urls:
            raise ScrapeError(
                f"No page images found for {chapter_url} "
                "(the chapter may be coin-locked)")
        return urls
