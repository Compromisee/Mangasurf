"""ReaderM 1.0.0, batch 2 — the HeroUI component layer.

HeroUI is React 19 + react-aria + Tailwind 4, which is 168 MB of node_modules.
It is a *build-time* dependency only: `ui/build.mjs` bundles it to a single
static pair of files under `readerm/reader/app/vendor/`, which are committed.
A pip install, a PyInstaller build and an end user all need nothing but
Python.

The app itself stays vanilla. Real HeroUI components are mounted as small
islands over controls that already exist, so the native element remains the
source of truth and the interface still works if the bundle is missing.
"""
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APP = os.path.join(ROOT, "readerm", "reader", "app")
VENDOR = os.path.join(APP, "vendor")
UI = os.path.join(ROOT, "ui")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ───────────────────────────────────────────────────── the shipped bundle


def test_the_bundle_is_committed():
    """The packaged app must build without Node."""
    assert os.path.isfile(os.path.join(VENDOR, "heroui.js"))
    assert os.path.isfile(os.path.join(VENDOR, "heroui.css"))


def test_the_bundle_is_self_contained():
    """One file, no bare specifiers, no import map to resolve."""
    source = read(os.path.join(VENDOR, "heroui.js"))
    assert "from\"react\"" not in source
    assert "from \"react\"" not in source
    assert "require(" not in source or "typeof require" in source


def test_the_bundle_publishes_the_widget_api():
    source = read(os.path.join(VENDOR, "heroui.js"))
    assert "ReaderMUI" in source


def test_the_stylesheet_carries_component_styles():
    """A first attempt ran Tailwind over the source and emitted only
    utilities -- measured zero occurrences of `.slider`, `.switch`, `.chip`,
    so components mounted with correct markup and no styling at all."""
    css = read(os.path.join(VENDOR, "heroui.css"))
    # Anchored to a rule opening, so renaming the class is caught -- a bare
    # ".slider" also matches ".sliderX".
    for cls in ("slider", "switch", "chip", "tabs", "select"):
        # the rule that *defines* the component, not a descendant selector
        assert re.search(rf"\.{cls}\s*[,{{]", css), cls
    assert len(css) > 200_000, "the component sheet is suspiciously small"


def test_the_stylesheet_maps_app_tokens_onto_heroui():
    """So a HeroUI slider follows the user's accent instead of shipping a
    second theme system."""
    css = read(os.path.join(VENDOR, "heroui.css"))
    assert "--primary: var(--accent" in css
    assert "--background: var(--bg" in css


def test_no_token_mapping_references_itself():
    """A self-referential custom property is a *cycle*, and a cycle resolves
    to the guaranteed-invalid value -- the fallback is NOT applied.

    Shipped in the first HeroUI build as ``--accent: var(--accent, #7aa2f7)``
    and ``--border: var(--border, ...)``, because those two names happen to be
    spelled identically in HeroUI and in theme.css. Measured in Chromium,
    ``--accent`` then read back as the empty string on every element carrying
    ``[data-theme]``, which blanked the middle swatch of every theme tile.
    Where the names already agree the correct mapping is no mapping at all.

    Written as a general rule rather than a check for those two names, so the
    next accidental collision is caught too.
    """
    css = read(os.path.join(VENDOR, "heroui.css"))
    # Strip comments *before* slicing: the override block is introduced by a
    # comment that quotes the offending declaration verbatim, and scanning it
    # as CSS made this test fail on its own documentation.
    overrides = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    overrides = overrides[overrides.index(":root,\n[data-theme] {"):]
    cycles = []
    for prop, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", overrides):
        if prop in re.findall(r"var\(\s*(--[a-z0-9-]+)", value):
            cycles.append(f"{prop}: {value.strip()}")
    assert cycles == [], "self-referential custom properties: " + "; ".join(cycles)


def test_heroui_surfaces_follow_the_dark_theme():
    """HeroUI swaps palette on ``.dark``/``[data-theme=dark]``. ReaderM's
    themes are named midnight/mocha/forest/..., so that selector never
    matches and every token we do not map keeps its LIGHT value on a dark UI.

    Measured before the fix: ``--overlay`` painted ``oklch(1 0 0)`` -- pure
    white -- behind 13 ``background-color`` declarations.
    """
    css = read(os.path.join(VENDOR, "heroui.css"))
    overrides = css[css.index("ReaderM overrides"):]
    for token in ("--overlay", "--surface-secondary", "--surface-tertiary",
                  "--muted"):
        assert re.search(rf"{token}\s*:\s*var\(", overrides), token


def test_node_modules_is_not_committed():
    """Asked of git itself: a commented-out line still "appears" in the file."""
    out = subprocess.run(["git", "check-ignore", "-q", "ui/node_modules"],
                         cwd=ROOT, capture_output=True)
    assert out.returncode == 0, "ui/node_modules is not ignored"
    tracked = subprocess.run(["git", "ls-files", "ui/node_modules"],
                             cwd=ROOT, capture_output=True, text=True)
    assert tracked.stdout.strip() == "", "node_modules is tracked"


def test_the_build_writes_into_the_package():
    build = read(os.path.join(UI, "build.mjs"))
    assert "readerm/reader/app/vendor" in build


def test_the_build_inlines_everything():
    build = read(os.path.join(UI, "build.mjs"))
    assert "bundle: true" in build
    assert 'format: "iife"' in build


# ───────────────────────────────────────────────────── serving the bundle


@pytest.fixture()
def server():
    from mangasurf.reader.assets import AssetServer

    srv = AssetServer()
    srv.start()
    yield srv
    srv.stop()


def fetch(url):
    import urllib.error
    import urllib.request

    try:
        response = urllib.request.urlopen(url, timeout=10)
        return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


@pytest.mark.parametrize("path", ["/vendor/heroui.js", "/vendor/heroui.css"])
def test_the_page_can_load_the_bundle_by_relative_url(server, path):
    """index.html is served from "/", so `./vendor/heroui.js` resolves to
    `/vendor/heroui.js`. The root shortcut only matched single-segment paths,
    so the bundle 404'd and window.ReaderMUI was undefined."""
    status, body, headers = fetch(f"http://127.0.0.1:{server.port}{path}"
                                  f"?t={server.token}")
    assert status == 200, path
    assert len(body) > 5000, path


def test_the_bundle_is_served_with_the_right_type(server):
    _, _, headers = fetch(f"http://127.0.0.1:{server.port}"
                          f"/vendor/heroui.js?t={server.token}")
    assert headers["Content-Type"].startswith("text/javascript")


def raw_get(port, target, token):
    """Send a request line verbatim.

    urllib collapses `../` client-side, so a traversal sent through it never
    reaches the server at all -- the test passed with *both* guards removed.
    A raw socket is the only way to prove the guard does anything.
    """
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(
            f"GET {target}?t={token} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n".encode())
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


@pytest.mark.parametrize("attack", [
    "/../assets.py",
    "/vendor/../../assets.py",
    "/vendor/%2e%2e%2f%2e%2e%2fassets.py",
    "/app/../assets.py",
])
def test_the_deeper_shortcut_still_refuses_traversal(server, attack):
    """Widening the root shortcut to any depth must not become a way out.

    Two guards cover this, deliberately: the shortcut checks the candidate
    before using it, and `_asset` checks again. Removing either alone is
    still safe -- removing *both* was measured returning 200 and leaking
    assets.py, so the redundancy is real rather than decorative.
    """
    response = raw_get(server.port, attack, server.token)
    head = response.split(b"\r\n", 1)[0]
    assert b" 200 " not in head, f"{attack} -> {head!r}"
    assert b"AssetServer" not in response, f"{attack} leaked the module"


def test_the_page_links_the_bundle():
    html = read(os.path.join(APP, "index.html"))
    assert "./vendor/heroui.css" in html
    assert "./vendor/heroui.js" in html
    # before app.js, so window.ReaderMUI exists when the interface mounts
    assert html.index("vendor/heroui.js") < html.index('src="./app.js"')


# ─────────────────────────────────────────────── the widget source itself


def test_the_widgets_use_the_compound_api():
    """HeroUI v3 is compound: `Slider` is `SliderRoot` and renders nothing
    alone. A first attempt mounted only the progress bar and logged
    "cannot be rendered outside a collection"."""
    source = read(os.path.join(UI, "src", "widgets.jsx"))
    # Scoped per widget: a bare file-wide search still passes when one
    # component loses its parts but another keeps the same import.
    slider = source[source.index("function ManagedSlider"):]
    slider = slider[:slider.index("\n}")]
    for part in ("SliderTrack", "SliderFill", "SliderThumb"):
        assert part in slider, f"slider lost {part}"
    tabs = source[source.index("function ManagedTabs"):]
    tabs = tabs[:tabs.index("\n}")]
    assert "TabList" in tabs
    switch = source[source.index("function ManagedSwitch"):]
    switch = switch[:switch.index("\n}")]
    assert "SwitchControl" in switch
    select = source[source.index("function ManagedSelect"):]
    select = select[:select.index("\n}")]
    for part in ("SelectTrigger", "SelectPopover"):
        assert part in select, f"select lost {part}"


def test_options_use_listboxitem():
    """v3 has no SelectItem or AutocompleteItem."""
    source = read(os.path.join(UI, "src", "widgets.jsx"))
    # Skip comments: the file explains *why* those names are wrong, so a bare
    # substring search matched its own explanation.
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith(("*", "/*", "//")))
    assert "ListBoxItem" in code
    assert "SelectItem" not in code
    assert "AutocompleteItem" not in code


def test_chips_are_keyboard_reachable():
    """Chip is presentational in v3 -- it renders a <span>, so on its own it
    cannot be focused. A genre filter has to be."""
    source = read(os.path.join(UI, "src", "widgets.jsx"))
    block = source[source.index("function ChipRow"):]
    block = block[:block.index("\n}")]
    assert "<button" in block
    assert "aria-pressed" in block


def test_roots_are_reused_not_leaked():
    """createRoot per call warns loudly and leaks over a long session."""
    source = read(os.path.join(UI, "src", "widgets.jsx"))
    assert "WeakMap" in source
    block = source[source.index("function mount("):]
    block = block[:block.index("\n}")]
    assert "roots.get" in block


# ───────────────────────────────────────────────────── islands in the app


def test_the_app_mounts_islands():
    """Checked at the call site inside boot(): the name also appears in the
    definition and in the test-export block, so a bare search passes even
    when nothing calls it."""
    source = read(os.path.join(APP, "app.js"))
    boot = source[source.index("async function boot()"):]
    boot = boot[:boot.index("\n}")]
    assert "mountHeroIslands()" in boot
    assert "heroSelect(" in source


def test_the_native_control_stays_the_source_of_truth():
    """The app reads and writes the <select> exactly as before; the island
    only mirrors it."""
    source = read(os.path.join(APP, "app.js"))
    block = source[source.index("function heroSelect"):]
    block = block[:block.index("\n}")]
    assert "native.value = value" in block
    assert "dispatchEvent(new Event('change'" in block


def test_islands_degrade_without_the_bundle():
    """If the bundle is missing, the plain control must keep working."""
    source = read(os.path.join(APP, "app.js"))
    block = source[source.index("function heroSelect"):]
    block = block[:block.index("\n}")]
    assert "if (!native || !ui) return" in block
    hidden = read(os.path.join(APP, "style.css"))
    assert ".rm-hidden-native" in hidden, "the native is only hidden once mounted"


def test_rebuilt_option_lists_are_picked_up():
    """Sources and genres arrive after boot, so the island has to re-render."""
    source = read(os.path.join(APP, "app.js"))
    block = source[source.index("function heroSelect"):]
    block = block[:block.index("\n}")]
    assert "MutationObserver" in block


# ─────────────────────────────────── hotlink-protected hosts (extended)


HOSTS = [
    ("https://uploads.mangadex.org/covers/a/b.jpg", True),
    ("https://manhuatop.org/wp-content/uploads/x.jpg", True),
    ("https://webtoon-phinf.pstatic.net/2025/x.jpg", True),
    ("https://www.webtoons.com/thumb.jpg", True),
    ("https://asuracomic.net/cover.jpg", False),
    ("https://cdn.example.com/x.png", False),
]


@pytest.mark.parametrize("url,proxied", HOSTS)
def test_blocked_hosts_are_proxied(url, proxied):
    """Found by watching what the browser actually blocked --
    ERR_BLOCKED_BY_RESPONSE.NotSameOrigin and ERR_BLOCKED_BY_ORB -- not by
    guessing which sites hotlink-protect."""
    import shutil

    if not shutil.which("node"):
        pytest.skip("node is not available")
    source = read(os.path.join(APP, "app.js"))
    start = source.index("const HOTLINK_PROTECTED = new RegExp(")
    end = source.index("'i')", start) + 4
    script = (source[start:end] + ";\n"
              + f"const u = {json.dumps(url)};\n"
              + "let h=''; try { h = new URL(u).hostname } catch {}\n"
              + "console.log(JSON.stringify(h ? HOTLINK_PROTECTED.test(h) : false));")
    out = subprocess.run(["node", "-e", script], capture_output=True,
                         text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) is proxied
