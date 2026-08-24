"""Asura Scans source (asuracomic.net) via its public JSON API.

The website itself is useless to a scraper: ``asuracomic.net`` is an Astro
SPA that serves the **identical 617,595-byte document** for ``/``,
``/comics/<slug>``, ``/comics/<slug>/chapter/1`` and ``/browse`` -- verified
by md5, all four hashes equal. Parsing it gets you the homepage every time.

Its backend, ``api.asurascans.com``, is open and unauthenticated. Everything
below was measured 2026-07:

Listing
    ``GET /api/series?limit=<n>&offset=<n>``. **``page`` does not work** --
    ``?page=2``, ``?p=2``, ``?skip=20``, ``?per_page=40`` and ``?perPage=40``
    all returned page one (20 of 20 ids identical). ``offset`` is the only
    parameter that pages: ``?limit=20&offset=20`` shared 0 ids with offset 0.
    ``limit`` works and is honoured (``?limit=40`` returned 40).

    Response is ``{"data": [...], "meta": {"total": 338, "per_page": 20,
    "has_more": true}}``.

Search
    ``&search=<term>`` filters properly (10 results for "solo", total 10).
    ``&name=``, ``&q=`` and ``&title=`` are **decoys**: each returned the full
    338-item catalogue with the ``has_more`` flag set, i.e. they are ignored
    silently -- a search built on them would return "everything" for any word.

Filters
    ``&genres=<slug>`` (316 of 338 for action), ``&status=<ongoing|completed|
    ...>``, ``&type=<manhwa|manhua|manga>``. Genre slugs come from
    ``GET /api/genres`` (33 of them) rather than being guessed.

Series
    ``GET /api/series/<slug>`` -- accepts the bare slug *and* the site's
    public slug with its ``-059befe1`` suffix. That suffix is a constant, not
    a per-series hash: every entry on pages 1 and 5 ended in the same eight
    characters, so it is stripped before use. ``/api/series/<numeric id>``
    404s.

Chapters
    ``GET /api/series/<slug>/chapters`` -> ``{"data": [...]}``, newest first,
    each with ``number``, ``page_count`` and ``is_locked``. Pages come from
    ``GET /api/series/<slug>/chapters/<number>`` -- keyed by the chapter
    *number*, not its id or slug (``/chapters/chapter-1`` 404s,
    ``/chapters/1`` works) -- returning ``data.chapter.pages`` as
    ``[{"url","width","height"}]``.

Images
    ``cdn.asurascans.com``, hotlinks fine (200 image/webp with no Referer).
"""

import logging
import re

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://asuracomic.net"
API = "https://api.asurascans.com/api"

#: Every public_url ends in this constant; it is not a per-series hash.
_PUBLIC_SUFFIX = re.compile(r"-[0-9a-f]{8}$")


class AsuraScansSource(Source):
    id = "asurascans"
    name = "Asura Scans"
    base_url = SITE
    domains = ("asuracomic.net", "asurascans.com", "cdn.asurascans.com")

    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Latest Updates", "Popularity")

    def headers(self):
        h = super().headers()
        h["Accept"] = "application/json"
        return h

    # ---------------------------------------------------------- helpers

    @staticmethod
    def slug_of(url_or_slug: str) -> str:
        """Series slug from a URL, a public slug or a bare slug.

        The public URL is ``/comics/<slug>-059befe1``; that trailing group is
        the same for every series, so it is dropped.
        """
        text = (url_or_slug or "").strip().rstrip("/")
        text = re.sub(r"^https?://[^/]+", "", text)
        text = text.split("?", 1)[0].split("#", 1)[0]
        if "/" in text:
            for part in ("/comics/", "/series/", "/api/series/"):
                if part in text:
                    text = text.split(part, 1)[1]
                    break
            else:
                text = text.rsplit("/", 1)[-1]
        text = text.split("/", 1)[0]
        return _PUBLIC_SUFFIX.sub("", text)

    def series_url(self, slug: str) -> str:
        return f"{SITE}/series/{slug}"

    def _row(self, entry):
        slug = entry.get("slug") or self.slug_of(entry.get("public_url") or "")
        if not slug:
            return None
        genres = entry.get("genres")
        tags = []
        if isinstance(genres, list):
            tags = [g.get("name") for g in genres
                    if isinstance(g, dict) and g.get("name")]
        chapters = entry.get("chapter_count")
        return self._result(
            entry.get("title") or slug,
            self.series_url(slug),
            cover=entry.get("cover") or None,
            status=(entry.get("status") or "").title() or None,
            tags=tags,
            authors=[entry["author"]] if entry.get("author") else [],
            chapters=int(chapters) if str(chapters or "").isdigit() else None,
            series_type=classify_type(text=entry.get("type"))
            or self.default_series_type,
        )

    def _query(self, limit, page, **params):
        page = max(1, int(page or 1))
        limit = max(1, int(limit or 20))
        # offset, not page: every page-shaped parameter is ignored.
        query = {"limit": limit, "offset": (page - 1) * limit}
        query.update({k: v for k, v in params.items() if v})
        try:
            payload = self.fetch_json(f"{API}/series", params=query)
        except ScrapeError as e:
            logger.error("asurascans query failed: %s", e)
            return []
        rows = []
        for entry in payload.get("data") or []:
            row = self._row(entry)
            if row is not None:
                rows.append(row)
        return rows

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **filters):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)
        # &search= is the only parameter that filters; name/q/title are decoys.
        return self._query(limit, page, search=query)

    def browse(self, sort: str = "Latest Updates", genre: str = None,
               page: int = 1, limit: int = 32, status=None, **_):
        params = {}
        if genre:
            params["genres"] = str(genre).strip().lower().replace(" ", "-")
        if status:
            params["status"] = str(status).strip().lower()
        return self._query(limit, page, **params)

    def genres(self) -> list:
        try:
            payload = self.fetch_json(f"{API}/genres", max_retries=2)
        except ScrapeError as e:
            logger.debug("asurascans genres failed: %s", e)
            return []
        return [{"id": g.get("slug"), "name": g.get("name")}
                for g in payload.get("data") or []
                if g.get("slug") and g.get("name")]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        slug = self.slug_of(manga_url)
        payload = self.fetch_json(f"{API}/series/{slug}")
        entry = payload.get("series") or {}

        genres = entry.get("genres")
        tags = []
        if isinstance(genres, list):
            tags = [g.get("name") for g in genres
                    if isinstance(g, dict) and g.get("name")]

        alt = entry.get("alt_titles")
        if not isinstance(alt, list):
            alt = [t.strip() for t in
                   str(entry.get("alternative_titles") or "").split("•")
                   if t.strip()]

        description = entry.get("description") or ""
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip() or None

        return {
            "url": self.series_url(slug),
            "title": entry.get("title") or slug,
            "cover": entry.get("cover") or None,
            "description": description,
            "tags": tags[:20],
            "status": (entry.get("status") or "").title() or None,
            "authors": [entry["author"]] if entry.get("author") else [],
            "artists": [entry["artist"]] if entry.get("artist") else [],
            "alt_titles": [str(t) for t in alt][:8],
            "series_type": classify_type(text=entry.get("type"))
            or self.default_series_type,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        slug = self.slug_of(manga_url)
        payload = self.fetch_json(f"{API}/series/{slug}/chapters")

        chapters = []
        for entry in payload.get("data") or []:
            number = entry.get("number")
            if number is None:
                continue
            # Locked chapters serve no pages to anonymous clients.
            if entry.get("is_locked"):
                continue
            label = str(number)
            if label.endswith(".0"):
                label = label[:-2]
            chapters.append({
                "url": f"{API}/series/{slug}/chapters/{number}",
                "name": f"Chapter {label}",
                "number": number,
                "pages": entry.get("page_count"),
                "referer": self.series_url(slug),
                "source": self.id,
            })

        # The API lists newest first.
        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        url = self._chapter_url(chapter)
        if not url.startswith(API):
            # A reader URL was handed in: /comics/<slug>/chapter/<n>
            match = re.search(r"/chapter/([\d.]+)", url)
            slug = self.slug_of(url)
            if not match or not slug:
                raise ScrapeError(f"Cannot resolve Asura chapter from {url}")
            url = f"{API}/series/{slug}/chapters/{match.group(1)}"

        payload = self.fetch_json(url)
        data = payload.get("data") or {}
        pages = (data.get("chapter") or {}).get("pages") or []

        images = []
        for page in pages:
            src = (page.get("url") or "").strip() if isinstance(page, dict) \
                else str(page or "").strip()
            if src and src not in images:
                images.append(src)
        return images
