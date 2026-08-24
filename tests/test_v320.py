"""v3.2.0 — the ReaderM rename, the data-dir migration, and the Stats tab.

The rename is the risky part: an existing MangaDL install keeps its library,
settings, bookmarks, reading positions and password in ``~/.mangadl``, and a
renamed build that ignored them would look exactly like data loss. So most of
what follows drives ``paths.migrate`` against a realistic old install rather
than asserting on source text.
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

APP = os.path.join(ROOT, "readerm", "reader", "app")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ───────────────────────────────────────────────────────────────── rename


def test_the_package_is_called_readerm():
    assert os.path.isdir(os.path.join(ROOT, "readerm"))
    assert not os.path.exists(os.path.join(ROOT, "mangadl"))


def test_the_spec_was_renamed():
    assert os.path.isfile(os.path.join(ROOT, "ReaderM.spec"))
    assert not os.path.exists(os.path.join(ROOT, "MangaDL.spec"))


def test_the_console_scripts_are_renamed():
    pyproject = read(os.path.join(ROOT, "pyproject.toml"))
    assert 'readerm = "mangasurf.cli:main"' in pyproject
    assert 'readerm-gui = "mangasurf.gui:run_gui"' in pyproject
    assert 'readerm-tui = "mangasurf.tui:run_tui"' in pyproject


def test_no_shipped_file_still_says_the_old_name():
    """Two legitimate exceptions: the upstream fork URL, and the migration
    code and its tests, which have to name the folder they read from."""
    offenders = []
    skip = {".git", "__pycache__", "build", "dist", "node_modules", "foliate",
            "tests"}
    allowed = {os.path.join(ROOT, "readerm", "paths.py")}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for name in filenames:
            if os.path.splitext(name)[1] not in {".py", ".js", ".css", ".html",
                                                 ".toml", ".spec", ".txt"}:
                continue
            path = os.path.join(dirpath, name)
            if path in allowed:
                continue
            try:
                text = read(path)
            except (UnicodeDecodeError, OSError):
                continue
            comment_starts = ("#", "*", "/*", "//", '"""', "'" * 3)
            for line in text.splitlines():
                stripped = line.strip()
                if "ReaderM" in line:              # the upstream fork URL
                    continue
                # Comments may name the old app: the migration path has to
                # explain which folder it reads from, and why.
                if stripped.startswith(comment_starts):
                    continue
                if re.search(r"\bmangadl\b|\bMangaDL\b", line):
                    offenders.append(f"{os.path.relpath(path, ROOT)}: {stripped[:70]}")
    assert offenders == [], offenders


def test_the_module_and_the_package_metadata_agree():
    """Was `startswith("3.2")`, which the 1.0.0 renumbering invalidated.
    The real risk is bumping one of the two places and forgetting the
    other, so that is what is checked now."""
    import re

    import readerm

    pyproject = open(os.path.join(ROOT, "pyproject.toml"),
                     encoding="utf-8").read()
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert declared == mangasurf.__version__


# ──────────────────────────────────────────────────────────── data folder


def test_the_data_folder_is_dot_readerm():
    from readerm import paths

    assert paths.DIR_NAME == ".readerm"
    assert paths.data_dir().endswith(".readerm")


def test_every_module_shares_one_data_folder():
    """Eight modules used to compute the path independently, which is why the
    rename had eight chances to go wrong. They all call paths.ensure() now.

    Checked in the source rather than by comparing the imported constants:
    those are captured at import time, and other tests in the suite move HOME
    around, so the live values legitimately differ by whenever a module was
    first imported.
    """
    users = ("config.py", "features.py", "library.py", "logs.py",
             "passlock.py", "singleton.py", "tracking.py")
    for name in users:
        source = read(os.path.join(ROOT, "readerm", name))
        assert "_ensure_data_dir()" in source, name
        assert 'expanduser("~"), ".readerm"' not in source, f"{name} still rolls its own"
    reader_api = read(os.path.join(ROOT, "readerm", "reader", "api.py"))
    assert "_ensure_data_dir()" in reader_api


@pytest.fixture()
def old_install(tmp_path, monkeypatch):
    """A realistic ~/.mangadl, with noise that must not be carried over."""
    home = tmp_path / "home"
    old = home / ".mangadl"
    old.mkdir(parents=True)
    (old / "library.json").write_text(json.dumps({
        "http://x/solo": {"title": "Solo Leveling", "url": "http://x/solo",
                          "source": "mangadex", "chapters": {"Chapter 1": {"pages": 12}}}}))
    (old / "config.json").write_text(json.dumps({"theme": "plum", "accent": "rose"}))
    (old / "bookmarks.json").write_text(json.dumps([{"title": "One Piece"}]))
    (old / "reading.json").write_text(json.dumps({"/d/c1": {"index": 5, "fraction": 0.42}}))
    (old / "lock.json").write_text(json.dumps({"hash": "abc", "hint": "the usual"}))
    (old / "stats.json").write_text(json.dumps({"totals": {"chapters": 431}}))
    (old / "instance.json").write_text(json.dumps({"pid": 4242}))
    (old / "mangasurf.log").write_text("old log")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(home)))
    return home


def test_an_existing_install_is_migrated(old_install):
    from readerm import paths

    result = paths.migrate()
    assert result["migrated"] is True
    assert "library.json" in result["files"]
    assert "config.json" in result["files"]


def test_the_library_survives_the_rename(old_install):
    from readerm import paths

    paths.migrate()
    moved = json.loads((old_install / ".readerm" / "library.json").read_text())
    assert [e["title"] for e in moved.values()] == ["Solo Leveling"]


def test_settings_survive_the_rename(old_install):
    from readerm import paths

    paths.migrate()
    config = json.loads((old_install / ".readerm" / "config.json").read_text())
    assert config["theme"] == "plum"
    assert config["accent"] == "rose"


@pytest.mark.parametrize("name", ["library.json", "config.json", "bookmarks.json",
                                  "reading.json", "lock.json", "stats.json"])
def test_each_kind_of_state_is_carried_over(old_install, name):
    from readerm import paths

    paths.migrate()
    assert (old_install / ".readerm" / name).is_file(), name


def test_per_install_noise_is_left_behind(old_install):
    """instance.json is a live singleton handshake and logs describe a build
    that is no longer running."""
    from readerm import paths

    paths.migrate()
    new = old_install / ".readerm"
    assert not (new / "instance.json").exists()
    assert not (new / "mangasurf.log").exists()


def test_the_old_folder_is_kept_as_a_backup(old_install):
    """Copied, not moved, so downgrading still works."""
    from readerm import paths

    paths.migrate()
    assert (old_install / ".mangadl" / "library.json").is_file()


def test_a_per_file_guard_protects_live_state(old_install):
    """Two independent guards stop a clobber: the directory check, and a
    per-file `exists` test. The second one matters if the folder is ever
    created before migration runs -- which `ensure()` can do.
    """
    from readerm import paths

    new = old_install / ".readerm"
    new.mkdir()
    (new / "config.json").write_text(json.dumps({"theme": "ocean"}))
    paths.migrate(force=False)
    assert json.loads((new / "config.json").read_text())["theme"] == "ocean"


def test_a_second_launch_does_not_re_copy(old_install):
    from readerm import paths

    paths.migrate()
    target = old_install / ".readerm" / "config.json"
    target.write_text(json.dumps({"theme": "ocean"}))
    again = paths.migrate()
    assert again["migrated"] is False
    assert json.loads(target.read_text())["theme"] == "ocean", "migration clobbered live settings"


def test_a_fresh_machine_just_creates_the_folder(tmp_path, monkeypatch):
    home = tmp_path / "fresh"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(home)))
    from readerm import paths

    result = paths.migrate()
    assert result["migrated"] is False
    assert result["reason"] == "no previous install"
    assert os.path.isdir(paths.ensure())


def test_a_failed_migration_does_not_stop_the_app(old_install, monkeypatch):
    """An empty library is recoverable; a crash loop on launch is not."""
    import shutil

    from readerm import paths

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", boom)
    result = paths.migrate()
    assert result["migrated"] is False
    assert "copy failed" in result["reason"]


# ─────────────────────────────────────────────────────────── settings UI


def test_every_backend_setting_has_a_control():
    """A setting that saves and loads but has no control is exactly the bug
    v3.1.0 fixed; this stops it coming back as the list grows."""
    from mangasurf.gui import DEFAULT_SETTINGS

    app = read(os.path.join(APP, "app.js"))
    bound = set(re.findall(r"pushSettings\(\{\s*\[?([a-z_]+)", app))
    bound |= set(re.findall(r"bindSlider\('#[a-z-]+',\s*'([a-z_]+)'", app))
    bound |= set(re.findall(r"set_server_config',\s*\{\s*([a-z_]+)", app))
    bound |= set(re.findall(r"set_opds_config',\s*\{\s*([a-z_]+)", app))

    # Internal state, not user-facing preferences.
    internal = {"sources", "library_search_roots", "rail_expanded", "reader_theme"}
    missing = sorted(k for k in DEFAULT_SETTINGS if k not in bound and k not in internal)
    assert missing == [], f"no control for: {missing}"


def test_the_reader_theme_key_is_gone():
    """v3.1.0 unified on `theme`; `reader_theme` was a leftover that would
    quietly diverge from it."""
    from mangasurf.gui import DEFAULT_SETTINGS

    app = read(os.path.join(APP, "app.js"))
    assert "reader_theme" not in app
    # still tolerated in the defaults for older configs, but nothing reads it
    assert DEFAULT_SETTINGS.get("theme") is not None


def test_sliders_use_the_shared_binding():
    """Ad-hoc handlers were what left half the sliders without a filled
    track and a stale value chip."""
    app = read(os.path.join(APP, "app.js"))
    assert app.count("bindSlider(") >= 10


def test_the_slider_fill_is_a_custom_property():
    css = read(os.path.join(APP, "theme.css"))
    assert "--fill" in css
    assert "::-webkit-slider-runnable-track" in css
    assert "::-moz-range-progress" in css, "Firefox needs its own fill"


def test_checkboxes_are_themed():
    """The platform checkbox ignores the theme on every OS."""
    css = read(os.path.join(APP, "theme.css"))
    assert 'input[type="checkbox"]:not(.raw)' in css
    assert "appearance: none" in css


def test_the_type_scale_is_defined_once():
    css = read(os.path.join(APP, "theme.css"))
    for token in ("--fs-xs", "--fs-md", "--fs-2xl", "--lh-body",
                  "--ls-heading", "--fw-semi"):
        assert token in css, token


def test_the_spacing_scale_is_defined_once():
    css = read(os.path.join(APP, "theme.css"))
    for token in ("--sp-1", "--sp-4", "--sp-9"):
        assert token in css, token


def test_no_hard_coded_hex_colours_in_the_chrome():
    css = read(os.path.join(APP, "style.css"))
    offenders = []
    for line in css.splitlines():
        stripped = line.strip()
        if stripped.startswith("/*") or stripped.startswith("*"):
            continue
        offenders += [f"{stripped[:60]} -> {m}"
                      for m in re.findall(r"#[0-9a-fA-F]{3,8}\b", line)]
    assert offenders == [], offenders


# ─────────────────────────────────────────────────────────── browser tests


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


def _calendar_days(count=364):
    days = []
    for i in range(count):
        chapters = (i % 9) if (i % 5) else 0
        level = 0 if not chapters else min(4, 1 + chapters // 3)
        days.append({"date": f"2026-{1 + i // 31:02d}-{1 + i % 28:02d}",
                     "chapters": chapters, "pages": chapters * 18,
                     "bytes": chapters * 1000, "level": level,
                     "sources": {"mangadex": chapters} if chapters else {},
                     "top": "mangadex" if chapters else ""})
    return days


STUB = {
    "get_settings": {"ok": True, "settings": {
        "theme": "midnight", "accent": "blue", "corners": "rounded",
        "matrix": True, "animations": True, "columns": 0,
        "reader_max_width": "80%", "reader_gap": 12, "reader_preload": 5,
        "max_concurrent_jobs": 4, "chapter_workers": 6, "image_workers": 10,
        "retries": 3, "delay": 1.2, "bundle": 0,
        "reader_autoscroll_speed": 150}},
    "get_sources": {"ok": True, "sources": [
        {"id": "mangadex", "name": "MangaDex"}, {"id": "asurascans", "name": "Asura Scans"}]},
    "get_source_config": {"ok": True, "sources": [
        {"id": "mangadex", "name": "MangaDex", "base_url": "https://mangadex.org",
         "enabled": True, "supports_language": True, "supports_scanlator": True,
         "needs_flaresolverr": False, "adult_only": False}]},
    "lock_status": {"ok": True, "enabled": False, "should_lock": False},
    "reader_library": {"ok": True, "count": 2, "books": [
        {"title": "Solo Leveling", "url": "u0", "source": "mangadex", "cover": "",
         "directory": "/d/0", "chapters": 179,
         "items": [{"kind": "folder", "path": "/d/0/c1", "label": "c1",
                    "pages": 6, "readable": True}]},
        {"title": "One Piece", "url": "u1", "source": "weebcentral", "cover": "",
         "directory": "/d/1", "chapters": 1104,
         "items": [{"kind": "folder", "path": "/d/1/c1", "label": "c1",
                    "pages": 6, "readable": True}]}]},
    "reader_recent": {"ok": True, "items": [
        {"path": "/d/0/c1", "title": "Solo Leveling", "name": "c1", "index": 3,
         "total": 20, "fraction": 0.4, "readable": True, "kind": "folder"},
        {"path": "/d/1/c1", "title": "One Piece", "name": "c1", "index": 19,
         "total": 20, "fraction": 1.0, "readable": True, "kind": "folder"}]},
    "get_queue": {"ok": True, "queue": []},
    "get_stats": {"ok": True, "stats": {
        "totals": {"chapters": 873, "pages": 15714, "bytes": 3_000_000_000,
                   "downloads": 486, "seconds": 33120},
        "sources": {"mangadex": {"name": "MangaDex", "chapters": 500, "bytes": 2_000_000_000},
                    "asurascans": {"name": "Asura Scans", "chapters": 373, "bytes": 1_000_000_000}},
        "derived": {"human_time": "9h 12m"}}},
    "get_calendar": {"ok": True, "calendar": {
        "days": _calendar_days(), "weeks": 52, "peak": 8, "total": 873}},
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
    pg = browser.new_page(viewport={"width": 1340, "height": 900})
    pg.errors = []
    pg.on("pageerror", lambda exc: pg.errors.append(str(exc)))
    pg.on("console", lambda msg: pg.errors.append(msg.text)
          if msg.type == "error" else None)
    pg.add_init_script(init)
    pg.goto(origin + "/app/index.html", wait_until="load")
    pg.wait_for_function("window.__readerReady === true", timeout=20000)
    yield pg
    pg.close()


def test_the_app_boots_clean(page):
    assert page.evaluate("window.__readerReady") is True
    assert page.errors == []


def test_the_window_is_called_readerm(page):
    assert "ReaderM" in page.title()


# ── stats ─────────────────────────────────────────────────────────────────


def test_the_stats_tab_exists(page):
    assert page.locator('.rail-btn[data-view="stats"]').count() == 1


def test_the_stats_view_shows_totals(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(600)
    text = page.text_content("#stats-totals")
    assert "873" in text
    assert "CHAPTERS" in text.upper()


def test_the_contribution_calendar_renders_a_cell_per_day(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(600)
    assert page.locator("#cal i").count() == 364


def test_busier_days_are_brighter(page):
    """A calendar where every cell is the same colour says nothing."""
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(600)
    levels = page.evaluate(
        "[...document.querySelectorAll('#cal i')].map(i => i.dataset.level)")
    assert len(set(levels)) >= 3, set(levels)
    colours = page.evaluate("""() => {
        const seen = {};
        for (const cell of document.querySelectorAll('#cal i'))
            seen[cell.dataset.level] = getComputedStyle(cell).backgroundColor;
        return seen;
    }""")
    assert len(set(colours.values())) == len(colours), colours


def test_the_legend_swatches_are_painted(page):
    """Scoping the level colours to `.cal` alone left every legend swatch
    transparent -- measured rgba(0, 0, 0, 0) on all five."""
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(600)
    colours = page.evaluate(
        "[...document.querySelectorAll('.cal-legend i')]"
        ".map(i => getComputedStyle(i).backgroundColor)")
    assert len(colours) == 5
    assert all("rgba(0, 0, 0, 0)" not in c for c in colours), colours
    assert len(set(colours)) == 5, colours


def test_month_labels_track_the_column_pitch(page):
    """Cells are 12px with a 3px gap, so a column is 15px. A 12px label pitch
    drifted three pixels a week -- across a year, months sat above the wrong
    column entirely."""
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(600)
    geometry = page.evaluate("""() => {
        const cells = document.querySelectorAll('#cal i');
        const spans = document.querySelectorAll('#cal-months span');
        return {
            columnPitch: Math.round(cells[7].getBoundingClientRect().x
                                  - cells[0].getBoundingClientRect().x),
            labelPitch: Math.round(spans[1].getBoundingClientRect().x
                                 - spans[0].getBoundingClientRect().x),
        };
    }""")
    assert geometry["columnPitch"] == geometry["labelPitch"], geometry


def test_streaks_are_reported(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(600)
    text = page.text_content("#stats-streaks")
    assert "LONGEST STREAK" in text.upper()
    assert "ACTIVE DAYS" in text.upper()


def test_the_streak_maths_is_right(page):
    """Driven directly, because a wrong streak still renders happily."""
    cases = page.evaluate("""() => {
        const mk = list => list.map((n, i) => ({ date: `d${i}`, chapters: n }));
        return {
            allEmpty: window.__reader.streaks(mk([0, 0, 0])),
            straight: window.__reader.streaks(mk([1, 1, 1, 1])),
            broken:   window.__reader.streaks(mk([1, 1, 0, 1])),
            trailing: window.__reader.streaks(mk([1, 1, 1, 0])),
            longestInMiddle: window.__reader.streaks(mk([1, 1, 1, 1, 0, 1])),
        };
    }""")
    assert cases["allEmpty"] == {"best": 0, "current": 0}
    assert cases["straight"] == {"best": 4, "current": 4}
    assert cases["broken"]["best"] == 2
    # a run that ends today-minus-one still counts: nothing downloaded yet today
    assert cases["trailing"]["current"] == 3
    assert cases["longestInMiddle"]["best"] == 4


def test_the_source_tab_ranks_by_chapters(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="sources"]')
    page.wait_for_timeout(300)
    labels = page.evaluate(
        "[...document.querySelectorAll('#stats-sources .bl')].map(e => e.textContent)")
    assert labels[:2] == ["MangaDex", "Asura Scans"], labels


def test_bar_widths_are_proportional(page):
    """Not just "bigger than the next one": the ratio has to match the data.

    MangaDex has 500 chapters and Asura 373, so the second bar should be
    ~75% of the first. A floor of 2% makes every bar equal-but-nonzero, which
    a simple `a > b > 0` check happily accepts.
    """
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="sources"]')
    page.wait_for_timeout(300)
    widths = page.evaluate(
        "[...document.querySelectorAll('#stats-sources .bt i')]"
        ".map(i => i.getBoundingClientRect().width)")
    assert len(widths) == 2, widths
    assert widths[0] > widths[1] > 0, widths
    # the widest bar must actually fill its track
    track = page.evaluate(
        "document.querySelector('#stats-sources .bt').getBoundingClientRect().width")
    assert widths[0] > track * 0.9, f"widest bar is only {widths[0]:.0f} of {track:.0f}px"
    assert abs((widths[1] / widths[0]) - (373 / 500)) < 0.05, widths


def test_the_library_tab_counts_series(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="library"]')
    page.wait_for_timeout(300)
    assert "SERIES" in page.text_content("#stats-library").upper()
    assert "One Piece" in page.text_content("#stats-biggest")


def test_the_reading_tab_splits_finished_from_in_progress(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="reading"]')
    page.wait_for_timeout(300)
    text = page.text_content("#stats-reading")
    assert "IN PROGRESS" in text.upper()
    assert "FINISHED" in text.upper()


def test_only_one_tab_pane_shows_at_a_time(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="library"]')
    page.wait_for_timeout(300)
    visible = page.evaluate(
        "[...document.querySelectorAll('.tabpane')].filter(p => !p.hidden).length")
    assert visible == 1


def test_the_active_tab_is_marked(page):
    page.click('.rail-btn[data-view="stats"]')
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="sources"]')
    page.wait_for_timeout(200)
    # Scoped: the reader's page sidebar has tabs of its own now, so a bare
    # ".tab.on" matches more than one thing.
    assert page.locator("#stats-tabs .tab.on").get_attribute("data-tab") == "sources"


# ── sliders ───────────────────────────────────────────────────────────────


def test_sliders_paint_a_filled_track(page):
    """`accent-color` alone gives the platform slider, which ignores the
    theme; the fill is a gradient stop this has to keep in step."""
    fills = page.evaluate("""() => [...document.querySelectorAll('input[type=range]')]
        .map(el => el.style.getPropertyValue('--fill'))""")
    assert fills, "no sliders found"
    assert any(f and f != "0%" for f in fills), fills


def test_the_fill_matches_the_saved_value(page):
    """80% of a 40..100 range is 66.7% of the way along the track."""
    fill = page.evaluate(
        "document.getElementById('set-width').style.getPropertyValue('--fill')")
    assert abs(float(fill.rstrip("%")) - 66.7) < 1.5, fill


def test_dragging_a_slider_repaints_it(page):
    before = page.evaluate(
        "document.getElementById('set-gap').style.getPropertyValue('--fill')")
    page.evaluate("""() => {
        const el = document.getElementById('set-gap');
        el.value = '40';
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    after = page.evaluate(
        "document.getElementById('set-gap').style.getPropertyValue('--fill')")
    assert before != after, (before, after)


def test_every_slider_has_a_live_value_chip(page):
    missing = page.evaluate("""() => {
        const out = [];
        for (const el of document.querySelectorAll('.settings input[type=range]')) {
            const chip = document.getElementById(el.id + '-out');
            if (!chip || !chip.textContent.trim()) out.push(el.id);
        }
        return out;
    }""")
    assert missing == [], missing


def test_the_value_chip_follows_the_slider(page):
    page.evaluate("""() => {
        const el = document.getElementById('set-max-jobs');
        el.value = '6';
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    assert page.text_content("#set-max-jobs-out").strip() == "6"


def test_a_slider_with_a_unit_shows_it(page):
    assert "px/s" in page.text_content("#set-auto-speed-out")
    assert "%" in page.text_content("#set-width-out")


# ── settings coverage ─────────────────────────────────────────────────────


def test_the_new_settings_are_present(page):
    for control in ("#set-preload", "#set-reader-animate", "#set-fullscreen-default",
                    "#set-reader-path", "#set-default-source", "#set-language",
                    "#set-scanlator", "#set-interleave-browse", "#set-data-saver",
                    "#set-bundle", "#set-confirm-delete", "#set-auto-snapshot",
                    "#set-opds-cover-root"):
        assert page.locator(control).count() == 1, control


def test_saved_values_reach_the_controls(page):
    assert page.input_value("#set-preload") == "5"
    assert page.input_value("#set-max-jobs") == "4"
    assert page.input_value("#set-image-workers") == "10"


def test_the_delay_slider_maps_tenths_to_seconds(page):
    """Stored as 1.2 seconds, shown on a 0..30 integer track."""
    assert page.input_value("#set-delay") == "12"
    assert page.text_content("#set-delay-out").strip() == "1.2s"


def test_changing_a_new_setting_saves_it(page):
    page.evaluate("""() => {
        const el = document.getElementById('set-language');
        el.value = 'ja';
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }""")
    page.wait_for_timeout(500)
    saved = {}
    for name, args in page.evaluate("window.__calls"):
        if name == "set_settings" and args:
            saved.update(args[0] or {})
    assert saved.get("language") == "ja", saved
