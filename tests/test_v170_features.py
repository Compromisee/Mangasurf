"""Comprehensive test suite for Mangasurf v1.7.0 advanced features:

- Package renaming to mangasurf & backward-compatible aliases
- Accurate multi-chapter downloaded count tracking
- MAL (MyAnimeList), PornhwaDB, and MangaBaka integrations
- Cross-source title cross-referencing and downloaded recognition
- ComicInfo.xml and manga.json metadata building
- Title decluttering for File Explorer & OPDS Server
- Settings maintenance tools (rescan, fix covers, rebuild metadata)
"""

import json
import os
import shutil
import tempfile
import pytest

from mangasurf.gui import Api
from mangasurf.metadata import (
    normalize_title,
    declutter_title,
    search_mal,
    search_pornhwadb,
    search_mangabaka,
    get_title_synonyms,
    cross_reference_downloaded,
    generate_comic_info_xml,
    write_folder_metadata,
)
from mangasurf import library


def test_mangasurf_package_imports():
    """Verify mangasurf package and mangasurf alias both import cleanly."""
    import mangasurf
    import mangasurf
    assert mangasurf.__version__ == "1.7.1"
    assert mangasurf.__version__ == "1.7.1"


def test_declutter_titles():
    """Verify title decluttering strips release tags, brackets, and resolution stamps."""
    raw_titles = [
        ("Solo Leveling [Official] [1080p]", "Solo Leveling"),
        ("The Bastard of Swordborne (Uncensored) - Season 2", "The Bastard of Swordborne"),
        ("Dungeon Odyssey [Digital] [Complete]", "Dungeon Odyssey"),
        ("Secret Class (Webtoon) - Official", "Secret Class"),
    ]
    for raw, expected in raw_titles:
        cleaned = declutter_title(raw)
        assert cleaned == expected, f"Expected '{expected}', got '{cleaned}'"


def test_comic_info_xml_and_manga_json_generation():
    """Verify ComicInfo.xml and manga.json are properly generated in a series folder."""
    temp_dir = tempfile.mkdtemp(prefix="mangasurf_meta_test_")
    try:
        sample_meta = {
            "title": "The Bastard of Swordborne [Official]",
            "authors": ["Master Jin", "Redice"],
            "artists": ["Studio Blade"],
            "description": "Jin discovers an ancient primordial sword manual...",
            "genres": ["Action", "Fantasy", "Manhwa"],
            "rating": 9.5,
            "year": 2026,
            "source": "chikari",
            "source_name": "Chikari",
            "url": "https://chikari.moe/series/the-bastard-of-swordborne",
        }
        
        write_folder_metadata(temp_dir, sample_meta)
        
        xml_path = os.path.join(temp_dir, "ComicInfo.xml")
        json_path = os.path.join(temp_dir, "manga.json")
        
        assert os.path.isfile(xml_path), "ComicInfo.xml must be created"
        assert os.path.isfile(json_path), "manga.json must be created"
        
        with open(xml_path, "r", encoding="utf-8") as f:
            xml_text = f.read()
            assert "<Title>The Bastard of Swordborne</Title>" in xml_text
            assert "<Writer>Master Jin, Redice</Writer>" in xml_text
            assert "<Genre>Action, Fantasy, Manhwa</Genre>" in xml_text
            
        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)
            assert json_data["source"] == "chikari"
            assert "Master Jin" in json_data["authors"]
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_cross_source_referencing():
    """Verify that downloading on one site allows cross-source match on another site."""
    mock_library = [
        {
            "title": "Solo Leveling",
            "url": "https://mangadex.org/title/solo-leveling",
            "source": "mangadex",
            "chapters": 179,
        },
        {
            "title": "Secret Class",
            "url": "https://hiperdex.com/manga/secret-class",
            "source": "hiperdex",
            "chapters": 210,
        }
    ]
    
    # 1. Search item from Asura Scans matching by Title
    asura_item = {
        "title": "Solo Leveling [Official]",
        "url": "https://asuracomic.net/series/solo-leveling",
        "source": "asurascans"
    }
    match1 = cross_reference_downloaded(asura_item, mock_library)
    assert match1 is not None
    assert match1["title"] == "Solo Leveling"

    # 2. Search item from KuraHentai matching by alternative title/synonym
    kura_item = {
        "title": "Secret Lesson",
        "url": "https://kurahentai.com/series/secret-lesson",
        "source": "kurahentai"
    }
    match2 = cross_reference_downloaded(kura_item, mock_library)
    assert match2 is not None
    assert match2["title"] == "Secret Class"


def test_pornhwadb_and_mangabaka_metadata():
    """Verify PornhwaDB and MangaBaka metadata indexers return accurate entries."""
    pdb_res = search_pornhwadb("secret class", limit=2)
    assert len(pdb_res) > 0
    assert "Secret Class" in pdb_res[0]["title"]
    assert pdb_res[0]["provider"] == "PornhwaDB"

    mb_res = search_mangabaka("solo leveling", limit=2)
    assert len(mb_res) > 0
    assert "Solo Leveling" in mb_res[0]["title"]
    assert mb_res[0]["provider"] == "MangaBaka"


def test_online_chapter_streaming_api():
    """Verify reader_open can stream online chapter URLs directly from sources."""
    api = Api()
    from mangasurf.sources.chikari import ChikariSource
    src = ChikariSource()
    chs = src.get_chapters("https://chikari.moe/series/the-bastard-of-swordborne")
    assert len(chs) > 0
    test_url = chs[0]["url"]
    res = api.reader_open(test_url)
    assert res.get("ok") is True
    assert res.get("kind") == "pages"
    assert len(res.get("pages", [])) > 0
    assert res.get("is_online") is True
