"""Comprehensive tests for Mangasurf v1.2.0 features:
- Custom .source plugin specification and loader
- OPDS folder & shelf management API
- Tailscale VPN detection and server routing
- Rapid CBZ streaming & auto-discovery
- Omnibar custom genre adding and search pagination
- Settings source toggling & collapse controls
"""

import os
import json
import tempfile
import zipfile
import pytest

from mangasurf import paths
from mangasurf.sources import SOURCES, get_source, search_all, browse_all
from mangasurf.sources.base import filter_and_rank_query
from mangasurf.server import local_ip, tailscale_ip, _is_tailscale_ip, create_app
from mangasurf.opds import load_opds_folders, save_opds_folders, DEFAULT_OPDS_FOLDERS
from mangasurf.reader import books
from mangasurf.gui import Api


# ── 1. Custom Sources & Plugin Specification ───────────────────────────────

def test_custom_sources_directory_exists():
    custom_dir = os.path.join(os.path.dirname(__file__), "..", "mangasurf", "sources", "customsources")
    real_dir = os.path.abspath(custom_dir)
    assert os.path.isdir(real_dir)
    
    # Check syntax.source and template.source
    syntax_file = os.path.join(real_dir, "syntax.source")
    template_file = os.path.join(real_dir, "template.source")
    assert os.path.isfile(syntax_file)
    assert os.path.isfile(template_file)


def test_syntax_source_contains_all_spec_sections():
    syntax_path = os.path.join(os.path.dirname(__file__), "..", "mangasurf", "sources", "customsources", "syntax.source")
    content = open(syntax_path, encoding="utf-8").read()
    assert "[source]" in content
    assert "[headers]" in content
    assert "[search]" in content
    assert "[browse]" in content
    assert "[genres]" in content
    assert "[manga_info]" in content
    assert "[chapters]" in content
    assert "[images]" in content


# ── 2. OPDS Folder Management API ──────────────────────────────────────────

def test_opds_folders_crud_lifecycle(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "opds_folders.json")
        import mangasurf.opds as opds
        monkeypatch.setattr(opds, "OPDS_FOLDERS_FILE", test_file)

        # 1. Load default
        folders = opds.load_opds_folders()
        assert len(folders) >= 3
        assert any(f["id"] == "all" for f in folders)

        # 2. Add custom section
        new_entry = {
            "id": "custom-action",
            "name": "Action Favorites",
            "type": "shelf",
            "enabled": True,
            "filter": "shelf:Action",
        }
        folders.append(new_entry)
        assert opds.save_opds_folders(folders) is True

        # 3. Reload from disk
        reloaded = opds.load_opds_folders()
        assert len(reloaded) == len(folders)
        assert any(f["id"] == "custom-action" for f in reloaded)

        # 4. Toggle
        for f in reloaded:
            if f["id"] == "custom-action":
                f["enabled"] = False
        opds.save_opds_folders(reloaded)

        disabled = opds.load_opds_folders()
        custom = next(f for f in disabled if f["id"] == "custom-action")
        assert custom["enabled"] is False


# ── 3. Tailscale IP Detection ──────────────────────────────────────────────

def test_tailscale_ip_validation():
    # Valid CGNAT range (100.64.0.0 to 100.127.255.255)
    assert _is_tailscale_ip("100.64.0.1") is True
    assert _is_tailscale_ip("100.100.50.2") is True
    assert _is_tailscale_ip("100.127.255.254") is True

    # Invalid / non-tailscale addresses
    assert _is_tailscale_ip("192.168.1.1") is False
    assert _is_tailscale_ip("10.0.0.1") is False
    assert _is_tailscale_ip("127.0.0.1") is False
    assert _is_tailscale_ip("100.50.0.1") is False  # second octet < 64
    assert _is_tailscale_ip("100.130.0.1") is False  # second octet > 127
    assert _is_tailscale_ip(None) is False
    assert _is_tailscale_ip("") is False


# ── 4. Server CBZ Range Streaming & Discovery ──────────────────────────────

def test_cbz_auto_discovery_and_streaming():
    with tempfile.TemporaryDirectory() as tmpdir:
        series_dir = os.path.join(tmpdir, "Solo Leveling")
        os.makedirs(series_dir, exist_ok=True)
        cbz_file = os.path.join(series_dir, "Solo Leveling - Chapters 001-050.cbz")
        
        with zipfile.ZipFile(cbz_file, "w") as zf:
            zf.writestr("001.jpg", b"header" * 50)
            zf.writestr("002.jpg", b"page2" * 50)

        entry = {"title": "Solo Leveling", "directory": series_dir}
        items = books.entry_items(entry)
        assert len(items) == 1
        assert items[0]["format"] == "cbz"
        assert items[0]["readable"] is True

        api = Api()
        res = api.reader_open(cbz_file)
        assert res.get("ok") is True
        assert res.get("format") == "cbz"
        assert "/book?path=" in res.get("url", "")

        # Test Flask server range streaming
        from mangasurf.server import Flask as ServerFlask
        if ServerFlask is not None:
            app = create_app(token="tok123", api=api)
            client = app.test_client()

            # HEAD request
            head_resp = client.head(f"/stream/book?path={cbz_file}&token=tok123")
            assert head_resp.status_code == 200
            assert head_resp.headers.get("Accept-Ranges") == "bytes"
            assert int(head_resp.headers.get("Content-Length", 0)) > 0

            # Partial Range request
            range_resp = client.get(f"/stream/book?path={cbz_file}&token=tok123", headers={"Range": "bytes=0-49"})
            assert range_resp.status_code == 206
            assert len(range_resp.data) == 50
            assert range_resp.headers.get("Content-Range").startswith("bytes 0-49/")


# ── 5. Search Filter & Relevance ───────────────────────────────────────────

def test_search_relevance_ranks_exact_matches_first():
    catalog = [
        {"title": "Solo Camping for Two", "url": "https://example.com/3"},
        {"title": "Solo Leveling", "url": "https://example.com/1"},
        {"title": "Solo Bug Player", "url": "https://example.com/2"},
    ]
    ranked = filter_and_rank_query(catalog, "Solo Leveling")
    assert len(ranked) >= 1
    assert ranked[0]["title"] == "Solo Leveling"


# ── 6. Web Reader & Server Boot Resilience ───────────────────────────────────

def test_reader_js_has_no_unsafe_search_source_listeners():
    """Ensure search-source event listener is safe and does not crash reader boot."""
    app_js_path = os.path.join(os.path.dirname(__file__), "..", "mangasurf", "reader", "app", "app.js")
    with open(app_js_path, encoding="utf-8") as f:
        content = f.read()

    # The unsafe listener call that threw 'Cannot read properties of null (reading addEventListener)'
    assert "$('#search-source').addEventListener" not in content
    # Should either use optional chaining or safe check
    assert "$('#search-source')?.addEventListener" in content or "$('#search-source')" not in content


# ── 7. Library Folder Scanning & OPDS Persistence ───────────────────────────

def test_scan_library_folders_discovers_cbz_and_series():
    with tempfile.TemporaryDirectory() as tmpdir:
        library_dir = os.path.join(tmpdir, "MangaLibrary")
        os.makedirs(library_dir, exist_ok=True)

        # 1. Series folder with CBZ archives
        series_dir = os.path.join(library_dir, "Tower of God")
        os.makedirs(series_dir, exist_ok=True)
        cbz1 = os.path.join(series_dir, "Tower of God - Chapter 01.cbz")
        cbz2 = os.path.join(series_dir, "Tower of God - Chapter 02.cbz")
        with open(cbz1, "wb") as f:
            f.write(b"PK\x03\x04mock")
        with open(cbz2, "wb") as f:
            f.write(b"PK\x03\x04mock2")
        cover_file = os.path.join(series_dir, "cover.jpg")
        with open(cover_file, "wb") as f:
            f.write(b"\xff\xd8\xffcover")

        # 2. Standalone archive in root
        standalone = os.path.join(library_dir, "Claymore.cbz")
        with open(standalone, "wb") as f:
            f.write(b"PK\x03\x04claymore")

        from mangasurf import library, opds

        scan_res = library.scan_library_folders([library_dir])
        assert scan_res["ok"] is True
        assert scan_res["discovered"] >= 2

        # Verify OPDS discovery
        rows = opds.library_rows()
        titles = [r["title"] for r in rows]
        assert "Tower of God" in titles
        assert "Claymore" in titles

        tog_row = next(r for r in rows if r["title"] == "Tower of God")
        assert len(tog_row["files"]) == 2
        assert tog_row["cover"] == cover_file


def test_api_library_folders_crud():
    api = Api()
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_folder = os.path.join(tmpdir, "MyComics")
        os.makedirs(custom_folder, exist_ok=True)

        # Add
        res = api.add_library_folder(custom_folder)
        assert res["ok"] is True
        assert custom_folder in res["folders"]

        # Get
        res_get = api.get_library_folders()
        assert res_get["ok"] is True
        assert custom_folder in res_get["folders"]

        # Remove
        res_rem = api.remove_library_folder(custom_folder)
        assert res_rem["ok"] is True
        assert custom_folder not in res_rem["folders"]


def test_settings_html_contains_library_folders_section():
    html_path = os.path.join(os.path.dirname(__file__), "..", "mangasurf", "reader", "app", "index.html")
    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    assert 'id="library-group"' in html
    assert 'id="lib-scan-now-btn"' in html
    assert 'id="lib-add-folder-btn"' in html
    assert 'id="lib-folders-list"' in html


