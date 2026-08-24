"""v3.2.1 — the reader's own stylesheet 403'd, and filters had no controls.

Two reported bugs, both reproduced before they were fixed:

1. The window opens ``/?t=<token>``. That page then loads ``./style.css`` and
   ``./app.js`` by relative URL, and a browser does not copy a query string
   onto a sub-resource, so every one of them came back **403**. Measured on
   the real ``AssetServer``: body font ``"Times New Roman"``, background
   ``rgba(0, 0, 0, 0)``, ``window.__readerReady`` never true.

2. ``features.DEFAULT_FILTERS`` -- min/max chapters, blocked titles, tags and
   authors, hide-no-cover, safe mode -- is applied to every search on the
   Python side, but nothing in the interface could set it.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP = os.path.join(ROOT, "mangasurf", "reader", "app")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ─────────────────────────────────────────────────────── asset server


@pytest.fixture()
def server():
    from mangasurf.reader.assets import AssetServer

    srv = AssetServer()
    srv.start()
    yield srv
    srv.stop()


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        response = urllib.request.urlopen(request, timeout=10)
        return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


@pytest.mark.parametrize("asset", [
    "style.css", "theme.css", "app.js", "themes.js", "manga-view.js",
])
def test_the_page_can_load_its_own_assets_by_relative_url(server, asset):
    """index.html is served from "/", so `./style.css` resolves to
    `/style.css` -- not `/app/style.css`. Both the route and the auth have to
    cope, or the app renders unstyled with no JavaScript."""
    base = f"http://127.0.0.1:{server.port}"
    status, body, _ = fetch(f"{base}/{asset}",
                            {"Cookie": f"mangasurf_token={server.token}"})
    assert status == 200, f"{asset} -> {status}"
    assert len(body) > 200, asset


def test_the_first_tokened_request_hands_out_a_cookie(server):
    """Relative sub-resources arrive with no query string. A Referer is not
    enough on its own: CSS @import and JS module imports send the *stylesheet
    or module* as the Referer, not the page."""
    status, _, headers = fetch(server.url("/"))
    assert status == 200
    cookie = headers.get("Set-Cookie", "")
    assert "mangasurf_token=" in cookie, headers
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie


def test_a_nested_import_is_authorised_by_the_cookie(server):
    """theme.css is reached by @import from style.css, and themes.js by a
    module import from app.js. Neither carries the page's token."""
    base = f"http://127.0.0.1:{server.port}"
    jar = {"Cookie": f"mangasurf_token={server.token}"}
    for nested, referer in (("theme.css", "style.css"), ("themes.js", "app.js")):
        status, _, _ = fetch(f"{base}/{nested}",
                             {**jar, "Referer": f"{base}/{referer}"})
        assert status == 200, f"{nested} (imported from {referer}) -> {status}"


def test_the_engine_is_reachable_from_a_page_at_the_root(server):
    """app.js imports '../foliate/view.js', which from "/" normalises to
    "/foliate/view.js"."""
    base = f"http://127.0.0.1:{server.port}"
    status, body, _ = fetch(f"{base}/foliate/view.js",
                            {"Cookie": f"mangasurf_token={server.token}"})
    assert status == 200
    assert b"export" in body


def test_a_request_with_no_token_at_all_is_still_refused(server):
    base = f"http://127.0.0.1:{server.port}"
    status, _, _ = fetch(f"{base}/style.css")
    assert status == 403


def test_a_wrong_cookie_is_refused(server):
    base = f"http://127.0.0.1:{server.port}"
    status, _, _ = fetch(f"{base}/style.css", {"Cookie": "mangasurf_token=nope"})
    assert status == 403


def test_the_cookie_is_only_issued_to_a_real_token(server):
    """Otherwise the 403 page would hand out the key it just refused."""
    base = f"http://127.0.0.1:{server.port}"
    _, _, headers = fetch(f"{base}/style.css?t=wrong")
    assert "Set-Cookie" not in headers, headers


def test_the_root_shortcut_cannot_escape_the_asset_folder(server):
    """The "/name" fallback maps onto app/, and must not become a way out."""
    jar = {"Cookie": f"mangasurf_token={server.token}"}
    base = f"http://127.0.0.1:{server.port}"
    for attack in ("/..%2fassets.py", "/%2e%2e%2fassets.py", "/etc"):
        status, _, _ = fetch(f"{base}{attack}", jar)
        assert status in (403, 404), f"{attack} -> {status}"


def test_a_missing_root_asset_is_a_clean_404(server):
    jar = {"Cookie": f"mangasurf_token={server.token}"}
    status, _, _ = fetch(f"http://127.0.0.1:{server.port}/nope.css", jar)
    assert status == 404


# ─────────────────────────────────────────────── filters: backend truth


@pytest.fixture()
def filtered(tmp_path, monkeypatch):
    from mangasurf import features

    monkeypatch.setattr(features, "FILTERS_PATH", str(tmp_path / "filters.json"))
    return features


ROWS = [
    {"title": "Solo Leveling", "chapters": 179, "cover": "x"},
    {"title": "Tiny Oneshot", "chapters": 3, "cover": "x"},
    {"title": "Endless Epic", "chapters": 1200, "cover": "x"},
    {"title": "Unknown Count", "cover": "x"},
    {"title": "No Cover Here", "chapters": 50},
    {"title": "Spicy Thing", "chapters": 40, "cover": "x", "tags": ["Smut"]},
]


def kept(features, **changes):
    filters = {**features.DEFAULT_FILTERS, **changes}
    return [row["title"] for row in features.apply_filters(ROWS, filters)]


def test_min_chapters_drops_short_series(filtered):
    assert "Tiny Oneshot" not in kept(filtered, min_chapters=10)
    assert "Solo Leveling" in kept(filtered, min_chapters=10)


def test_max_chapters_drops_long_series(filtered):
    assert "Endless Epic" not in kept(filtered, max_chapters=200)
    assert "Solo Leveling" in kept(filtered, max_chapters=200)


def test_a_range_applies_both_ends(filtered):
    result = kept(filtered, min_chapters=10, max_chapters=200)
    assert "Tiny Oneshot" not in result
    assert "Endless Epic" not in result
    assert "Solo Leveling" in result


def test_an_unknown_chapter_count_is_kept_by_default(filtered):
    """MangaDex leaves the count empty for every ongoing series; dropping
    those would make whole sources vanish from a filtered search."""
    assert "Unknown Count" in kept(filtered, min_chapters=10)


def test_strict_range_drops_an_unknown_count(filtered):
    assert "Unknown Count" not in kept(
        filtered, min_chapters=10, strict_chapter_range=True)


def test_strict_range_does_nothing_without_a_range(filtered):
    assert "Unknown Count" in kept(filtered, strict_chapter_range=True)


def test_blocked_titles_match_case_insensitively(filtered):
    assert "Endless Epic" not in kept(filtered, blocked_titles=["epic"])


def test_blocked_tags_are_dropped(filtered):
    assert "Spicy Thing" not in kept(filtered, blocked_tags=["smut"])


def test_hide_no_cover(filtered):
    assert "No Cover Here" not in kept(filtered, hide_no_cover=True)


def test_safe_mode_drops_adult_tags(filtered):
    assert "Spicy Thing" not in kept(filtered, safe_mode=True)


def test_filters_round_trip_through_the_api(filtered):
    from mangasurf.gui import Api

    api = Api()
    api.set_filters({"min_chapters": 12, "blocked_tags": ["harem"]})
    saved = api.get_filters()["filters"]
    assert saved["min_chapters"] == 12
    assert saved["blocked_tags"] == ["harem"]


def test_an_unknown_filter_key_is_ignored(filtered):
    """set_filters only writes keys it knows, so a typo cannot corrupt the
    file into something apply_filters then trips over."""
    from mangasurf.gui import Api

    api = Api()
    saved = api.set_filters({"min_chapters": 5, "nonsense": True})["filters"]
    assert saved["min_chapters"] == 5
    assert "nonsense" not in saved


# ────────────────────────────────────────────────── filters: the UI


def test_the_search_view_has_filter_controls():
    html = read(os.path.join(APP, "index.html"))
    for control in ("flt-min", "flt-max", "flt-strict", "flt-titles",
                    "flt-tags", "flt-authors", "flt-nocover", "flt-safe",
                    "flt-clear"):
        assert f'id="{control}"' in html, control


def test_every_backend_filter_has_a_control():
    """The bug was a whole subsystem with no interface; this stops it
    happening again as DEFAULT_FILTERS grows."""
    from mangasurf.features import DEFAULT_FILTERS

    app = read(os.path.join(APP, "app.js"))
    bound = set(re.findall(r"pushFilters\(\{\s*\[?([a-z_]+)", app))
    bound |= set(re.findall(r"number\('#flt-[a-z]+',\s*'([a-z_]+)'\)", app))
    bound |= set(re.findall(r"list\('#flt-[a-z]+',\s*'([a-z_]+)'\)", app))
    bound |= set(re.findall(r"flag\('#flt-[a-z]+',\s*'([a-z_]+)'\)", app))
    missing = sorted(k for k in DEFAULT_FILTERS if k not in bound)
    assert missing == [], f"no control for: {missing}"


def test_the_ui_filter_defaults_match_python():
    from mangasurf.features import DEFAULT_FILTERS

    app = read(os.path.join(APP, "app.js"))
    block = app[app.index("const FILTER_DEFAULTS"):]
    block = block[:block.index("}")]
    for key in DEFAULT_FILTERS:
        assert key in block, key
