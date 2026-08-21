"""Tests for the landing page and the GUI tabs.

Structural checks run everywhere. The interactive checks drive real headless
Chromium and skip automatically when Playwright is unavailable.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")
DOCS = os.path.join(ROOT, "docs")
SITE = os.path.join(DOCS, "index.html")

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright is not installed")


def read(path):
    return open(path, encoding="utf-8").read()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        for candidate in (os.path.expanduser("~/.cache/ms-playwright"),
                          "/home/user/.cache/ms-playwright"):
            if os.path.isdir(candidate):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
                break
    with sync_playwright() as p:
        try:
            launched = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"chromium unavailable: {exc}")
        yield launched
        launched.close()


@pytest.fixture()
def site(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto("file://" + SITE)
    page.wait_for_timeout(300)
    page.errors = errors
    yield page
    page.close()


# ===================================================== landing page: static


def test_site_has_no_duplicate_ids():
    from collections import Counter

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read(SITE), "html.parser")
    ids = [e["id"] for e in soup.find_all(id=True)]
    assert [k for k, v in Counter(ids).items() if v > 1] == []


def test_every_referenced_image_exists():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read(SITE), "html.parser")
    missing = [img["src"] for img in soup.find_all("img")
               if not os.path.exists(os.path.join(DOCS, img["src"]))]
    assert missing == []


def test_every_cli_tab_has_a_pane():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read(SITE), "html.parser")
    tabs = {t["data-p"] for t in soup.select(".tab[data-p]")}
    panes = {p["id"].replace("p-", "") for p in soup.select(".pane[id]")}
    assert tabs, "no CLI tabs found"
    assert tabs <= panes, f"tabs with no pane: {tabs - panes}"


def test_every_screenshot_tab_has_a_panel():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read(SITE), "html.parser")
    tabs = {t["data-s"] for t in soup.select("[data-s]")}
    shots = {s["id"].replace("s-", "") for s in soup.select(".shot[id]")}
    assert tabs == shots


def test_no_fabricated_social_counts():
    """A static page cannot know real star/fork counts, so it must not show
    any. Inventing them would present made-up numbers as fact."""
    html = read(SITE)
    for fragment in ("btn-count", "stargazers", "Watch<", "Fork<"):
        assert fragment not in html, fragment


def test_stated_counters_match_the_repository():
    """Every number the page shows has to be real."""
    html = read(SITE)

    sources = len(re.findall(r"^\s+\w+Source,",
                             read(os.path.join(ROOT, "readerm", "sources",
                                               "__init__.py")), re.M))

    # FEATURES.md is prose grouped by topic now, not a numbered list, so
    # there is no honest "N documented features" figure to quote. If the
    # page ever claims one again it has to match a real count.
    claim = re.search(r"([\d,]+)\s+documented features", html)
    if claim:
        counted = sum(1 for line in open(os.path.join(ROOT, "MD", "FEATURES.md"),
                                         encoding="utf-8")
                      if re.match(r"^\d+\.", line))
        assert int(claim.group(1).replace(",", "")) == counted, (
            f"page claims {claim.group(1)} features, FEATURES.md has {counted}")

    # Read the stat tiles structurally rather than by class name, so a
    # redesign cannot make this check silently vacuous.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    tiles = {}
    for value in soup.select(".st-n, .hs-n"):
        label = value.find_next(class_=["st-k", "hs-k"])
        if label:
            tiles[label.get_text(strip=True).lower()] = value.get_text(strip=True)
    assert tiles, "no stat tiles found on the page"
    assert tiles.get("sources") == str(sources), (
        f"page says {tiles.get('sources')} sources, registry has {sources}")

    # Tests passing: never claim more tests than the suite actually has.
    # Counting "def test_" is not enough -- 30 parametrize decorators expand
    # 595 functions into 694 cases -- so ask pytest itself.
    collected = _collect_count()
    claimed = int(tiles["tests passing"])
    assert claimed <= collected, f"page claims {claimed}, suite has {collected}"


def _collect_count():
    """How many test cases pytest collects, parametrisation included."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only",
         "-p", "no:cacheprovider", os.path.join(ROOT, "tests")],
        capture_output=True, text=True, cwd=ROOT, timeout=300,
        env={**os.environ, "READERM_UI_COLLECT_GUARD": "1"},
    )
    match = re.search(r"(\d+) tests? collected", result.stdout)
    if not match:
        pytest.skip("could not collect the suite to verify the count")
    return int(match.group(1))


def test_no_stale_source_count_in_prose():
    """The hero headline, <title> and social meta all state a source count in
    prose. Those are not covered by the .hs-n stat check, and were left
    reading "twelve sources" after the registry grew to 23."""
    from readerm.sources import SOURCE_CLASSES

    html = read(SITE)
    stale = ["twelve", "nine sources", "four sources", "12 sources"]
    for word in stale:
        assert word.lower() not in html.lower(), word
    # and the real number must actually appear in the headline
    assert f"{len(SOURCE_CLASSES)} sources" in html


def test_no_stat_the_page_cannot_verify():
    """The merged-genre total is a live property -- 86 with every site
    unreachable (hardcoded fallbacks), 207 with all 23 answering. A static
    page cannot know it, so it must not state one."""
    html = read(SITE)
    assert "merged genres" not in html


def test_source_tiles_match_the_registry():
    """The grid lists sites by hand, so it can drift from the code."""
    from bs4 import BeautifulSoup

    from readerm.sources import list_sources

    soup = BeautifulSoup(read(SITE), "html.parser")
    listed = {t.get_text(strip=True).lower() for t in soup.select(".src-n")}
    real = {m["name"].lower() for m in list_sources()}
    assert listed == real, f"drifted: {listed ^ real}"


def test_adult_sources_are_marked():
    from bs4 import BeautifulSoup

    from readerm.sources import list_sources

    soup = BeautifulSoup(read(SITE), "html.parser")
    tagged = set()
    for tile in soup.select(".src"):
        if tile.select_one(".tag-adult"):
            name = tile.select_one(".src-n")
            if name:
                tagged.add(name.get_text(strip=True).lower())
    expected = {m["name"].lower() for m in list_sources() if m["adult_only"]}
    assert tagged == expected


def test_version_badge_matches_the_package():
    version = re.search(r'__version__ = "([^"]+)"',
                        read(os.path.join(ROOT, "readerm", "__init__.py"))).group(1)
    assert version in read(SITE)


def test_links_point_at_the_right_repository():
    html = read(SITE)
    assert "github.com/Compromisee/mangasurf" in html or "github.com/Compromisee/ReaderM" in html
    # The old names must not linger anywhere on the page.
    assert "Compromisee/WeebDL" not in html
    assert "Compromisee/MDL" not in html
    assert "Yui007" not in html


def test_both_colour_modes_are_defined():
    html = read(SITE)
    assert 'data-theme="night"' in html
    assert 'html[data-theme="dawn"]' in html


def test_site_respects_reduced_motion():
    assert "prefers-reduced-motion" in read(SITE)


def test_landing_page_uses_icon_font_not_emoji():
    """The brief: Google icons, no emoji.

    Emoji render differently on every OS, are unstyleable, and several
    showed as empty boxes in headless Chromium.
    """
    import re as _re

    from bs4 import BeautifulSoup

    html = read(SITE)
    soup = BeautifulSoup(html, "html.parser")
    # Only visible copy matters: <style>/<script> banners and shell listings
    # legitimately contain box-drawing and tick characters.
    for tag in soup(["style", "script", "pre"]):
        tag.decompose()
    for pane in soup.select(".pane"):
        pane.decompose()

    emoji = _re.findall(
        "[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", soup.get_text())
    assert emoji == [], f"emoji left on the page: {set(emoji)}"
    assert "material-symbols-rounded" in html, "expected the Material icon font"


def test_landing_page_icons_are_real_ligatures():
    """Every icon span must carry a ligature name, not be left empty."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(read(SITE), "html.parser")
    spans = soup.select(".material-symbols-rounded")
    assert len(spans) >= 10, f"only {len(spans)} icons found"
    empty = [str(s)[:60] for s in spans if not s.get_text(strip=True)]
    assert empty == [], f"icon spans with no ligature: {empty}"


def test_landing_page_fonts_do_not_block_rendering():
    """Same lesson as the app: never block first paint on a font CDN."""
    import re as _re

    html = read(SITE)
    head = html[:html.index("</head>")]
    head = _re.sub(r"<noscript>.*?</noscript>", "", head, flags=_re.S)
    links = [t for t in _re.findall(r"<link[^>]*>", head, flags=_re.S)
             if "fonts.googleapis.com" in t and 'rel="stylesheet"' in t]
    assert links, "expected the font stylesheets to be linked"
    for tag in links:
        assert 'media="print"' in tag and "onload" in tag, tag[:110]


def test_content_is_not_hidden_without_javascript():
    """The scroll reveal must never be able to eat the page.

    The hiding is gated behind html.js, which only JS adds, so a script
    error or an old browser shows everything.
    """
    import re as _re

    # Strip CSS comments first: a comment sitting above a rule gets pulled
    # into the "selector" capture and made every check pass by accident.
    html = _re.sub(r"/\*.*?\*/", "", read(SITE), flags=_re.S)
    # Every rule that hides a .rise element must be scoped to html.js.
    for match in _re.finditer(r"([^{}]*\.rise[^{}]*)\{([^}]*)\}", html):
        selector, body = match.group(1).strip(), match.group(2)
        if "opacity:0" not in body.replace(" ", ""):
            continue
        assert "html.js" in selector or ".js " in selector, (
            f"'{selector}' hides content without a JS gate")
    # ...and something must actually add that class at runtime.
    assert "classList.add('js')" in html or 'classList.add("js")' in html


def test_cli_panes_preserve_their_formatting():
    """The panes are divs; without white-space:pre every listing collapses
    into one wrapped paragraph."""
    html = read(SITE)
    block = html[html.index(".pane{"):html.index(".pane{") + 220]
    assert "white-space:pre" in block.replace(" ", "")


def test_page_is_not_styled_like_github():
    """The brief was an original design, not a code-host clone."""
    html = read(SITE)
    for borrowed in ("repo-tab", "gh-logo", "gh-search", "octicon",
                     "data-color-mode", "lang-bar"):
        assert borrowed not in html, f"GitHub chrome left behind: {borrowed}"


# ================================================ landing page: interactive


def test_site_loads_without_errors(site):
    assert site.errors == []
    assert site.evaluate(
        "() => document.querySelector('.panel .pane.on').id") == "p-dl"


@pytest.mark.parametrize("pane", ["dl", "search", "menu", "lib", "cfg"])
def test_each_cli_tab_switches(site, pane):
    site.click(f'.tab[data-p="{pane}"]')
    site.wait_for_timeout(200)
    assert site.evaluate(
        "() => document.querySelector('.panel .pane.on').id") == f"p-{pane}"


def test_only_one_cli_pane_visible_at_a_time(site):
    site.click('.tab[data-p="search"]')
    site.wait_for_timeout(200)
    visible = site.evaluate("""() =>
        [...document.querySelectorAll('.panel .pane')]
          .filter(p => getComputedStyle(p).display !== 'none').length""")
    assert visible == 1


def test_theme_toggles_and_persists(site):
    before = site.evaluate("() => document.documentElement.dataset.theme")
    site.click("#themeBtn")
    site.wait_for_timeout(250)
    after = site.evaluate("() => document.documentElement.dataset.theme")
    assert after != before
    assert site.evaluate("() => localStorage.getItem('mdl-theme')") == after
    # the change must be visible, not merely an attribute
    bg = site.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert bg in ("rgb(251, 247, 244)", "rgb(11, 10, 18)")


def test_screenshot_tabs_switch(site):
    site.click('[data-s="s3"]')
    site.wait_for_timeout(200)
    assert site.evaluate("() => document.querySelector('#s-s3').classList.contains('on')")
    assert not site.evaluate("() => document.querySelector('#s-s1').classList.contains('on')")


def test_page_does_not_scroll_sideways(site):
    """A horizontal scrollbar is the usual sign of a broken width somewhere."""
    assert not site.evaluate(
        "() => document.documentElement.scrollWidth > window.innerWidth + 1")


def test_anchor_links_all_resolve(site):
    missing = site.evaluate("""() =>
        [...document.querySelectorAll('a[href^="#"]')]
          .map(a => a.getAttribute('href'))
          .filter(h => h.length > 1 && !document.querySelector(h))""")
    assert missing == []


# ==================================================== GUI: new tabs static


def test_get_health_endpoint_exists():
    import importlib
    import tempfile

    os.environ["HOME"] = tempfile.mkdtemp()
    import readerm.gui as gui
    importlib.reload(gui)
    assert hasattr(gui.Api, "get_health")
    report = gui.Api().get_health()
    assert report["ok"] is True
    assert {"breakers", "browse_cache", "genre_cache"} <= set(report["report"])
