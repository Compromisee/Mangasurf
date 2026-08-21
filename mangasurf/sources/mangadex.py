"""MangaDex source, built on the official JSON API (api.mangadex.org).

Notes gathered from the live API while writing this, because they are all
easy to get wrong:

Covers
    A manga's cover lives in its ``cover_art`` relationship, but that
    relationship only carries a cover *id* by default -- not something you can
    build a URL from. Asking for ``includes[]=cover_art`` (reference
    expansion) inlines the cover attributes so ``fileName`` comes back in the
    same request, which is what we actually need.

    The URL is then:
        https://uploads.mangadex.org/covers/{manga-id}/{fileName}

    Two pre-rendered thumbnails exist, and the *full* filename including its
    original extension must be kept before appending the size suffix:
        {fileName}.256.jpg      small  (grid thumbnails)
        {fileName}.512.jpg      medium (detail view)

    So ``abc.png`` becomes ``abc.png.512.jpg`` -- not ``abc.512.jpg``. Getting
    this wrong 404s, which is the classic "MangaDex covers are broken" bug.
    We store all three sizes so the UI can pick cheaply, and download the
    original for the saved ``cover.jpg``.

    ``GET /cover?manga[]=<id>`` lists every cover, including per-volume art
    and localised editions; :meth:`get_covers` exposes that for volume covers.

Chapters
    ``/manga/{id}/feed`` is paginated at 500 max and caps out at offset 10000,
    so long series need paging. Crucially, some chapters are *external*
    (licensed titles redirect to MangaPlus etc.): they have a non-null
    ``externalUrl`` and ``pages == 0``. Those cannot be downloaded and are
    filtered out, otherwise the engine happily "downloads" zero pages.

    A chapter number can have several scanlation releases. We keep one per
    number (preferring the group the user asked for, else the most complete),
    and expose the rest so a UI could offer a choice.

Pages
    ``/at-home/server/{chapterId}`` returns a short-lived base URL plus the
    page filenames. Build:
        {baseUrl}/data/{hash}/{filename}          original quality
        {baseUrl}/data-saver/{hash}/{filename}    compressed
"""

import logging
import re

from .base import Source, ScrapeError, classify_type, _num_or_none

logger = logging.getLogger(__name__)

API = "https://api.mangadex.org"
UPLOADS = "https://uploads.mangadex.org"
SITE = "https://mangadex.org"

# Every rating, so nothing silently disappears from results. MangaDex
# defaults to safe+suggestive only when the parameter is omitted.
ALL_RATINGS = ["safe", "suggestive", "erotica", "pornographic"]

COVER_SIZES = {"small": ".256.jpg", "medium": ".512.jpg", "original": ""}


class MangaDexSource(Source):
    id = "mangadex"
    name = "MangaDex"
    base_url = SITE
    domains = ("mangadex.org", "api.mangadex.org")

    supports_search = True
    supports_language = True
    supports_scanlator = True
    supports_browse = True
    supports_genres = True
    search_sorts = ("Best Match", "Popularity", "Latest Updates",
                    "Recently Added", "Title", "Rating", "Year")
    browse_sorts = ("Trending", "Popularity", "Latest Updates",
                    "Recently Added", "Rating", "Year")

    # MangaDex sort key -> API order parameter
    _SORTS = {
        # "Trending" is not a real API sort; follow count is the closest
        # proxy the API exposes, and it is what the site's own popular
        # listing is built on.
        "Trending": ("followedCount", "desc"),
        "Best Match": ("relevance", "desc"),
        "Popularity": ("followedCount", "desc"),
        "Latest Updates": ("latestUploadedChapter", "desc"),
        "Recently Added": ("createdAt", "desc"),
        "Title": ("title", "asc"),
        "Rating": ("rating", "desc"),
        "Year": ("year", "desc"),
    }

    languages = ("en", "ja", "es", "es-la", "fr", "de", "it", "pt-br",
                 "ru", "zh", "zh-hk", "ko", "id", "vi", "th", "ar", "pl", "tr")

    def __init__(self, *args, **kwargs):
        # data_saver trades quality for much smaller downloads
        self.data_saver = bool(kwargs.pop("data_saver", False))
        self.scanlator = kwargs.pop("scanlator", None)
        super().__init__(*args, **kwargs)

    def headers(self):
        h = super().headers()
        h["Accept"] = "application/json"
        # MangaDex asks API clients to identify themselves
        from .. import __version__
        h["User-Agent"] = (
            f"ReaderM/{__version__} "
            "(+https://github.com/Compromisee/mangasurf)"
        )
        return h

    # ------------------------------------------------------------- ids

    @staticmethod
    def extract_id(url: str) -> str:
        """Pull the manga UUID out of any MangaDex URL (or accept a raw UUID)."""
        match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            (url or "").lower(),
        )
        if not match:
            raise ScrapeError(f"No MangaDex manga id found in: {url}")
        return match.group(0)

    @classmethod
    def handles(cls, url: str) -> bool:
        if super().handles(url):
            return True
        # bare UUID is treated as MangaDex
        return bool(re.fullmatch(
            r"\s*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\s*",
            (url or "").lower(),
        ))

    # ---------------------------------------------------------- covers

    @staticmethod
    def cover_url(manga_id: str, file_name: str, size: str = "original") -> str:
        """Build a cover URL.

        ``size`` is one of ``small`` (256px), ``medium`` (512px) or
        ``original``. The full filename *with* its original extension is kept
        and the size suffix appended after it, which is what the CDN expects.
        """
        if not manga_id or not file_name:
            return None
        return f"{UPLOADS}/covers/{manga_id}/{file_name}{COVER_SIZES.get(size, '')}"

    @classmethod
    def _covers_from_relationships(cls, manga_id, relationships):
        """Extract every cover size from an expanded ``cover_art`` relationship."""
        for rel in relationships or []:
            if rel.get("type") != "cover_art":
                continue
            file_name = (rel.get("attributes") or {}).get("fileName")
            if file_name:
                return {
                    "cover": cls.cover_url(manga_id, file_name, "original"),
                    "cover_small": cls.cover_url(manga_id, file_name, "small"),
                    "cover_medium": cls.cover_url(manga_id, file_name, "medium"),
                    "cover_file": file_name,
                }
        return {"cover": None, "cover_small": None, "cover_medium": None,
                "cover_file": None}

    def get_covers(self, manga_url: str, limit: int = 100) -> list:
        """Every cover for a manga (volume art and localised editions)."""
        manga_id = self.extract_id(manga_url)
        params = [("manga[]", manga_id), ("limit", min(limit, 100)),
                  ("order[volume]", "asc")]
        try:
            data = self.fetch_json(f"{API}/cover", params=params)
        except ScrapeError:
            return []
        covers = []
        for item in data.get("data", []):
            attrs = item.get("attributes") or {}
            file_name = attrs.get("fileName")
            if not file_name:
                continue
            covers.append({
                "volume": attrs.get("volume"),
                "locale": attrs.get("locale"),
                "description": attrs.get("description") or "",
                "url": self.cover_url(manga_id, file_name, "original"),
                "thumbnail": self.cover_url(manga_id, file_name, "medium"),
            })
        return covers

    # ---------------------------------------------------------- genres

    # Tag ids are stable UUIDs; cached per process after the first call.
    _tag_cache = None

    def genres(self, groups=("genre", "theme", "format")) -> list:
        """Every tag MangaDex offers, usable as ``genre=`` in browse/search."""
        cls = type(self)
        if cls._tag_cache is None:
            try:
                data = self.fetch_json(f"{API}/manga/tag")
            except ScrapeError:
                return []
            tags = []
            for item in data.get("data", []):
                attrs = item.get("attributes") or {}
                name = (attrs.get("name") or {}).get("en")
                if not name:
                    continue
                tags.append({
                    "id": item.get("id"),
                    "name": name,
                    "group": attrs.get("group"),
                })
            tags.sort(key=lambda t: (t["group"] or "", t["name"]))
            cls._tag_cache = tags
        return [t for t in cls._tag_cache
                if not groups or t.get("group") in groups]

    def _tag_id(self, genre: str):
        """Resolve a genre name (or raw UUID) to a tag id."""
        if not genre:
            return None
        genre = genre.strip()
        if re.fullmatch(r"[0-9a-f-]{36}", genre.lower()):
            return genre
        wanted = genre.lower()
        for tag in self.genres(groups=None):
            if tag["name"].lower() == wanted:
                return tag["id"]
        for tag in self.genres(groups=None):
            if wanted in tag["name"].lower():
                return tag["id"]
        return None

    # ---------------------------------------------------------- browse

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 32, status=None, year=None, demographic=None,
               content_rating=None, **_):
        """Discovery listing: trending, popular, latest, or by genre."""
        order_key, order_dir = self._SORTS.get(sort, self._SORTS["Trending"])
        limit = max(1, min(100, limit))
        params = [
            ("limit", limit),
            ("offset", max(0, (int(page) - 1) * limit)),
            ("includes[]", "cover_art"),
            ("includes[]", "author"),
            (f"order[{order_key}]", order_dir),
            # a listing full of empty series is useless
            ("hasAvailableChapters", "true"),
        ]
        for rating in (content_rating or ALL_RATINGS):
            params.append(("contentRating[]", rating))
        if status and status != "Any":
            params.append(("status[]", str(status).lower()))
        if year:
            params.append(("year", str(year)))
        if demographic and demographic != "Any":
            params.append(("publicationDemographic[]", str(demographic).lower()))

        for name in ([genre] if isinstance(genre, str) else (genre or [])):
            tag_id = self._tag_id(name)
            if tag_id:
                params.append(("includedTags[]", tag_id))

        try:
            data = self.fetch_json(f"{API}/manga", params=params)
        except ScrapeError as e:
            logger.error("MangaDex browse failed: %s", e)
            return []
        return [self._to_result(item) for item in data.get("data", [])]

    # ---------------------------------------------------------- search

    @staticmethod
    def _title_of(attrs) -> str:
        """Best-effort readable title: prefer English, then romaji, then any."""
        title = attrs.get("title") or {}
        for key in ("en", "ja-ro", "ja"):
            if title.get(key):
                return title[key]
        if title:
            return next(iter(title.values()))
        for alt in attrs.get("altTitles") or []:
            for key in ("en", "ja-ro"):
                if alt.get(key):
                    return alt[key]
        return "Unknown"

    def search(self, query: str, limit: int = 32, sort: str = "Best Match",
               status=None, content_rating=None, year=None,
               included_tags=None, genre=None, page: int = 1, **_):
        order_key, order_dir = self._SORTS.get(sort, self._SORTS["Best Match"])
        limit_val = max(1, min(100, limit))
        page_val = max(1, int(page or _.get("page", 1) or 1))
        params = [
            ("limit", limit_val),
            ("offset", max(0, (page_val - 1) * limit_val)),
            ("includes[]", "cover_art"),
            ("includes[]", "author"),
            ("includes[]", "artist"),
            (f"order[{order_key}]", order_dir),
        ]
        if query:
            params.append(("title", query))
        for rating in (content_rating or ALL_RATINGS):
            params.append(("contentRating[]", rating))
        if status and status != "Any":
            params.append(("status[]", status.lower()))
        if year:
            params.append(("year", str(year)))
        for tag in included_tags or []:
            resolved = self._tag_id(tag) or tag
            params.append(("includedTags[]", resolved))
        for name in ([genre] if isinstance(genre, str) else (genre or [])):
            tag_id = self._tag_id(name)
            if tag_id:
                params.append(("includedTags[]", tag_id))

        try:
            data = self.fetch_json(f"{API}/manga", params=params)
        except ScrapeError as e:
            logger.error("MangaDex search failed: %s", e)
            return []

        return [self._to_result(item) for item in data.get("data", [])]

    def _to_result(self, item):
        """Convert one API manga object into a search/browse result."""
        manga_id = item.get("id")
        attrs = item.get("attributes") or {}
        covers = self._covers_from_relationships(manga_id, item.get("relationships"))
        authors = [
            (r.get("attributes") or {}).get("name")
            for r in item.get("relationships", [])
            if r.get("type") in ("author", "artist")
            and (r.get("attributes") or {}).get("name")
        ]
        tags = []
        for tag in attrs.get("tags") or []:
            label = ((tag.get("attributes") or {}).get("name") or {}).get("en")
            if label:
                tags.append(label)
        return self._result(
            self._title_of(attrs),
            f"{SITE}/title/{manga_id}",
            cover=covers["cover_medium"],
            cover_small=covers["cover_small"],
            cover_original=covers["cover"],
            manga_id=manga_id,
            status=(attrs.get("status") or "").title() or None,
            year=attrs.get("year"),
            # Origin language is what actually distinguishes manga / manhwa /
            # manhua, and it is the only field every MangaDex entry carries.
            original_language=attrs.get("originalLanguage"),
            series_type=classify_type(attrs.get("originalLanguage"), tags),
            last_chapter=_num_or_none(attrs.get("lastChapter")),
            last_volume=_num_or_none(attrs.get("lastVolume")),
            demographic=attrs.get("publicationDemographic"),
            authors=list(dict.fromkeys(authors)),
            tags=tags,
            content_rating=attrs.get("contentRating"),
            description=self._description(attrs),
        )

    @staticmethod
    def _description(attrs) -> str:
        desc = attrs.get("description") or {}
        if isinstance(desc, dict):
            return desc.get("en") or (next(iter(desc.values()), "") if desc else "")
        return desc or ""

    # ------------------------------------------------------------ info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_id = self.extract_id(manga_url)
        params = [("includes[]", "cover_art"), ("includes[]", "author"),
                  ("includes[]", "artist")]
        data = self.fetch_json(f"{API}/manga/{manga_id}", params=params)
        item = data.get("data") or {}
        attrs = item.get("attributes") or {}
        covers = self._covers_from_relationships(manga_id, item.get("relationships"))

        authors, artists = [], []
        for rel in item.get("relationships", []):
            name = (rel.get("attributes") or {}).get("name")
            if not name:
                continue
            if rel.get("type") == "author":
                authors.append(name)
            elif rel.get("type") == "artist":
                artists.append(name)

        tags = []
        for tag in attrs.get("tags") or []:
            label = ((tag.get("attributes") or {}).get("name") or {}).get("en")
            if label:
                tags.append(label)

        return {
            "url": f"{SITE}/title/{manga_id}",
            "manga_id": manga_id,
            "title": self._title_of(attrs),
            "alt_titles": [
                v for alt in (attrs.get("altTitles") or [])
                for v in alt.values()
            ][:10],
            "cover": covers["cover"],
            "cover_medium": covers["cover_medium"],
            "cover_small": covers["cover_small"],
            "description": self._description(attrs).strip() or None,
            "tags": tags,
            "status": (attrs.get("status") or "").title() or None,
            "year": attrs.get("year"),
            "authors": list(dict.fromkeys(authors)),
            "artists": list(dict.fromkeys(artists)),
            "original_language": attrs.get("originalLanguage"),
            "demographic": attrs.get("publicationDemographic"),
            # Advanced-info fields. lastChapter is only populated once a
            # series is finished -- MangaDex leaves it "" for every ongoing
            # title -- so it is surfaced but never relied on for filtering.
            "series_type": classify_type(attrs.get("originalLanguage"), tags),
            "last_chapter": _num_or_none(attrs.get("lastChapter")),
            "last_volume": _num_or_none(attrs.get("lastVolume")),
            "content_rating": attrs.get("contentRating"),
            "source": self.id,
            "source_name": self.name,
        }

    # -------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        """All downloadable chapters, oldest first, deduplicated by number."""
        manga_id = self.extract_id(manga_url)
        raw, offset, total = [], 0, None
        page_size = 500

        while total is None or offset < total:
            params = [
                ("limit", page_size),
                ("offset", offset),
                ("translatedLanguage[]", self.language),
                ("includes[]", "scanlation_group"),
                ("order[volume]", "asc"),
                ("order[chapter]", "asc"),
                ("includeExternalUrl", "0"),
            ]
            for rating in ALL_RATINGS:
                params.append(("contentRating[]", rating))

            data = self.fetch_json(f"{API}/manga/{manga_id}/feed", params=params)
            batch = data.get("data", [])
            if total is None:
                total = data.get("total", len(batch))
            if not batch:
                break
            raw.extend(batch)
            offset += page_size
            # the feed endpoint refuses offsets beyond 10k
            if offset >= 10000:
                logger.warning("MangaDex: chapter list truncated at 10000 entries")
                break

        chapters = [c for c in (self._parse_chapter(c) for c in raw) if c]
        if not chapters:
            logger.warning(
                "MangaDex: no downloadable '%s' chapters (the title may be "
                "licensed and hosted externally)", self.language,
            )
            return []
        return self._dedupe(chapters)

    def _parse_chapter(self, item):
        """Convert one API chapter object, or None if it is not downloadable."""
        attrs = item.get("attributes") or {}

        # Licensed titles point at MangaPlus/Azuki with zero hosted pages.
        if attrs.get("externalUrl"):
            return None
        if attrs.get("isUnavailable"):
            return None
        pages = attrs.get("pages") or 0
        if pages <= 0:
            return None

        number = attrs.get("chapter")
        volume = attrs.get("volume")
        title = (attrs.get("title") or "").strip()

        if number:
            name = f"Chapter {number}"
        elif attrs.get("volume"):
            name = f"Volume {volume}"
        else:
            name = title or "Oneshot"
        if title and number:
            name = f"{name}: {title}"

        groups = [
            (r.get("attributes") or {}).get("name")
            for r in item.get("relationships", [])
            if r.get("type") == "scanlation_group"
            and (r.get("attributes") or {}).get("name")
        ]

        return {
            "url": item.get("id"),          # chapter UUID; at-home takes this
            "id": item.get("id"),
            "name": name,
            "number": number,
            "volume": volume,
            "title": title or None,
            "pages": pages,
            "language": attrs.get("translatedLanguage"),
            "groups": groups,
            "group": groups[0] if groups else None,
            "date": (attrs.get("publishAt") or "")[:10],
            "source": self.id,
        }

    def _dedupe(self, chapters):
        """Keep one release per chapter number.

        Preference order: the user's requested scanlator, then the release
        with the most pages (usually the most complete), then the earliest.
        Alternatives are kept on the chosen chapter so a UI can offer them.
        """
        wanted = (self.scanlator or "").strip().lower()
        buckets = {}
        for chapter in chapters:
            key = chapter.get("number") or f"__{chapter['name']}"
            buckets.setdefault(key, []).append(chapter)

        chosen = []
        for group in buckets.values():
            if len(group) == 1:
                best = group[0]
            else:
                def score(c):
                    names = [g.lower() for g in c.get("groups") or []]
                    return (
                        1 if wanted and any(wanted in n for n in names) else 0,
                        c.get("pages") or 0,
                    )
                best = max(group, key=score)
                best = dict(best)
                best["alternatives"] = [
                    {"id": c["id"], "group": c.get("group"), "pages": c.get("pages")}
                    for c in group if c["id"] != best["id"]
                ]
            chosen.append(best)

        def sort_key(c):
            try:
                number = float(c.get("number"))
            except (TypeError, ValueError):
                number = float("inf")     # unnumbered extras go last
            try:
                volume = float(c.get("volume"))
            except (TypeError, ValueError):
                volume = float("inf")
            return (number, volume, c.get("date") or "")

        chosen.sort(key=sort_key)
        return chosen

    # ----------------------------------------------------------- pages

    def get_chapter_images(self, chapter) -> list:
        chapter_id = self._chapter_url(chapter)
        if not chapter_id:
            return []
        # strip a full URL down to the UUID if one was passed
        if "/" in chapter_id:
            chapter_id = self.extract_id(chapter_id)

        data = self.fetch_json(f"{API}/at-home/server/{chapter_id}")
        base = (data.get("baseUrl") or "").rstrip("/")
        block = data.get("chapter") or {}
        chapter_hash = block.get("hash")
        if not base or not chapter_hash:
            raise ScrapeError(f"MangaDex returned no image server for {chapter_id}")

        if self.data_saver:
            files, mode = block.get("dataSaver") or [], "data-saver"
            if not files:                       # fall back if saver is missing
                files, mode = block.get("data") or [], "data"
        else:
            files, mode = block.get("data") or [], "data"
            if not files:
                files, mode = block.get("dataSaver") or [], "data-saver"

        return [f"{base}/{mode}/{chapter_hash}/{name}" for name in files]
