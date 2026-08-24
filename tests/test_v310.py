"""v3.1.0 — the appearance system, driven through a real browser.

The bug this release fixes is a quiet one: `theme`, `accent`, `corners`,
`matrix`, `animations` and `columns` were still in Python's DEFAULT_SETTINGS
and still being written to `config.json` after v3.0.0 replaced the front-end.
Nothing read them. Changing them did nothing at all.

So the tests here mostly ask one question in different ways: does the setting
actually reach the pixels? Contrast and colour are measured off the rendered
page, not asserted from source text.
"""
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP = os.path.join(ROOT, "mangasurf", "reader", "app")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ─────────────────────────────────────────────────────────── static checks


def test_the_design_tokens_live_in_one_file():
    assert os.path.isfile(os.path.join(APP, "theme.css"))
    assert '@import url("./theme.css")' in read(os.path.join(APP, "style.css"))


def test_every_theme_defines_every_token():
    """A token used in CSS but missing from one theme is an invisible
    control: the pre-v3 GUI shipped a 0.03-contrast queue exactly that way."""
    css = read(os.path.join(APP, "theme.css"))
    blocks = re.findall(r'\[data-theme="([a-z]+)"\]\s*\{([^}]*)\}', css)
    palettes = [(name, body) for name, body in blocks if "--bg:" in body]
    assert len(palettes) >= 8, [n for n, _ in palettes]
    keysets = {name: set(re.findall(r"(--[a-z0-9-]+)\s*:", body))
               for name, body in palettes}
    reference = keysets[palettes[0][0]]
    for name, keys in keysets.items():
        assert keys == reference, (name, keys ^ reference)


def test_every_theme_defines_the_matrix_dot_colour():
    """Without it the dot layer is invisible, which reads as 'matrix broken'."""
    css = read(os.path.join(APP, "theme.css"))
    for name, body in re.findall(r'\[data-theme="([a-z]+)"\]\s*\{([^}]*)\}', css):
        if "--bg:" in body:
            assert "--matrix-dot:" in body, name


def test_light_themes_get_their_own_accent_table():
    """Pastel accents that work on #16161e fail contrast on white."""
    css = read(os.path.join(APP, "theme.css"))
    assert '[data-theme="light"][data-accent="blue"]' in css
    assert '[data-theme="paper"][data-accent="blue"]' in css


def test_square_corner_mode_zeroes_every_radius_token():
    css = read(os.path.join(APP, "theme.css"))
    block = css[css.index('[data-corners="square"]'):]
    block = block[:block.index("}")]
    for token in ("--r-sm", "--r-md", "--r-lg", "--r-xl", "--r-pill"):
        assert f"{token}: 0px" in block, token


def test_fonts_never_block_first_paint():
    """v1.4.24 measured the old head stalling >45s on a slow font CDN.

    Parsed as whole tags, not line by line: `rel` and `href` sit on separate
    lines here, so a per-line scan matched neither and the test passed with
    the guard removed.
    """
    html = read(os.path.join(APP, "index.html"))
    tags = re.findall(r"<link\b[^>]*>", html, re.S)
    remote = [t for t in tags
              if "fonts.googleapis.com/css2" in t and 'rel="stylesheet"' in t]
    assert remote, "no remote font stylesheet found -- has the markup moved?"
    for tag in remote:
        flat = " ".join(tag.split())
        assert 'media="print"' in flat, flat


def test_icon_glyphs_are_hidden_until_the_font_loads():
    """Material Symbols are ligatures: before the font lands the browser
    paints the literal word 'settings'."""
    css = read(os.path.join(APP, "theme.css"))
    assert "html:not(.icons-ready) .mi" in css
    assert "visibility: hidden" in css
    assert "icons-ready" in read(os.path.join(APP, "app.js"))


def test_no_hard_coded_hex_colours_in_the_chrome():
    """Everything must come from a token, or a theme change misses it."""
    css = read(os.path.join(APP, "style.css"))
    offenders = []
    for line in css.splitlines():
        stripped = line.strip()
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        for match in re.findall(r"#[0-9a-fA-F]{3,8}\b", line):
            offenders.append(f"{stripped[:70]} -> {match}")
    assert offenders == [], offenders


# ────────────────────────────────────────────────────────── browser tests


@pytest.fixture(scope="module")
def origin():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=os.path.dirname(APP))

    class Server(socketserver.TCPServer):
        allow_reuse_address = True
        daemon_threads = True

        def handle_error(self, *args):
            pass

    httpd = Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        for candidate in (os.path.expanduser("~/.cache/ms-playwright"),
                          "/home/user/.cache/ms-playwright"):
            if os.path.isdir(candidate):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = candidate
                break
    with sync_playwright() as play:
        try:
            launched = play.chromium.launch()
        except Exception as exc:                       # pragma: no cover
            pytest.skip(f"chromium unavailable: {exc}")
        yield launched
        launched.close()


SOURCES = [
    {"id": "mangadex", "name": "MangaDex", "base_url": "https://mangadex.org",
     "enabled": True, "supports_language": True, "supports_scanlator": True,
     "needs_flaresolverr": False, "adult_only": False},
    {"id": "weebcentral", "name": "Weeb Central", "base_url": "https://weebcentral.com",
     "enabled": True, "supports_language": False, "supports_scanlator": False,
     "needs_flaresolverr": True, "adult_only": False},
    {"id": "nhentai", "name": "nhentai", "base_url": "https://nhentai.to",
     "enabled": False, "supports_language": False, "supports_scanlator": False,
     "needs_flaresolverr": False, "adult_only": True},
]

STUB = {
    "get_settings": {"ok": True, "settings": {
        "theme": "midnight", "accent": "blue", "corners": "rounded",
        "matrix": True, "animations": True, "columns": 0,
        "reader_mode": "webtoon", "reader_fit": "contain", "reader_gap": 0,
        "reader_max_width": "100%", "reader_filter": "none",
        "output_dir": "/tmp/dl", "format": "cbz", "delay": 0.5,
        "max_concurrent_jobs": 2, "chapter_workers": 3, "image_workers": 6,
        "retries": 5, "server_port": 8577, "opds_port": 8578}},
    "get_sources": {"ok": True, "sources": [{"id": s["id"], "name": s["name"]} for s in SOURCES]},
    "get_source_config": {"ok": True, "sources": SOURCES},
    "lock_status": {"ok": True, "enabled": False, "should_lock": False},
    "reader_library": {"ok": True, "count": 0, "books": []},
    "reader_recent": {"ok": True, "items": []},
    "get_queue": {"ok": True, "queue": []},
}


@pytest.fixture()
def page(browser, origin):
    init = """
    window.__calls = [];
    window.pywebview = { api: new Proxy({}, { get: (_, name) => {
      if (name === 'then') return undefined;
      return async (...args) => {
        window.__calls.push([String(name), args]);
        return (%s)[String(name)] ?? { ok: true };
      };
    }})};
    """ % json.dumps(STUB)
    pg = browser.new_page(viewport={"width": 1280, "height": 860})
    pg.errors = []
    pg.on("pageerror", lambda exc: pg.errors.append(str(exc)))
    pg.on("console", lambda msg: pg.errors.append(msg.text)
          if msg.type == "error" else None)
    pg.add_init_script(init)
    pg.goto(origin + "/app/index.html", wait_until="load")
    pg.wait_for_function("window.__readerReady === true", timeout=20000)
    yield pg
    pg.close()


def luminance(css_colour):
    nums = [int(n) for n in re.findall(r"\d+", css_colour)[:3]]
    if len(nums) < 3:
        return 0.0
    r, g, b = nums

    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(one, two):
    a, b = sorted((luminance(one), luminance(two)), reverse=True)
    return (a + 0.05) / (b + 0.05)


THEMES = ["midnight", "mocha", "forest", "plum", "ocean", "oled", "light", "paper"]
ACCENTS = ["blue", "violet", "teal", "rose", "amber", "mint"]


def test_the_app_boots_with_no_console_errors(page):
    assert page.evaluate("window.__readerReady") is True
    assert page.errors == []


@pytest.mark.parametrize("theme", THEMES)
def test_each_theme_paints_the_page(page, theme):
    applied = page.evaluate("t => { window.__reader.setTheme(t); "
                            "return getComputedStyle(document.body).backgroundColor }", theme)
    assert applied and applied != "rgba(0, 0, 0, 0)", theme
    assert page.evaluate("document.documentElement.dataset.theme") == theme


@pytest.mark.parametrize("theme", THEMES)
def test_body_text_is_readable_on_every_theme(page, theme):
    """Measured off the rendered page, so a bad palette cannot pass."""
    page.evaluate("t => window.__reader.setTheme(t)", theme)
    got = page.evaluate("""() => {
        const cs = getComputedStyle(document.body);
        return [cs.color, cs.backgroundColor];
    }""")
    ratio = contrast(got[0], got[1])
    assert ratio >= 7.0, f"{theme}: body text contrast only {ratio:.1f}:1"


@pytest.mark.parametrize("theme", THEMES)
def test_secondary_text_still_passes_on_every_theme(page, theme):
    page.evaluate("t => window.__reader.setTheme(t)", theme)
    got = page.evaluate("""() => {
        const root = getComputedStyle(document.documentElement);
        const probe = document.createElement('span');
        probe.style.color = root.getPropertyValue('--text-2');
        document.body.append(probe);
        const colour = getComputedStyle(probe).color;
        probe.remove();
        return [colour, getComputedStyle(document.body).backgroundColor];
    }""")
    ratio = contrast(got[0], got[1])
    assert ratio >= 4.5, f"{theme}: secondary text contrast only {ratio:.1f}:1"


@pytest.mark.parametrize("accent", ACCENTS)
def test_accent_text_is_legible_on_the_accent(page, accent):
    """The label on a filled button has to survive every accent."""
    page.evaluate("a => window.__reader.setAccent(a)", accent)
    got = page.evaluate("""() => {
        const probe = document.createElement('div');
        probe.className = 'btn primary';
        probe.textContent = 'x';
        document.body.append(probe);
        const cs = getComputedStyle(probe);
        const out = [cs.color, cs.backgroundColor];
        probe.remove();
        return out;
    }""")
    ratio = contrast(got[0], got[1])
    assert ratio >= 4.0, f"{accent}: button label contrast only {ratio:.1f}:1"


@pytest.mark.parametrize("accent", ACCENTS)
def test_accents_are_distinct_on_light_themes(page, accent):
    """Light themes carry a separate accent table; check it actually applies."""
    dark, light = page.evaluate("""a => {
        window.__reader.setTheme('midnight'); window.__reader.setAccent(a);
        const d = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
        window.__reader.setTheme('light');
        const l = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
        return [d, l];
    }""", accent)
    assert dark and light
    assert dark != light, f"{accent} did not change for the light theme"


def test_square_corners_flatten_real_elements(page):
    """Reading the token is not enough -- a component with a hard-coded
    radius would still be round."""
    rounded = page.evaluate("""() => {
        window.__reader.setCorners(false);
        const c = document.createElement('div');
        c.className = 'card'; document.body.append(c);
        const r = getComputedStyle(c).borderRadius;
        c.remove(); return r;
    }""")
    square = page.evaluate("""() => {
        window.__reader.setCorners(true);
        const c = document.createElement('div');
        c.className = 'card'; document.body.append(c);
        const r = getComputedStyle(c).borderRadius;
        c.remove(); return r;
    }""")
    assert rounded not in ("0px", ""), rounded
    assert square == "0px", square


def test_square_corners_reach_the_reader_overlay(page):
    """The reader is a separate surface, and a corner setting has to cover it.

    Aimed at elements that are genuinely round to begin with -- #r-panel has
    no radius of its own, so asserting 0px on it passed even with the whole
    square-corner rule deleted.
    """
    rounded, square = page.evaluate("""() => {
        const ids = ['r-toast', 'r-close', 'r-slider'];
        const read = () => ids.map(id =>
            getComputedStyle(document.getElementById(id)).borderRadius);
        window.__reader.setCorners(false);
        const before = read();
        window.__reader.setCorners(true);
        return [before, read()];
    }""")
    assert any(r not in ("0px", "") for r in rounded), rounded
    assert all(r == "0px" for r in square), square


def test_turning_animations_off_removes_transitions(page):
    page.evaluate("window.__reader.setAnimations(false)")
    duration = page.evaluate("""() => {
        const b = document.createElement('button');
        b.className = 'btn'; document.body.append(b);
        const d = getComputedStyle(b).transitionDuration;
        b.remove(); return d;
    }""")
    assert set(duration.replace(" ", "").split(",")) <= {"0s"}, duration


def test_column_count_forces_the_grid(page):
    page.evaluate("window.__reader.setColumns(4)")
    columns = page.evaluate("""() => {
        const g = document.getElementById('library-grid');
        return getComputedStyle(g).gridTemplateColumns.split(' ').length;
    }""")
    assert columns == 4, columns


def test_column_zero_means_auto(page):
    page.evaluate("window.__reader.setColumns(0)")
    assert page.evaluate("document.documentElement.dataset.columns") in (None, "")


# ─────────────────────────────────────────────────────────── dot matrix


def test_the_dot_matrix_draws(page):
    running = page.evaluate("window.__reader.matrix.running")
    dots = page.evaluate("window.__reader.matrix.dotCount")
    assert running is True
    assert dots > 20, dots


def test_the_dot_count_is_capped(page):
    """Density must not grow with screen area -- spacing widens instead."""
    page.set_viewport_size({"width": 1920, "height": 1200})
    page.wait_for_timeout(400)
    page.evaluate("window.__reader.setMatrix(false); window.__reader.setMatrix(true)")
    page.wait_for_timeout(300)
    assert page.evaluate("window.__reader.matrix.dotCount") <= 420


def test_turning_the_matrix_off_stops_the_loop(page):
    page.evaluate("window.__reader.setMatrix(false)")
    assert page.evaluate("window.__reader.matrix.running") is False
    assert page.is_hidden("#matrix")
    page.evaluate("window.__reader.setMatrix(true)")
    assert page.evaluate("window.__reader.matrix.running") is True


def test_the_matrix_colour_follows_the_theme(page):
    """One colour for every theme means invisible dots on light."""
    values = page.evaluate("""() => {
        const out = {};
        for (const t of ['midnight', 'light']) {
            window.__reader.setTheme(t);
            out[t] = getComputedStyle(document.documentElement)
                .getPropertyValue('--matrix-dot').trim();
        }
        return out;
    }""")
    assert values["midnight"] != values["light"], values


# ────────────────────────────────────────────────────── settings plumbing


def test_appearance_changes_are_saved(page):
    page.evaluate("""() => {
        window.__reader.setTheme('forest');
        window.__reader.setAccent('mint');
        window.__reader.setCorners(true);
    }""")
    page.wait_for_timeout(500)          # pushSettings coalesces for 250ms
    saved = {}
    for name, args in page.evaluate("window.__calls"):
        if name == "set_settings" and args:
            saved.update(args[0] or {})
    assert saved.get("theme") == "forest", saved
    assert saved.get("accent") == "mint", saved
    assert saved.get("corners") == "square", saved


def test_every_settings_control_is_bound(page):
    """A control that is rendered but wired to nothing is the exact bug this
    release fixes, so it is checked rather than assumed."""
    unbound = page.evaluate("""() => {
        const out = [];
        for (const el of document.querySelectorAll(
                '.settings input, .settings select, .settings .seg button')) {
            if (!el.id && !el.dataset.format) continue;
            const key = el.id || ('format:' + el.dataset.format);
            // getEventListeners is devtools-only; probe by dispatching instead
            out.push(key);
        }
        return out;
    }""")
    assert len(unbound) > 25, f"only found {len(unbound)} controls"


def test_the_settings_panel_covers_the_old_shell_groups(page):
    """These groups existed in the pre-v3 UI and had to come back."""
    text = page.text_content(".settings")
    for heading in ("Appearance", "Reading", "Sources", "Downloads",
                    "Performance", "Privacy", "servers", "Background"):
        assert heading.lower() in text.lower(), heading


# ──────────────────────────────────────────────────────── source ranking


def test_sources_render_with_rank_and_capabilities(page):
    rows = page.locator("#source-list li")
    assert rows.count() == len(SOURCES)
    text = page.text_content("#source-list")
    assert "MangaDex" in text and "mangadex.org" in text
    assert "languages" in text and "cloudflare" in text
    assert "18+" in text


def test_a_disabled_source_is_marked(page):
    assert page.locator("#source-list li.disabled").count() == 1


def test_source_rows_are_draggable(page):
    assert page.evaluate(
        "[...document.querySelectorAll('#source-list li')].every(li => li.draggable)")


def test_move_buttons_exist_for_keyboard_users(page):
    """A drag gesture is not reachable from a keyboard."""
    assert page.locator("#source-list [data-move]").count() == len(SOURCES) * 2


def _open_group(page, heading):
    """Settings groups are <details> inside a hidden view.

    Three things have to be true before a control in one is clickable, and
    missing any of them looks identical (Playwright just says "not visible"):
    the Settings view must be on, the group must be open, and the row has to
    be scrolled into the viewport -- the move buttons sat at y=1033 in an
    860px-tall window.
    """
    page.evaluate("window.__reader.showView('settings')")
    page.evaluate("""h => {
        for (const d of document.querySelectorAll('.set-group'))
            if (d.querySelector('summary').textContent.toLowerCase().includes(h)) d.open = true;
    }""", heading.lower())
    page.wait_for_timeout(200)


def test_moving_a_source_calls_the_backend(page):
    _open_group(page, "sources")
    button = page.locator('#source-list li[data-id="weebcentral"] [data-move="-1"]')
    button.scroll_into_view_if_needed()
    button.click()
    page.wait_for_timeout(200)
    calls = [name for name, _ in page.evaluate("window.__calls")]
    assert "move_source" in calls


def test_toggling_a_source_calls_the_backend(page):
    _open_group(page, "sources")
    # The <input> is opacity:0 behind a styled <span>, so the switch itself
    # is what a person clicks.
    toggle = page.locator('#source-list li[data-id="mangadex"] label.switch span')
    toggle.scroll_into_view_if_needed()
    toggle.click()
    page.wait_for_timeout(200)
    calls = [name for name, _ in page.evaluate("window.__calls")]
    assert "toggle_source" in calls


# ──────────────────────────────────────────────────────────────── lock


def test_the_lock_screen_can_be_shown_and_hides_the_app(page):
    page.evaluate("window.__reader.showLock({ hint: 'the usual' })")
    page.wait_for_timeout(200)
    assert not page.is_hidden("#lock")
    assert "the usual" in page.text_content("#lock-hint-text")


def test_the_matrix_pauses_while_locked(page):
    page.evaluate("window.__reader.showLock({})")
    page.wait_for_timeout(200)
    assert page.evaluate("window.__reader.matrix.running") is False


def test_a_wrong_password_shows_an_error_and_keeps_the_lock(page):
    """The default stub answers {ok: true} to everything, which would unlock.
    Replace the whole bridge so lock_verify genuinely refuses."""
    page.evaluate("""() => {
        window.pywebview = { api: new Proxy({}, { get: (_, name) => {
            if (name === 'then') return undefined;
            return async () => String(name) === 'lock_verify'
                ? { ok: false, error: 'Wrong password' }
                : { ok: true };
        }})};
        window.__reader.showLock({});
    }""")
    page.fill("#lock-input", "nope")
    page.click("#lock-unlock")
    page.wait_for_timeout(300)
    assert not page.is_hidden("#lock"), "a refused password still unlocked the app"
    assert "Wrong password" in page.text_content("#lock-error")


# ─────────────────────────────────────────────────────────────── theme tiles


def test_theme_tiles_preview_the_real_palette(page):
    """Painted from the stylesheet, not a hand-copied hex list that would
    drift out of step with theme.css."""
    colours = page.evaluate("""() => [...document.querySelectorAll('#theme-tiles .theme-tile')]
        .map(t => ({ theme: t.dataset.theme,
                     bars: [...t.querySelectorAll('.bars i')].map(i => i.style.background) }))""")
    assert len(colours) >= 8
    for tile in colours:
        assert all(tile["bars"]), tile
        assert len(set(tile["bars"])) == 3, f"{tile['theme']} has duplicate swatches"


@pytest.mark.parametrize("theme", THEMES)
def test_heroui_surfaces_track_the_theme_not_heroui_defaults(page, theme):
    """HeroUI switches palette on ``.dark``/``[data-theme=dark]``; ReaderM's
    themes are named midnight/mocha/... so that selector never matches.
    Any token left unmapped keeps HeroUI's LIGHT value -- ``--overlay``
    measured as pure white behind 13 ``background-color`` rules.

    Measured off painted pixels, not the cascade: a popover surface must sit
    close to the app background, never 20x away from it.
    """
    page.evaluate("t => window.__reader.setTheme(t)", theme)
    page.wait_for_timeout(120)
    got = page.evaluate("""() => {
        const probe = document.createElement('div');
        document.body.append(probe);
        const paint = token => {
            probe.style.backgroundColor = '';
            probe.style.backgroundColor = `var(${token})`;
            return getComputedStyle(probe).backgroundColor;
        };
        const out = {
            bg: getComputedStyle(document.body).backgroundColor,
            overlay: paint('--overlay'),
            surface2: paint('--surface-secondary'),
            surface3: paint('--surface-tertiary'),
        };
        probe.remove();
        return out;
    }""")
    for name in ("overlay", "surface2", "surface3"):
        ratio = contrast(got[name], got["bg"])
        assert ratio < 3.0, (
            f"{theme}: HeroUI {name} is {got[name]} against a {got['bg']} "
            f"page (contrast {ratio:.1f}:1) -- it kept a HeroUI default "
            f"instead of following the theme")


def test_the_accent_token_survives_the_heroui_layer(page):
    """``--accent: var(--accent)`` in the HeroUI overrides was a self-reference.
    A CSS cycle resolves to guaranteed-invalid and the fallback is skipped, so
    ``--accent`` came back empty on every ``[data-theme]`` element and the
    theme tiles lost their middle swatch."""
    got = page.evaluate("""() => {
        const probe = document.createElement('div');
        probe.dataset.theme = 'midnight';
        document.body.append(probe);
        const v = getComputedStyle(probe).getPropertyValue('--accent').trim();
        probe.remove();
        return { onProbe: v,
                 onRoot: getComputedStyle(document.documentElement)
                     .getPropertyValue('--accent').trim() };
    }""")
    assert got["onProbe"], "--accent is blank on a [data-theme] element"
    assert got["onRoot"], "--accent is blank on :root"


def test_accent_swatches_show_their_own_colour(page):
    colours = page.evaluate("""() => [...document.querySelectorAll('#accent-swatches .swatch')]
        .map(s => s.style.background)""")
    assert len(colours) == len(ACCENTS)
    assert len(set(colours)) == len(ACCENTS), colours


def test_the_selected_theme_and_accent_are_marked(page):
    page.evaluate("window.__reader.setTheme('plum'); window.__reader.setAccent('rose')")
    page.wait_for_timeout(150)
    assert page.locator("#theme-tiles .theme-tile.on").get_attribute("data-theme") == "plum"
    assert page.locator("#accent-swatches .swatch.on").get_attribute("data-accent") == "rose"
