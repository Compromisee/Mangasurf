"""Source registry: every supported manga site in Mangasurf.

Adding a new site is a three-step job:
    1. write ``mangasurf/sources/<name>.py`` with a Source subclass
    2. import it below and append it to ``SOURCE_CLASSES``
    3. that's it -- CLI, GUI, and API pick it up automatically
"""

import logging
import re

from .asurascans import AsuraScansSource
from .base import BASE_HEADERS, DEFAULT_UA, ScrapeError, Source
from .comix import ComixSource
from .demonicscans import DemonicScansSource
from .flamecomics import FlameComicsSource
from .hentaiakane import HentaiAkaneSource
from .hitomi import HitomiSource
from .kagane import KaganeSource
from .madaranet import MadaraNetSource
from .madarascans import MadaraScansSource
from .manga18club import Manga18ClubSource
from .mangadass import MangadassSource
from .mangadex import MangaDexSource
from .mangadistrict import MangaDistrictSource
from .mangadotnet import MangaDotNetSource
from .mangakatana import MangakatanaSource
from .manhwa18 import Manhwa18Source
from .manhwaread import ManhwaReadSource
from .natomanga import NatomangaSource
from .nhentai import NhentaiSource
from .omegascans import OmegaScansSource
from .simplyhentai import SimplyHentaiSource
from .vymanga import VymangaSource
from .webtoons import WebtoonsSource
from .weebcentral import WeebCentralSource
from .witchscans import WitchScansSource, WitchtoonsSource
from .writerscans import WriterScansSource
from .chikari import ChikariSource
from .kuramanga import KuraMangaSource
from .kurahentai import KuraHentaiSource
from .hiperdex import HiperdexSource
from .madaradex import MadaraDexSource
from .mangak import MangaKSource

logger = logging.getLogger(__name__)

SOURCE_CLASSES = [
    MangaDexSource,
    MangakatanaSource,
    WeebCentralSource,
    KaganeSource,
    ComixSource,
    VymangaSource,
    MangaDotNetSource,
    MangaDistrictSource,
    HitomiSource,
    SimplyHentaiSource,
    NatomangaSource,
    AsuraScansSource,
    FlameComicsSource,
    DemonicScansSource,
    MadaraScansSource,
    OmegaScansSource,
    ManhwaReadSource,
    MadaraNetSource,
    WitchScansSource,
    WriterScansSource,
    WebtoonsSource,
    MangadassSource,
    Manhwa18Source,
    Manga18ClubSource,
    HentaiAkaneSource,
    NhentaiSource,
    ChikariSource,
    KuraMangaSource,
    KuraHentaiSource,
    HiperdexSource,
    MadaraDexSource,
    MangaKSource,
]

SOURCES = {cls.id: cls for cls in SOURCE_CLASSES}

DEFAULT_SOURCE = MangaDexSource.id

__all__ = [
    "BASE_HEADERS", "DEFAULT_SOURCE", "DEFAULT_UA", "SOURCES", "SOURCE_CLASSES",
    "ScrapeError", "Source", "MangaDexSource", "MangakatanaSource",
    "WeebCentralSource", "KaganeSource", "ComixSource", "VymangaSource",
    "MangaDotNetSource", "MangaDistrictSource", "HitomiSource", "SimplyHentaiSource",
    "NatomangaSource", "OmegaScansSource", "ManhwaReadSource", "Manhwa18Source",
    "WebtoonsSource", "MangadassSource", "Manga18ClubSource", "HentaiAkaneSource",
    "NhentaiSource", "AsuraScansSource", "FlameComicsSource",
    "DemonicScansSource", "MadaraScansSource", "MadaraNetSource",
    "WitchScansSource", "WriterScansSource",
    "get_source", "source_for_url", "detect_source", "list_sources",
    "search_all", "browse_all", "browse_multi", "genres_all",
    "split_genres",
]


def list_sources() -> list:
    return [
        {
            "id": cls.id,
            "name": cls.name,
            "base_url": cls.base_url,
            "domains": list(cls.domains),
            "supports_search": cls.supports_search,
            "supports_browse": cls.supports_browse,
            "supports_genres": cls.supports_genres,
            "browse_sorts": list(cls.browse_sorts),
            "supports_language": cls.supports_language,
            "supports_scanlator": cls.supports_scanlator,
            "needs_flaresolverr": cls.needs_flaresolverr,
            "adult_only": getattr(cls, "adult_only", False),
            "cover_needs_referer": getattr(cls, "cover_needs_referer", False),
            "sorts": list(cls.search_sorts),
            "languages": list(cls.languages),
        }
        for cls in SOURCE_CLASSES
    ]


def detect_source(url: str) -> str:
    if not url:
        return None
    url = url.strip().lower()
    for cls in SOURCE_CLASSES:
        if cls.handles(url):
            return cls.id
    return None


AGGREGATE_PREFIXES = {"madara": "madaranet"}


def resolve_member(source_id: str, **kwargs):
    if not source_id or "." not in source_id:
        return None
    prefix = source_id.split(".", 1)[0]
    parent_id = AGGREGATE_PREFIXES.get(prefix, prefix)
    parent_cls = SOURCES.get(parent_id)
    if parent_cls is None or not callable(getattr(parent_cls, "member", None)):
        return None
    aggregate = parent_cls(**kwargs)
    member = aggregate.member(source_id)
    if member is None:
        aggregate.close()
        return None
    return member


def get_source(source_id: str = None, **kwargs) -> Source:
    key = (source_id or DEFAULT_SOURCE).strip().lower()
    cls = SOURCES.get(key)
    if cls is None:
        member = resolve_member(key, **kwargs)
        if member is not None:
            return member
        known = ", ".join(SOURCES)
        raise ScrapeError(f"Unknown source '{source_id}'. Available: {known}")
    return cls(**kwargs)


def source_for_url(url: str, **kwargs) -> Source:
    source_id = detect_source(url)
    if source_id is None:
        known = ", ".join(cls.base_url for cls in SOURCE_CLASSES)
        raise ScrapeError(
            f"No source recognises '{url}'.\nSupported sites: {known}"
        )
    return get_source(source_id, **kwargs)


SEARCH_WORKERS = 14


def search_all(query: str, source_ids=None, limit: int = 20,
               workers: int = SEARCH_WORKERS, use_config: bool = True,
               interleave: bool = False, **filters) -> list:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import concurrent.futures

    ranks, limits = {}, {}
    if source_ids:
        ids = [s for s in source_ids if s in SOURCES]
    elif use_config:
        try:
            from ..config import load_config, search_ids
            ids = search_ids()
            entries = load_config().get("sources", {})
            ranks = {sid: entries[sid].get("rank", 100) for sid in ids if sid in entries}
            limits = {sid: int(entries[sid].get("limit", 0) or 0) for sid in ids if sid in entries}
        except Exception:
            ids = list(SOURCES)
    else:
        ids = list(SOURCES)

    if not ids:
        return []
    if not ranks:
        ranks = {sid: i for i, sid in enumerate(ids)}

    buckets = {}

    from ..robust import SOURCE_BREAKER

    def run(source_id):
        def fetch():
            source = get_source(source_id)
            try:
                return source.search(query, limit=limits.get(source_id) or limit,
                                     **filters)
            finally:
                source.close()

        return SOURCE_BREAKER.call(source_id, fetch)

    try:
        from ..config import load_settings
        search_timeout = float(load_settings().get("search_timeout") or 30.0)
    except Exception:
        search_timeout = 30.0

    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(ids))))
    try:
        futures = {pool.submit(run, sid): sid for sid in ids}
        done, pending = concurrent.futures.wait(futures, timeout=search_timeout)
        for future in done:
            source_id = futures[future]
            try:
                buckets[source_id] = future.result() or []
            except Exception as e:
                logger.warning("Search failed on %s: %s", source_id, e)
                buckets[source_id] = []

        for future in pending:
            source_id = futures[future]
            logger.debug("Search timed out on %s after %.1fs", source_id, search_timeout)
            buckets[source_id] = []
    finally:
        pool.shutdown(wait=False)

    ordered_ids = sorted(buckets, key=lambda sid: ranks.get(sid, 100))

    if interleave:
        merged, index = [], 0
        while True:
            added = False
            for source_id in ordered_ids:
                items = buckets[source_id]
                if index < len(items):
                    merged.append(items[index])
                    added = True
            if not added:
                break
            index += 1
        return merged

    merged = []
    for source_id in ordered_ids:
        merged.extend(buckets[source_id])

    if query and merged:
        from .base import filter_and_rank_query
        merged = filter_and_rank_query(merged, query)

    return merged


def _enabled_ids(source_ids=None, use_config=True):
    if source_ids:
        return [s for s in source_ids if s in SOURCES], {}
    if use_config:
        try:
            from ..config import load_config, search_ids
            ids = search_ids()
            entries = load_config().get("sources", {})
            return ids, {sid: entries[sid].get("rank", 100) for sid in ids if sid in entries}
        except Exception:
            pass
    return list(SOURCES), {}


def browse_all(sort: str = "Trending", genre: str = None, page: int = 1,
               limit: int = 12, workers: int = SEARCH_WORKERS,
               source_ids=None, use_config: bool = True,
               interleave: bool = True, use_cache: bool = True,
               **filters) -> list:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import concurrent.futures

    ids, ranks = _enabled_ids(source_ids, use_config)
    ids = [sid for sid in ids if SOURCES[sid].supports_browse]
    if not ids:
        return []

    buckets = {}

    from ..robust import BROWSE_CACHE, SOURCE_BREAKER, cache_key

    def run(source_id):
        key = cache_key("browse", source_id, sort or "", genre or "",
                        page, limit,
                        sorted(filters.items()))
        if use_cache:
            cached = BROWSE_CACHE.get(key)
            if cached is not None:
                return cached

        def fetch():
            source = get_source(source_id)
            try:
                return source.browse(sort=sort, genre=genre, page=page,
                                     limit=limit, **filters)
            finally:
                source.close()

        rows = SOURCE_BREAKER.call(source_id, fetch) or []
        if use_cache and rows:
            BROWSE_CACHE.set(key, rows)
        return rows

    pool = ThreadPoolExecutor(max_workers=max(1, min(workers, len(ids))))
    try:
        futures = {pool.submit(run, sid): sid for sid in ids}
        done, pending = concurrent.futures.wait(futures, timeout=12.0)
        for future in done:
            source_id = futures[future]
            try:
                buckets[source_id] = future.result() or []
            except Exception as e:
                logger.warning("Browse failed on %s: %s", source_id, e)
                buckets[source_id] = []

        for future in pending:
            source_id = futures[future]
            buckets[source_id] = []
    finally:
        pool.shutdown(wait=False)

    ordered = sorted(buckets, key=lambda sid: ranks.get(sid, 100))
    if not interleave:
        merged = []
        for source_id in ordered:
            merged.extend(buckets[source_id])
        return merged

    merged, index = [], 0
    while True:
        added = False
        for source_id in ordered:
            items = buckets[source_id]
            if index < len(items):
                merged.append(items[index])
                added = True
        if not added:
            break
        index += 1
    return merged


def _result_identity(item):
    url = (item.get("url") or "").strip().lower().rstrip("/")
    if url:
        return url
    return re.sub(r"\s+", " ", (item.get("title") or "").strip().lower())


def split_genres(genre):
    if genre is None:
        return []
    if isinstance(genre, (list, tuple, set)):
        values = list(genre)
    else:
        values = re.split(r"[,|]", str(genre))
    out = []
    for value in values:
        value = str(value or "").strip()
        if value and value.lower() not in {v.lower() for v in out}:
            out.append(value)
    return out


def browse_multi(genres, sort="Trending", page=1, limit=12, match="all",
                 source_ids=None, use_config=True, interleave=True,
                 **filters) -> list:
    wanted = split_genres(genres)
    if not wanted:
        return browse_all(sort=sort, genre=None, page=page, limit=limit,
                          source_ids=source_ids, use_config=use_config,
                          interleave=interleave, **filters)
    if len(wanted) == 1:
        return browse_all(sort=sort, genre=wanted[0], page=page, limit=limit,
                          source_ids=source_ids, use_config=use_config,
                          interleave=interleave, **filters)

    per_genre = []
    for name in wanted:
        rows = browse_all(sort=sort, genre=name, page=page,
                          limit=max(limit, 40), source_ids=source_ids,
                          use_config=use_config, interleave=False, **filters)
        per_genre.append(rows)

    by_source = {}
    for index, rows in enumerate(per_genre):
        for row in rows:
            bucket = by_source.setdefault(row.get("source", ""), {})
            entry = bucket.setdefault(_result_identity(row),
                                      {"row": row, "hits": set()})
            entry["hits"].add(index)

    need = len(wanted) if str(match).lower() != "any" else 1
    kept = []
    for bucket in by_source.values():
        for entry in bucket.values():
            if len(entry["hits"]) >= need:
                row = dict(entry["row"])
                row["matched_genres"] = [wanted[i] for i in sorted(entry["hits"])]
                kept.append(row)

    if interleave:
        kept = _interleave_by_source(kept)
    return kept[:limit] if limit else kept


def _interleave_by_source(rows):
    buckets = {}
    for row in rows:
        buckets.setdefault(row.get("source", ""), []).append(row)
    out = []
    while any(buckets.values()):
        for key in list(buckets):
            if buckets[key]:
                out.append(buckets[key].pop(0))
    return out


GENRES_DEADLINE = 6.0


def genres_all(source_ids=None, use_config=True, workers=8,
               deadline=GENRES_DEADLINE) -> list:
    import concurrent.futures

    ids, _ranks = _enabled_ids(source_ids, use_config)
    ids = [sid for sid in ids if SOURCES[sid].supports_genres]

    from ..robust import GENRE_CACHE, cache_key

    key = cache_key("genres", *sorted(ids))
    cached = GENRE_CACHE.get(key)
    if cached is not None:
        return cached

    def fetch(source_id):
        source = get_source(source_id)
        try:
            return source_id, list(source.genres() or [])
        finally:
            source.close()

    results, complete = [], True
    if ids:
        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(workers, len(ids))))
        try:
            futures = {pool.submit(fetch, sid): sid for sid in ids}
            done, pending = concurrent.futures.wait(
                futures, timeout=deadline)
            for future in done:
                source_id = futures[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.warning("Genre listing failed on %s: %s",
                                   source_id, e)
                    complete = False
            for future in pending:
                source_id = futures[future]
                complete = False
                results.append((source_id, _offline_genres(source_id)))
        finally:
            pool.shutdown(wait=False)

    merged = {}
    for source_id, genres in results:
        for genre in genres or []:
            name = (genre.get("name") or "").strip()
            if not name:
                continue
            entry = merged.setdefault(name.lower(),
                                      {"name": name, "sources": {}})
            entry["sources"][source_id] = genre.get("id", name)

    rows = list(merged.values())
    rows.sort(key=lambda row: (-len(row["sources"]), row["name"].lower()))
    if complete:
        GENRE_CACHE.set(key, rows)
    return rows


def _offline_genres(source_id):
    cls = SOURCES.get(source_id)
    if cls is None:
        return []
    try:
        offline = getattr(cls, "offline_genres", None)
        if callable(offline):
            return list(offline() or [])
        slugs = getattr(cls, "GENRES", ())
        if hasattr(cls, "_genre_label"):
            return [{"id": slug, "name": cls._genre_label(slug)}
                    for slug in slugs]
        return [{"id": g, "name": g} for g in slugs]
    except Exception:
        return []
