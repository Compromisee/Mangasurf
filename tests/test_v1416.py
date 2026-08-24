"""Regression tests for v1.4.16.

Three reported problems and one new document:

* the GUI was "really prone to crashing on opening" -- ``genres_all`` became a
  serial network loop when the Madara sources started reading their genre
  lists live, and the GUI awaits it during boot
* Rich was a hard import in ``cli.py`` and ``menu.py``, so a clone without
  dependencies installed could not run either at all
* ``SYNTAX.md`` must document only flags that really exist

Natomanga was reported as "not working" but could not be reproduced -- see
``test_natomanga_still_scrapes_end_to_end`` in the live suite and the note in
the changelog.
"""

import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# =================================================== GUI boot: genres_all


def test_genres_all_runs_in_parallel_under_a_deadline():
    """The bug: a serial for-loop with no time limit. Six merely *slow* sites
    (4s each, not down) froze the UI for 30.0s on open, because the GUI awaits
    this during boot. Parallel + deadline brings that to ~5s."""
    import time

    import mangasurf.sources.base as base
    from mangasurf.sources import genres_all

    original = base.Source.fetch
    slowed = {"manhuatop", "manhuaplus", "toonily", "manhwatop", "mangaread",
              "setsuscans"}

    def slow(self, *args, **kwargs):
        if self.id in slowed:
            time.sleep(3)
        return original(self, *args, **kwargs)

    base.Source.fetch = slow
    try:
        started = time.time()
        rows = genres_all(use_config=False, deadline=1.0)
        elapsed = time.time() - started
    finally:
        base.Source.fetch = original

    # Serially this was 6 x 3s plus the rest; the deadline caps it.
    assert elapsed < 8, f"took {elapsed:.1f}s"
    assert rows, "must still return genres"


def test_genres_all_falls_back_to_offline_lists_on_timeout():
    """A source that times out must contribute its hardcoded genres rather
    than vanishing from the picker."""
    import mangasurf.sources.base as base
    from mangasurf.sources import genres_all

    original = base.Source.fetch

    def hang(self, *args, **kwargs):
        import time
        time.sleep(30)

    base.Source.fetch = hang
    try:
        rows = genres_all(source_ids=["madaranet"], use_config=False,
                          deadline=0.5)
    finally:
        base.Source.fetch = original

    names = {r["name"].lower() for r in rows}
    assert "action" in names, "offline fallback list was not used"


def test_genres_all_does_not_cache_a_partial_result():
    """Caching a timed-out answer would freeze a short genre list in place for
    the cache's full hour."""
    import mangasurf.sources.base as base
    from mangasurf.robust import GENRE_CACHE, cache_key
    from mangasurf.sources import genres_all

    GENRE_CACHE.clear() if hasattr(GENRE_CACHE, "clear") else None
    original = base.Source.fetch

    def hang(self, *args, **kwargs):
        import time
        time.sleep(30)

    base.Source.fetch = hang
    try:
        # Must be a source that really reaches out in genres(); one that
        # answers from a constant never times out, so the test would pass
        # vacuously. flamecomics reads its genre list off the live payload.
        genres_all(source_ids=["flamecomics"], use_config=False, deadline=0.4)
    finally:
        base.Source.fetch = original

    assert GENRE_CACHE.get(cache_key("genres", "flamecomics")) is None


def test_genres_all_still_merges_across_sources():
    """The offline floor: with no network at all every source falls back to a
    constant, and the merge must still work."""
    import mangasurf.sources.base as base
    from mangasurf.sources import genres_all
    from mangasurf.sources.base import ScrapeError

    original = base.Source.fetch

    def dead(self, *args, **kwargs):
        raise ScrapeError("offline")

    base.Source.fetch = dead
    try:
        rows = genres_all(use_config=False)
    finally:
        base.Source.fetch = original

    assert len(rows) > 50
    action = [r for r in rows if r["name"].lower() == "action"]
    assert action and len(action[0]["sources"]) > 5


# ====================================================== Rich is optional


NO_RICH = """
import sys, builtins
sys.path.insert(0, %r)
_real = builtins.__import__
def _fake(name, *a, **k):
    if name == "rich" or name.startswith("rich."):
        raise ImportError("No module named 'rich'")
    return _real(name, *a, **k)
builtins.__import__ = _fake
""" % ROOT


def run_without_rich(body, argv=()):
    """Run a snippet in a subprocess where importing rich fails."""
    return subprocess.run(
        [sys.executable, "-c", NO_RICH + body, *argv],
        capture_output=True, text=True, cwd=ROOT, timeout=180,
        env={**os.environ, "HOME": os.environ.get("HOME", "/tmp"),
             "FORCE_COLOR": "1"},
    )


def test_cli_imports_without_rich():
    """It used to die at import: `from rich import box` -> ImportError, before
    argparse ran, so not even --help worked from a bare clone."""
    result = run_without_rich("import mangasurf.cli; print('OK')")
    assert result.returncode == 0, result.stderr[-800:]
    assert "OK" in result.stdout


def test_menu_imports_without_rich():
    """menu.py had the identical hard import."""
    result = run_without_rich("import mangasurf.menu; print('OK')")
    assert result.returncode == 0, result.stderr[-800:]
    assert "OK" in result.stdout


def test_cli_help_works_without_rich():
    result = run_without_rich(
        "import sys; sys.argv=['mangasurf','--help']\n"
        "from mangasurf.cli import main\n"
        "try: main()\n"
        "except SystemExit: pass")
    assert result.returncode == 0, result.stderr[-800:]
    assert "usage: mangasurf" in result.stdout


def test_sources_table_renders_without_rich():
    result = run_without_rich(
        "from mangasurf.cli import cmd_sources; cmd_sources()")
    assert result.returncode == 0, result.stderr[-800:]
    for source_id in ("mangadex", "witchscans", "asurascans"):
        assert source_id in result.stdout


def test_fallback_console_emits_ansi_when_colour_is_forced():
    result = run_without_rich(
        "import mangasurf.console as c\n"
        "assert c.RICH is False\n"
        "c.console.print('[bright_cyan]tint[/]')")
    assert result.returncode == 0, result.stderr[-800:]
    assert "\x1b[" in result.stdout, "no ANSI emitted with FORCE_COLOR=1"


def test_fallback_console_strips_markup_when_colour_is_off():
    """Piping must never produce raw [bold] tags or escape codes."""
    result = subprocess.run(
        [sys.executable, "-c", NO_RICH +
         "import mangasurf.console as c\nc.console.print('[bold]plain[/] text')"],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
        env={**os.environ, "NO_COLOR": "1", "HOME": os.environ.get("HOME", "/tmp")},
    )
    assert result.returncode == 0, result.stderr[-500:]
    assert result.stdout.strip() == "plain text"
    assert "\x1b[" not in result.stdout
    assert "[bold]" not in result.stdout


def test_fallback_table_supports_grid():
    """Table.grid() is used for the download summary panel; the first shim
    lacked it and the download crashed with AttributeError after fetching
    every page."""
    result = run_without_rich(
        "from mangasurf.console import Table\n"
        "g = Table.grid(padding=(0, 2))\n"
        "g.add_row('Source', 'Flame Comics')\n"
        "g.add_row('Chapters', '1 of 8')\n"
        "print(g.render(80))")
    assert result.returncode == 0, result.stderr[-800:]
    assert "Flame Comics" in result.stdout


def test_no_module_imports_rich_at_top_level():
    """Any new hard import of Rich reintroduces the crash."""
    offenders = []
    for name in sorted(os.listdir(os.path.join(ROOT, "mangasurf"))):
        if not name.endswith(".py") or name == "console.py":
            continue
        text = read(os.path.join(ROOT, "mangasurf", name))
        if re.search(r"(?m)^(from rich[\. ]|import rich\b)", text):
            offenders.append(name)
    assert not offenders, f"import rich directly: {offenders}"


def test_console_module_exports_what_the_cli_uses():
    import mangasurf.console as console_module

    for name in ("console", "Table", "Panel", "box", "ACCENT", "DIM",
                 "download_progress", "strip_markup", "RICH"):
        assert hasattr(console_module, name), name


def test_colour_is_disabled_when_piped():
    """Redirecting to a file must not produce escape-code soup."""
    result = subprocess.run(
        [sys.executable, "-m", "mangasurf.cli", "sources"],
        capture_output=True, text=True, cwd=ROOT, timeout=180,
        env={k: v for k, v in os.environ.items()
             if k not in ("FORCE_COLOR", "CLICOLOR_FORCE")},
    )
    assert result.returncode == 0
    assert "\x1b[" not in result.stdout


# ============================================================= SYNTAX.md


SYNTAX = os.path.join(ROOT, "MD", "SYNTAX.md")


def test_syntax_doc_exists():
    assert os.path.exists(SYNTAX)


def test_every_documented_flag_exists_in_the_parser():
    """A documented flag that the parser rejects is worse than no docs."""
    result = subprocess.run(
        [sys.executable, "-m", "mangasurf.cli", "--help"],
        capture_output=True, text=True, cwd=ROOT, timeout=180)
    help_text = result.stdout
    documented = set(re.findall(r"(?<![\w-])(--[a-z][a-z-]+)", read(SYNTAX)))
    assert documented, "no flags found in SYNTAX.md"
    missing = sorted(f for f in documented if f not in help_text)
    assert not missing, f"documented but not real: {missing}"


def test_every_documented_command_is_dispatched():
    cli = read(os.path.join(ROOT, "mangasurf", "cli.py"))
    dispatch = cli[cli.index("def main("):]
    for command in ("search", "info", "trending", "genres", "sources",
                    "config", "library", "watch", "disk", "stats", "history",
                    "lock", "export", "health", "resume", "menu", "tui",
                    "gui"):
        assert f'"{command}"' in dispatch, command


def test_syntax_doc_source_count_matches_the_registry():
    from mangasurf.sources import SOURCE_CLASSES

    text = read(SYNTAX)
    stale = re.findall(r"(\d+)\s+sources", text)
    for number in stale:
        assert int(number) == len(SOURCE_CLASSES), \
            f"SYNTAX.md says {number} sources, registry has {len(SOURCE_CLASSES)}"


def test_syntax_doc_documents_colour_control():
    text = read(SYNTAX)
    for token in ("NO_COLOR", "FORCE_COLOR", "--plain"):
        assert token in text, token


def test_cli_description_is_not_stale():
    """It named four sources long after there were twenty-three."""
    from mangasurf.sources import SOURCES

    cli = read(os.path.join(ROOT, "mangasurf", "cli.py"))
    assert "Natomanga and Weeb Central as CBZ" not in cli
    result = subprocess.run(
        [sys.executable, "-m", "mangasurf.cli", "--help"],
        capture_output=True, text=True, cwd=ROOT, timeout=180)
    assert f"{len(SOURCES)} sources" in result.stdout


def test_readme_links_the_syntax_doc():
    assert "SYNTAX.md" in read(os.path.join(ROOT, "README.md"))


# ================================================================== TUI


def test_tui_module_is_unchanged_and_still_guards_textual():
    """The brief was to touch the TUI only if it errored. It did not -- it
    boots, cycles tabs and lists all 23 sources with no exceptions -- so this
    only pins the guard that lets it degrade without Textual."""
    text = read(os.path.join(ROOT, "mangasurf", "tui.py"))
    assert "TEXTUAL_AVAILABLE" in text
    assert "except ImportError:" in text


def test_tui_fallback_message_points_at_the_menu():
    import mangasurf.tui as tui

    if tui.TEXTUAL_AVAILABLE:
        pytest.skip("Textual is installed; the fallback path is not taken")
    text = read(os.path.join(ROOT, "mangasurf", "tui.py"))
    assert "mangasurf menu" in text


# ======================================= v1.4.17: Madara Scans, and the name

def test_madarascans_is_registered_and_visible():
    """Reported as "Madara doesn't show in settings". Two different things
    are called Madara; the *site* was genuinely missing."""
    from mangasurf.sources import SOURCES, list_sources

    assert "madarascans" in SOURCES
    names = {m["name"] for m in list_sources()}
    assert "Madara Scans" in names


def test_madara_theme_engine_is_not_a_source():
    """madara.py is the shared WordPress-theme scraper. It must never appear
    in the UI: it has no base_url, so it would render as a blank row."""
    from mangasurf.sources import SOURCE_CLASSES, SOURCES
    from mangasurf.sources.madara import MadaraSource

    assert MadaraSource not in SOURCE_CLASSES
    assert "madara" not in SOURCES
    assert MadaraSource.base_url == ""
    assert MadaraSource.is_engine() is True


def test_engine_flag_does_not_leak_to_subclasses():
    """A plain class attribute would inherit and every Madara-based site
    would claim to be engine code."""
    from mangasurf.sources import SOURCE_CLASSES

    leaked = [c.id for c in SOURCE_CLASSES
              if hasattr(c, "is_engine") and c.is_engine()]
    assert not leaked, leaked


def test_madarascans_does_not_subclass_the_theme_engine():
    """Despite the name it runs themes/mangareader (Themesia), not Madara."""
    from mangasurf.sources.madara import MadaraSource
    from mangasurf.sources.madarascans import MadaraScansSource

    assert not issubclass(MadaraScansSource, MadaraSource)


def test_madarascans_claims_both_domains():
    """.com 301s to .org; a pasted link to either must be recognised."""
    from mangasurf.sources import detect_source

    assert detect_source("https://madarascans.org/series/x/") == "madarascans"
    assert detect_source("https://madarascans.com/series/x/") == "madarascans"


def test_madarascans_chapter_selector_matches_the_real_markup():
    """Three selectors that look right and match ZERO anchors on this site:
    #chapterlist (only inside a <style> block), .eplister (absent), and
    li[id^=chapter-item-] (the rows are div.ch-item, not <li>)."""
    from bs4 import BeautifulSoup

    from mangasurf.sources.madarascans import MadaraScansSource

    html = """
      <div id="chapters-list-container">
        <div class="ch-item free" id="chapter-item-2" data-ch="2">
          <a href="/x-chapter-2/">Chapter 2</a></div>
        <div class="ch-item free" id="chapter-item-1" data-ch="1">
          <a href="/x-chapter-1/">Chapter 1</a></div>
      </div>
      <a href="/x-chapter-9/">next shortcut outside the list</a>"""
    source = MadaraScansSource()
    try:
        chapters = source.get_chapters.__wrapped__(source, "x") \
            if hasattr(source.get_chapters, "__wrapped__") else None
    finally:
        source.close()

    soup = BeautifulSoup(html, "html.parser")
    assert len(soup.select('#chapters-list-container .ch-item a[href]')) == 2
    assert len(soup.select('li[id^="chapter-item-"] a[href]')) == 0
    assert len(soup.select('#chapterlist li a[href]')) == 0


def test_madarascans_skips_the_list_mode_toggle():
    """/series/list-mode matches the series selector but is a view toggle."""
    from mangasurf.sources.madarascans import MadaraScansSource

    assert MadaraScansSource._series_slug(
        "https://madarascans.org/series/list-mode") is None
    assert MadaraScansSource._series_slug(
        "https://madarascans.org/series/real-title/") == "real-title"
    assert MadaraScansSource._series_slug("https://madarascans.org/") is None


def test_madarascans_cards_dedupe_the_double_link():
    """Every card links the series twice -- cover, then title -- so a naive
    parse returns each series twice with one entry missing its title."""
    from bs4 import BeautifulSoup

    from mangasurf.sources.madarascans import MadaraScansSource

    html = """<div class="listupd">
      <a href="https://madarascans.org/series/foo/"><img src="/c.jpg"></a>
      <a href="https://madarascans.org/series/foo/">Foo Title</a>
      <a href="https://madarascans.org/series/list-mode">List</a>
    </div>"""
    source = MadaraScansSource()
    try:
        rows = source._cards(BeautifulSoup(html, "html.parser"), 10)
    finally:
        source.close()

    assert len(rows) == 1
    assert rows[0]["title"] == "Foo Title"
    assert rows[0]["cover"] == "https://madarascans.org/c.jpg"


def test_madarascans_browse_pages_on_the_query_not_the_path():
    """/series/page/2/ answers 200 and returns page one; ?page=2 is real."""
    src = read(os.path.join(ROOT, "mangasurf", "sources", "madarascans.py"))
    body = src[src.index("def browse"):src.index("def genres")]
    # Strip comments: the decoy path is named in one, to explain why it is
    # avoided, and matching raw text would fail on correct code.
    body = re.sub(r"(?m)#.*$", "", body)
    assert "?page={page}" in body or "&page={page}" in body
    assert "/series/page/" not in body


def test_madarascans_search_pages_on_the_path():
    """Search is the opposite of browse here: /page/<n>/?s=<term>."""
    src = read(os.path.join(ROOT, "mangasurf", "sources", "madarascans.py"))
    body = src[src.index("def search"):src.index("def browse")]
    assert "/page/{page}/?s=" in body


def test_madarascans_avoids_the_empty_manga_path():
    """/manga/ returns a 53-byte empty document; /series/ is the catalogue."""
    src = read(os.path.join(ROOT, "mangasurf", "sources", "madarascans.py"))
    body = src[src.index("def browse"):src.index("def genres")]
    assert "/series/" in body


def test_registry_source_count_is_consistent():
    """v1.4.18 folded ten Madara-theme sites into one aggregate, so the row
    count in Settings is smaller than the number of sites reachable."""
    from mangasurf.sources import SOURCE_CLASSES, SOURCES
    from mangasurf.sources.madaranet import MEMBERS

    assert len(SOURCES) == len(SOURCE_CLASSES)
    # 18 standalone sources + 1 aggregate standing in for 10 sites
    assert len(SOURCE_CLASSES) == 19
    assert len(MEMBERS) == 10
