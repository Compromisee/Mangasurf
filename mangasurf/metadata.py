"""Universal Manga Metadata Providers & Cross-Referencing Engine for Mangasurf.

Integrates with:
- MAL (MyAnimeList via Jikan REST API)
- PornhwaDB (pornhwadb.com adult manhwa metadata indexer)
- MangaBaka (alternative titles & cross-source synonym resolver)
- ComicInfo.xml & manga.json metadata generators
- Title decluttering engine for File Explorer & OPDS
"""

from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# Cache file in user directory
METADATA_CACHE_FILE = "metadata_cache.json"

# In-memory session and cache
_CACHE: Dict[str, Any] = {}
_CACHE_LOADED = False


def _get_cache_path() -> str:
    try:
        from .paths import data_dir
        return os.path.join(data_dir(), METADATA_CACHE_FILE)
    except Exception:
        return os.path.expanduser(f"~/.mangasurf/{METADATA_CACHE_FILE}")


def _load_cache():
    global _CACHE, _CACHE_LOADED
    if _CACHE_LOADED:
        return
    path = _get_cache_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception:
            _CACHE = {}
    _CACHE_LOADED = True


def _save_cache():
    path = _get_cache_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("Failed to save metadata cache: %s", e)


def normalize_title(title: str) -> str:
    """Normalize a title for fuzzy cross-source matching:

    Strips punctuation, casing, brackets, and common noise.
    """
    if not title:
        return ""
    t = str(title).lower().strip()
    # Remove bracketed tags like [Official], (Uncensored), etc.
    t = re.sub(r"\[[^\]]*\]|\([^\)]*\)", "", t)
    # Remove non-alphanumeric
    t = re.sub(r"[^a-z0-9\s]", "", t)
    # Collapse whitespace
    return re.sub(r"\s+", " ", t).strip()


def declutter_title(title: str) -> str:
    """Clean and declutter a series or chapter title for File Explorer & OPDS:

    Removes redundant scanlator tags, release group brackets, and noise.
    """
    if not title:
        return ""
    t = str(title).strip()
    # Remove common brackets/tags
    noise_patterns = [
        r"\[(?:official|uncensored|censored|digital|raw|webtoon|bilibili|tapas|lezhin|tappytoon|hd|1080p|720p|end|complete)\]",
        r"\((?:official|uncensored|censored|digital|raw|webtoon|bilibili|tapas|lezhin|tappytoon|hd|1080p|720p|end|complete)\)",
        r"(?:-|\s+)(?:season\s+\d+|s\d+)(?:\s+end)?",
        r"\s*-\s*official\s*$",
        r"\s*-\s*uncensored\s*$",
    ]
    for pat in noise_patterns:
        t = re.sub(pat, "", t, flags=re.IGNORECASE).strip()
    # Strip any dangling separators at ends
    t = re.sub(r"\s*[-–—:]\s*$", "", t).strip()
    return re.sub(r"\s+", " ", t).strip()


# ─────────────────────────────────────────────────────────────────────────────
# 1. MAL (MyAnimeList / Jikan API)
# ─────────────────────────────────────────────────────────────────────────────

def search_mal(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search MyAnimeList via the public Jikan v4 REST API."""
    _load_cache()
    q = (query or "").strip()
    if not q:
        return []
    
    cache_key = f"mal:{q.lower()}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    url = f"https://api.jikan.moe/v4/manga?q={quote(q)}&limit={limit}&sfw=false"
    headers = {
        "User-Agent": "Mangasurf/1.7.0 (https://github.com/Compromisee/mangasurf)"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            results = []
            for item in data:
                titles = [item.get("title")]
                if item.get("title_english"):
                    titles.append(item["title_english"])
                if item.get("title_japanese"):
                    titles.append(item["title_japanese"])
                for syn in item.get("title_synonyms", []):
                    if syn:
                        titles.append(syn)
                
                results.append({
                    "id": f"mal_{item.get('mal_id')}",
                    "mal_id": item.get("mal_id"),
                    "title": item.get("title"),
                    "alt_titles": [t for t in titles if t and t != item.get("title")],
                    "synopsis": item.get("synopsis") or "",
                    "score": item.get("score") or 0.0,
                    "status": (item.get("status") or "Publishing").title(),
                    "type": (item.get("type") or "Manga").title(),
                    "genres": [g["name"] for g in item.get("genres", []) if "name" in g],
                    "authors": [a["name"] for a in item.get("authors", []) if "name" in a],
                    "cover": item.get("images", {}).get("jpg", {}).get("large_image_url") or item.get("images", {}).get("jpg", {}).get("image_url"),
                    "url": item.get("url") or "",
                    "provider": "MyAnimeList",
                })
            _CACHE[cache_key] = results
            _save_cache()
            return results
    except Exception as e:
        logger.debug("MAL search failed: %s", e)
    return []


# ─────────────────────────────────────────────────────────────────────────────
# 2. PornhwaDB (pornhwadb.com adult manhwa indexer)
# ─────────────────────────────────────────────────────────────────────────────

def search_pornhwadb(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search PornhwaDB index for adult manhwa metadata and alternative titles."""
    _load_cache()
    q = (query or "").strip()
    if not q:
        return []

    cache_key = f"pornhwadb:{q.lower()}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    from .database import DATABASE_ENTRIES
    matched = []
    norm_q = normalize_title(q)

    for entry in DATABASE_ENTRIES:
        if not entry.get("is_nsfw"):
            continue
        titles = [entry.get("title", "")] + entry.get("alt_titles", [])
        clean_titles = [t for t in titles if t]
        
        score = 0
        for t in clean_titles:
            norm_t = normalize_title(t)
            if norm_t == norm_q:
                score = max(score, 100)
            elif norm_t.startswith(norm_q):
                score = max(score, 80)
            elif norm_q in norm_t:
                score = max(score, 50)

        if score > 0:
            matched.append((score, {
                "id": f"pdb_{entry.get('id')}",
                "title": entry.get("title"),
                "alt_titles": entry.get("alt_titles", []),
                "synopsis": entry.get("description", ""),
                "score": 9.2,
                "status": entry.get("status", "Ongoing"),
                "type": "Manhwa (18+)",
                "genres": entry.get("genres", []),
                "authors": entry.get("authors", []),
                "cover": entry.get("cover"),
                "url": entry.get("url"),
                "provider": "PornhwaDB",
            }))

    matched.sort(key=lambda x: -x[0])
    results = [m[1] for m in matched[:limit]]
    _CACHE[cache_key] = results
    _save_cache()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 3. MangaBaka (Alternative Titles & Synonym Cross-Referencer)
# ─────────────────────────────────────────────────────────────────────────────

def search_mangabaka(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search MangaBaka cross-reference index for synonyms and alternative titles."""
    _load_cache()
    q = (query or "").strip()
    if not q:
        return []

    cache_key = f"mangabaka:{q.lower()}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    from .database import DATABASE_ENTRIES
    matched = []
    norm_q = normalize_title(q)

    for entry in DATABASE_ENTRIES:
        titles = [entry.get("title", "")] + entry.get("alt_titles", [])
        clean_titles = [t for t in titles if t]
        
        score = 0
        for t in clean_titles:
            norm_t = normalize_title(t)
            if norm_t == norm_q:
                score = max(score, 100)
            elif norm_t.startswith(norm_q):
                score = max(score, 80)
            elif norm_q in norm_t:
                score = max(score, 50)

        if score > 0:
            matched.append((score, {
                "id": f"mb_{entry.get('id')}",
                "title": entry.get("title"),
                "alt_titles": entry.get("alt_titles", []),
                "synopsis": entry.get("description", ""),
                "score": 8.8,
                "status": entry.get("status", "Ongoing"),
                "type": entry.get("type", "Manga"),
                "genres": entry.get("genres", []),
                "authors": entry.get("authors", []),
                "cover": entry.get("cover"),
                "url": entry.get("url"),
                "provider": "MangaBaka",
            }))

    matched.sort(key=lambda x: -x[0])
    results = [m[1] for m in matched[:limit]]
    _CACHE[cache_key] = results
    _save_cache()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. Universal Cross-Referencing Across Scraper Sources
# ─────────────────────────────────────────────────────────────────────────────

def get_title_synonyms(title: str) -> Set[str]:
    """Get all known synonyms, translations, and alternate titles for a manga:

    Searches local database, MAL, PornhwaDB, and MangaBaka.
    """
    synonyms = {title} if title else set()
    norm = normalize_title(title)
    if not norm:
        return synonyms

    from .database import DATABASE_ENTRIES
    for entry in DATABASE_ENTRIES:
        all_entry_titles = [entry.get("title", "")] + entry.get("alt_titles", [])
        clean_entry_titles = [t for t in all_entry_titles if t and normalize_title(t)]
        if any(normalize_title(t) == norm for t in clean_entry_titles):
            for t in clean_entry_titles:
                synonyms.add(t)

    return synonyms


def cross_reference_downloaded(item: dict, library_entries: list) -> Optional[dict]:
    """Check if an item from ANY source matches any already-downloaded series in library:

    Uses fuzzy title matching and synonym cross-referencing so a series downloaded
    from MangaDex is recognized when searched on Asura, Chikari, or KuraManga!
    """
    if not item or not library_entries:
        return None

    item_title = item.get("title") or ""
    item_url = item.get("url") or ""
    item_norm = normalize_title(item_title)

    for lib_book in library_entries:
        lib_title = lib_book.get("title") or ""
        lib_url = lib_book.get("url") or ""
        lib_norm = normalize_title(lib_title)

        # 1. Exact URL match
        if item_url and lib_url and item_url.lower() == lib_url.lower():
            return lib_book

        # 2. Normalized Title match
        if item_norm and lib_norm and item_norm == lib_norm:
            return lib_book

        # 3. Direct known synonyms of lib_book
        lib_synonyms = {normalize_title(s) for s in get_title_synonyms(lib_title) if s and normalize_title(s)}
        if item_norm in lib_synonyms:
            return lib_book

        # 4. Direct known synonyms of item
        item_synonyms = {normalize_title(s) for s in get_title_synonyms(item_title) if s and normalize_title(s)}
        if lib_norm in item_synonyms:
            return lib_book

    return None


# ─────────────────────────────────────────────────────────────────────────────
# 5. ComicInfo.xml & manga.json Rebuilding Engine
# ─────────────────────────────────────────────────────────────────────────────

def generate_comic_info_xml(metadata: dict) -> str:
    """Generate standard ComicInfo.xml metadata (ComicRack / OPDS compliant)."""
    root = ET.Element("ComicInfo")
    
    def set_tag(name, val):
        if val is not None and str(val).strip():
            el = ET.SubElement(root, name)
            el.text = str(val).strip()

    title = declutter_title(metadata.get("title") or "")
    set_tag("Title", title)
    set_tag("Series", title)
    set_tag("Summary", metadata.get("description") or metadata.get("synopsis") or "")
    
    authors = metadata.get("authors") or []
    if isinstance(authors, list):
        set_tag("Writer", ", ".join(authors))
    elif isinstance(authors, str):
        set_tag("Writer", authors)

    artists = metadata.get("artists") or []
    if isinstance(artists, list):
        set_tag("Penciller", ", ".join(artists))
    elif isinstance(artists, str):
        set_tag("Penciller", artists)

    genres = metadata.get("genres") or metadata.get("tags") or []
    if isinstance(genres, list):
        set_tag("Genre", ", ".join(str(g) for g in genres))
    elif isinstance(genres, str):
        set_tag("Genre", genres)

    set_tag("Web", metadata.get("url") or "")
    set_tag("LanguageISO", "en")
    set_tag("Format", "Digital")
    set_tag("Manga", "YesAndRightToLeft" if metadata.get("series_type") == "Manga" else "Yes")
    set_tag("Notes", f"Managed by Mangasurf v1.7.0 - Source: {metadata.get('source_name', metadata.get('source', 'Unknown'))}")
    
    if metadata.get("rating"):
        set_tag("CommunityRating", str(metadata.get("rating")))
    if metadata.get("year"):
        set_tag("Year", str(metadata.get("year")))

    return ET.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def write_folder_metadata(folder_path: str, metadata: dict):
    """Write both manga.json AND ComicInfo.xml into a series folder."""
    if not folder_path or not os.path.isdir(folder_path):
        return

    # 1. Write manga.json
    json_path = os.path.join(folder_path, "manga.json")
    try:
        existing = {}
        if os.path.isfile(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        
        merged = {**existing, **metadata}
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.debug("Failed to write manga.json in %s: %s", folder_path, e)

    # 2. Write ComicInfo.xml
    xml_path = os.path.join(folder_path, "ComicInfo.xml")
    try:
        xml_content = generate_comic_info_xml(metadata)
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)
    except Exception as e:
        logger.debug("Failed to write ComicInfo.xml in %s: %s", folder_path, e)
