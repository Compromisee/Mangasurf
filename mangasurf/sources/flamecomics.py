"""Flame Comics source (flamecomics.xyz) via its Next.js data payload.

The site is server-rendered Next.js, so every page ships a
``<script id="__NEXT_DATA__">`` blob holding the exact JSON the React tree was
built from. That is far more reliable than the DOM: it carries types, tags,
countries, years and page manifests that never appear as markup.

Measured 2026-07:

Catalogue
    ``/browse`` embeds the **entire catalogue in one request** -- 167 series,
    with no pagination at all. ``?page=2`` and ``?search=`` change nothing
    (167 either way), because the browse page filters client-side. So search
    and browse are both served from that single payload, filtered locally.

Series record
    ``series_id``, ``title``, ``altTitles``, ``type`` ("Manhwa"/"Manhua"/…),
    ``country`` ("KR"), ``tags``, ``author``, ``artist``, ``year``,
    ``status``, ``cover`` (a bare filename).

Series page
    ``/series/<id>`` -> ``pageProps.chapters``, each with ``chapter``
    ("8.00"), ``title``, ``token`` and ``edit_time``.

Chapter pages
    ``/series/<id>/<token>`` -> ``pageProps.chapter.images``, which is a
    **dict keyed by stringified index**, not a list -- ``{"0": {...}, "1":
    {...}}`` -- so it has to be sorted numerically or the pages come out in
    dictionary order. Each value holds ``name``, ``width``, ``height``.

    The URL is assembled as
    ``cdn.flamecomics.xyz/uploads/images/series/<id>/<token>/<name>?<edit_time>``.
    Verified against the markup and fetched: 200 image/jpeg. The query string
    is a cache-buster -- the same URL without it also returns 200 -- but it is
    kept so the CDN serves the revision the manifest describes.

Covers
    ``cdn.flamecomics.xyz/uploads/images/series/<id>/<cover>``; hotlinks fine
    with no Referer.
"""

import json
import logging
import re

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)

SITE = "https://flamecomics.xyz"
CDN = "https://cdn.flamecomics.xyz/uploads/images/series"

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


class FlameComicsSource(Source):
    id = "flamecomics"
    name = "Flame Comics"
    base_url = SITE
    domains = ("flamecomics.xyz", "cdn.flamecomics.xyz")

    default_series_type = "Manhwa"

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Popularity", "Latest Updates", "Title")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._catalogue = None

    # ---------------------------------------------------------- helpers

    @staticmethod
    def parse_next_data(html):
        """Return ``props.pageProps`` from a Next.js document, or ``{}``."""
        match = _NEXT_DATA.search(html or "")
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except (TypeError, ValueError):
            logger.debug("flamecomics: unparsable __NEXT_DATA__")
            return {}
        return (payload.get("props") or {}).get("pageProps") or {}

    def _load_catalogue(self):
        """The whole catalogue, from the single /browse payload."""
        if self._catalogue is not None:
            return self._catalogue
        try:
            response = self.fetch(f"{SITE}/browse")
        except ScrapeError as e:
            logger.error("flamecomics catalogue failed: %s", e)
            self._catalogue = []
            return self._catalogue

        props = self.parse_next_data(response.text)
        self._catalogue = list(props.get("series") or [])
        return self._catalogue

    @staticmethod
    def _as_list(value):
        if isinstance(value, list):
            return [str(v) for v in value if v]
        if value:
            return [str(value)]
        return []

    def _row(self, entry):
        series_id = entry.get("series_id")
        if series_id is None:
            return None
        cover = entry.get("cover")
        tags = self._as_list(entry.get("tags") or entry.get("categories"))
        return self._result(
            entry.get("title") or f"Series {series_id}",
            f"{SITE}/series/{series_id}",
            cover=f"{CDN}/{series_id}/{cover}" if cover else None,
            status=(entry.get("status") or None),
            tags=tags,
            year=entry.get("year"),
            authors=self._as_list(entry.get("author")),
            series_type=classify_type(text=entry.get("type"), tags=tags)
            or self.default_series_type,
        )

    @staticmethod
    def series_id_of(url_or_id) -> str:
        text = str(url_or_id or "").strip().rstrip("/")
        match = re.search(r"/series/(\d+)", text)
        if match:
            return match.group(1)
        return text.rsplit("/", 1)[-1]

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        rows = self._load_catalogue()
        query = (query or "").strip().lower()
        if query:
            def matches(entry):
                haystack = [str(entry.get("title") or "")]
                haystack += self._as_list(entry.get("altTitles"))
                return any(query in text.lower() for text in haystack)
            rows = [r for r in rows if matches(r)]

        page = max(1, int(page or 1))
        start = (page - 1) * limit
        return [row for row in
                (self._row(r) for r in rows[start:start + limit])
                if row is not None]

    def browse(self, sort: str = "Popularity", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        rows = list(self._load_catalogue())

        if genre:
            wanted = str(genre).strip().lower()
            rows = [r for r in rows
                    if any(wanted == t.strip().lower()
                           for t in self._as_list(r.get("tags")
                                                  or r.get("categories")))]

        label = (sort or "").lower()
        if label == "title":
            rows.sort(key=lambda r: str(r.get("title") or "").lower())
        elif label in ("popularity", "trending"):
            rows.sort(key=lambda r: self._rank(r))
        elif label == "latest updates":
            rows.sort(key=lambda r: -int(r.get("last_edit") or r.get("time") or 0))

        page = max(1, int(page or 1))
        start = (page - 1) * limit
        return [row for row in
                (self._row(r) for r in rows[start:start + limit])
                if row is not None]

    @staticmethod
    def _rank(entry):
        try:
            return int(entry.get("popularityRank"))
        except (TypeError, ValueError):
            return 10 ** 6

    def genres(self) -> list:
        names = {}
        for entry in self._load_catalogue():
            for tag in self._as_list(entry.get("tags") or entry.get("categories")):
                names.setdefault(tag.strip().lower(), tag.strip())
        return [{"id": name, "name": name}
                for _key, name in sorted(names.items())]

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        series_id = self.series_id_of(manga_url)
        response = self.fetch(f"{SITE}/series/{series_id}")
        props = self.parse_next_data(response.text)
        entry = props.get("series") or {}

        description = re.sub(r"<[^>]+>", " ", entry.get("description") or "")
        description = re.sub(r"\s+", " ", description).strip() or None
        tags = self._as_list(entry.get("tags") or entry.get("categories"))
        cover = entry.get("cover")

        return {
            "url": f"{SITE}/series/{series_id}",
            "title": entry.get("title") or f"Series {series_id}",
            "cover": f"{CDN}/{series_id}/{cover}" if cover else None,
            "description": description,
            "tags": tags[:20],
            "status": entry.get("status"),
            "year": entry.get("year"),
            "authors": self._as_list(entry.get("author")),
            "artists": self._as_list(entry.get("artist")),
            "alt_titles": self._as_list(entry.get("altTitles"))[:8],
            "series_type": classify_type(text=entry.get("type"), tags=tags)
            or self.default_series_type,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        series_id = self.series_id_of(manga_url)
        response = self.fetch(f"{SITE}/series/{series_id}")
        props = self.parse_next_data(response.text)

        chapters = []
        for entry in props.get("chapters") or []:
            token = entry.get("token")
            if not token:
                continue
            number = str(entry.get("chapter") or "").rstrip("0").rstrip(".")
            name = f"Chapter {number or entry.get('chapter')}"
            if entry.get("title"):
                name = f"{name}: {entry['title']}"
            chapters.append({
                "url": f"{SITE}/series/{series_id}/{token}",
                "name": name,
                "number": entry.get("chapter"),
                "referer": f"{SITE}/series/{series_id}",
                "source": self.id,
            })

        chapters.reverse()
        return chapters

    # ----------------------------------------------------------- images

    @classmethod
    def build_pages(cls, chapter):
        """Assemble page URLs from a chapter payload.

        ``images`` is a dict keyed by stringified index, so it must be sorted
        numerically -- iterating it directly gives dictionary order.
        """
        images = chapter.get("images") or {}
        series_id = chapter.get("series_id")
        token = chapter.get("token")
        stamp = chapter.get("edit_time") or ""

        if isinstance(images, dict):
            items = sorted(images.items(),
                           key=lambda kv: cls._page_index(kv[0]))
            entries = [value for _key, value in items]
        else:
            entries = list(images)

        pages = []
        for entry in entries:
            name = entry.get("name") if isinstance(entry, dict) else entry
            if not name:
                continue
            url = f"{CDN}/{series_id}/{token}/{name}"
            if stamp:
                url = f"{url}?{stamp}"
            if url not in pages:
                pages.append(url)
        return pages

    @staticmethod
    def _page_index(key):
        try:
            return int(key)
        except (TypeError, ValueError):
            return 10 ** 6

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)
        props = self.parse_next_data(response.text)
        payload = props.get("chapter") or {}
        if not payload:
            return []
        return self.build_pages(payload)
