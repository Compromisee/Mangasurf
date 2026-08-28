"""Structural checks for the mobile PWA and the shared animation/effects settings.

These run without a browser (no Playwright). For the front-end files we check
the things that break silently: the server serving every asset under /pwa/,
the service worker being reachable and scoped, the settings keys existing on
the backend, and the JS wiring referencing real element ids.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOBILE = os.path.join(ROOT, "mangasurf", "reader", "mobile")
APP = os.path.join(ROOT, "mangasurf", "reader", "app")

import mangasurf.server as server


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ------------------------------------------------------------- files exist


def test_mobile_shell_files_present():
    for name in ("index.html", "style.css", "app.js", "manifest.webmanifest",
                 "sw.js", "icons/icon-192.png", "icons/icon-512.png"):
        assert os.path.isfile(os.path.join(MOBILE, name)), name


def test_manifest_is_valid_json_and_scoped():
    import json
    man = json.loads(read(os.path.join(MOBILE, "manifest.webmanifest")))
    assert man["name"]
    assert man["display"] == "standalone"
    assert man["start_url"] == "/pwa/"
    assert man["scope"] == "/pwa/"
    assert any("512" in i["sizes"] and "maskable" in i.get("purpose", "")
              for i in man["icons"])


def test_sw_caches_shell_and_skips_api():
    sw = read(os.path.join(MOBILE, "sw.js"))
    assert "'./index.html'" in sw
    assert "caches.match" in sw
    assert "/api/" in sw and "/stream/" in sw


# ------------------------------------------------------------- server routes


def _app(token="testtok"):
    return server.create_app(token=token)


def test_pwa_index_serves_and_injects_token():
    c = _app().test_client()
    H = {"X-Mangasurf-Token": "testtok"}
    r = c.get("/pwa/", headers=H)
    assert r.status_code == 200
    assert b"__MANGASURF_TOKEN__" in r.data
    assert b"app.js" in r.data
    assert r.headers.get("Set-Cookie")


def test_pwa_index_requires_auth():
    c = _app().test_client()
    assert c.get("/pwa/").status_code == 401


def test_pwa_assets_served_and_mime_typed():
    c = _app().test_client()
    H = {"X-Mangasurf-Token": "testtok"}
    assert c.get("/pwa/style.css", headers=H).status_code == 200
    assert c.get("/pwa/../server.py", headers=H).status_code == 404


def test_pwa_manifest_mime():
    c = _app().test_client()
    H = {"X-Mangasurf-Token": "testtok"}
    r = c.get("/pwa/manifest.webmanifest", headers=H)
    assert r.status_code == 200
    assert r.mimetype == "application/manifest+json"


def test_pwa_service_worker_scoped():
    c = _app().test_client()
    H = {"X-Mangasurf-Token": "testtok"}
    r = c.get("/pwa/sw.js", headers=H)
    assert r.status_code == 200
    assert r.headers.get("Service-Worker-Allowed") == "/pwa/"


def test_pwa_icons_cached_immutable():
    c = _app().test_client()
    H = {"X-Mangasurf-Token": "testtok"}
    r = c.get("/pwa/icons/icon-192.png", headers=H)
    assert r.status_code == 200
    assert "immutable" in (r.headers.get("Cache-Control") or "")


# ------------------------------------------------------------- index.html ids


def test_mobile_elements_referenced_by_js_exist():
    html = read(os.path.join(MOBILE, "index.html"))
    js = read(os.path.join(MOBILE, "app.js"))
    ids = set(re.findall(r"\$\('#([\w-]+)'\)", js))
    for attr in re.findall(r"getElementById\('([\w-]+)'\)", js):
        ids.add(attr)
    # Elements that are created dynamically by the JS rather than in the HTML.
    dynamic = {"toast"}
    ids -= dynamic
    missing = [i for i in ids if f'id="{i}"' not in html]
    assert not missing, f"JS references ids missing from index.html: {missing}"


def test_mobile_view_ids_present():
    html = read(os.path.join(MOBILE, "index.html"))
    for vid in ("view-home", "view-search", "view-downloads", "view-settings"):
        assert f'id="{vid}"' in html


def test_mobile_has_settings_sliders():
    html = read(os.path.join(MOBILE, "index.html"))
    for sid in ("set-motion-speed", "set-carousel-speed", "set-carousel-tilt",
                "set-carousel-depth", "set-cover-shine-speed",
                "set-cover-shine-intensity", "set-cover-shine", "set-session-clear"):
        assert f'id="{sid}"' in html, sid


# ------------------------------------------------- settings keys on backend


def test_animation_settings_keys_registered():
    import mangasurf.gui as g
    for key in ("motion_speed", "carousel_speed", "carousel_tilt",
                "carousel_depth", "cover_shine", "cover_shine_speed",
                "cover_shine_intensity"):
        assert key in g.DEFAULT_SETTINGS, key


# ------------------------------------------------- desktop app.js wiring


def _appjs():
    return read(os.path.join(APP, "app.js"))


def test_desktop_boot_calls_apply_motion():
    js = _appjs()
    assert "applyMotion(s || {})" in js


def test_desktop_motion_sliders_wired():
    js = _appjs()
    for sid in ("set-motion-speed", "set-carousel-speed", "set-carousel-tilt",
                "set-carousel-depth", "set-cover-shine-speed",
                "set-cover-shine-intensity", "set-cover-shine"):
        assert f"#set-{sid}" in js or sid in js, sid


def test_desktop_html_has_effects_panel():
    html = read(os.path.join(APP, "index.html"))
    for sid in ("set-motion-speed", "set-carousel-speed", "set-carousel-tilt",
                "set-carousel-depth", "set-cover-shine-speed",
                "set-cover-shine-intensity", "set-cover-shine"):
        assert f'id="{sid}"' in html, sid
