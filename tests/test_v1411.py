"""Regression tests for v1.4.11 -- settings moved into config.json.

Settings used to live in their own ``settings.json``, written with a bare
``open(..., "w")`` and no lock. That lost data two ways:

* an interrupted write left truncated JSON, and ``load_settings()`` swallowed
  the ``ValueError`` and silently returned defaults -- every preference reset
  at once, with no error shown;
* ``set_settings()`` did read-modify-write outside any lock, so two concurrent
  saves each wrote the state they had read and the later one erased the
  earlier one's change. Measured on the old code, four threads saving at once
  destroyed the theme, accent and output directory in **5 of 5** runs.

Both are now handled by ``mangasurf.config``: one ``RLock`` and one atomic
tmp+replace write, shared with the per-source config.
"""

import importlib
import json
import os
import sys
import tempfile
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)

    import mangasurf.config as appconfig
    import mangasurf.features as features
    import mangasurf.library as library
    import mangasurf.passlock as passlock

    for module in (appconfig, passlock, features, library):
        importlib.reload(module)
    import mangasurf.gui as gui
    importlib.reload(gui)
    yield home


# ============================================================= one file


def test_settings_live_in_config_json():
    import mangasurf.gui as gui

    gui.save_settings({**gui.load_settings(), "theme": "nord"})
    assert gui.SETTINGS_PATH.endswith("config.json")
    with open(gui.SETTINGS_PATH, encoding="utf-8") as f:
        stored = json.load(f)
    assert stored["settings"]["theme"] == "nord"


def test_settings_and_sources_share_the_file():
    """Writing one section must never drop the other."""
    import mangasurf.config as appconfig
    import mangasurf.gui as gui

    appconfig.set_enabled("mangadex", False)
    gui.save_settings({**gui.load_settings(), "theme": "mocha"})

    with open(appconfig.CONFIG_PATH, encoding="utf-8") as f:
        stored = json.load(f)
    assert stored["settings"]["theme"] == "mocha"
    assert stored["sources"]["mangadex"]["enabled"] is False

    # ...and the reverse order
    appconfig.set_enabled("mangadex", True)
    assert gui.load_settings()["theme"] == "mocha"


def test_save_config_does_not_erase_settings():
    """save_config() callers build only the sources half."""
    import mangasurf.config as appconfig
    import mangasurf.gui as gui

    gui.save_settings({**gui.load_settings(), "accent": "teal"})
    appconfig.save_config({"sources": {}})
    assert gui.load_settings()["accent"] == "teal"


# ======================================================= crash safety


def test_write_is_atomic():
    import mangasurf.config as appconfig
    import mangasurf.gui as gui

    gui.save_settings({**gui.load_settings(), "theme": "nord"})
    leftovers = [f for f in os.listdir(appconfig.DIR) if f.endswith(".tmp")]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_a_truncated_temp_file_cannot_reset_settings():
    """The failure mode that wiped everything: a half-written file."""
    import mangasurf.gui as gui

    gui.save_settings({**gui.load_settings(),
                       "theme": "mocha", "accent": "teal",
                       "output_dir": "/keep/me"})

    raw = open(gui.SETTINGS_PATH, encoding="utf-8").read()
    with open(gui.SETTINGS_PATH + ".tmp", "w", encoding="utf-8") as f:
        f.write(raw[:len(raw) // 2])          # interrupted write

    settings = gui.load_settings()
    assert settings["theme"] == "mocha"
    assert settings["accent"] == "teal"
    assert settings["output_dir"] == "/keep/me"


def test_unreadable_config_still_yields_defaults():
    """Corruption must degrade to defaults, not raise."""
    import mangasurf.gui as gui

    os.makedirs(os.path.dirname(gui.SETTINGS_PATH), exist_ok=True)
    with open(gui.SETTINGS_PATH, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    settings = gui.load_settings()
    assert settings["theme"] == "midnight"
    assert "output_dir" in settings


# ========================================================= the race


def test_concurrent_saves_do_not_clobber_each_other():
    """Four threads saving at once destroyed theme/accent/output_dir in 5 of
    5 runs before the lock was added."""
    import mangasurf.gui as gui

    gui.save_settings({**gui.load_settings(),
                       "theme": "mocha", "accent": "teal",
                       "output_dir": "/keep/me"})

    def worker(n):
        for i in range(40):
            gui.update_settings({"retries": (n + i) % 9 + 1})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    settings = gui.load_settings()
    assert settings["theme"] == "mocha"
    assert settings["accent"] == "teal"
    assert settings["output_dir"] == "/keep/me"


def test_concurrent_saves_keep_the_file_valid():
    import mangasurf.gui as gui

    def worker(n):
        for i in range(30):
            gui.update_settings({"accent": f"a{n}{i}"})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with open(gui.SETTINGS_PATH, encoding="utf-8") as f:
        json.load(f)          # must parse


def test_set_settings_merges_under_the_lock():
    """A partial update must not drop the keys it did not mention."""
    import mangasurf.gui as gui

    api = gui.Api()
    api.set_settings({"theme": "nord", "accent": "rose"})
    api.set_settings({"retries": 7})

    settings = gui.load_settings()
    assert settings["theme"] == "nord"
    assert settings["accent"] == "rose"
    assert settings["retries"] == 7


def test_save_button_keys_do_not_wipe_appearance():
    """The Save button posts ~17 of the 35 keys. Those it omits -- theme,
    accent, corners, sources -- must survive it."""
    import mangasurf.gui as gui

    api = gui.Api()
    api.set_settings({"theme": "mocha", "accent": "teal",
                      "corners": "square", "default_source": "natomanga"})
    api.set_settings({
        "output_dir": "/tmp/out", "format": "cbz", "keep_images": False,
        "chapter_workers": 3, "image_workers": 6, "delay": 0.5, "retries": 5,
    })

    settings = gui.load_settings()
    assert settings["theme"] == "mocha"
    assert settings["accent"] == "teal"
    assert settings["corners"] == "square"
    assert settings["default_source"] == "natomanga"


def test_choosing_a_download_folder_keeps_other_settings():
    """That auto-save used its own read-modify-write, racing the Save button."""
    import mangasurf.gui as gui

    gui.save_settings({**gui.load_settings(), "theme": "nord"})
    gui.update_settings({"output_dir": "/picked/here"})

    settings = gui.load_settings()
    assert settings["output_dir"] == "/picked/here"
    assert settings["theme"] == "nord"


# ========================================================== migration


def test_legacy_settings_file_is_migrated():
    import mangasurf.config as appconfig
    import mangasurf.gui as gui

    os.makedirs(appconfig.DIR, exist_ok=True)
    with open(appconfig.LEGACY_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"theme": "nord", "accent": "rose", "retries": 9}, f)

    settings = gui.load_settings()
    assert settings["theme"] == "nord"
    assert settings["accent"] == "rose"
    assert settings["retries"] == 9


def test_migration_preserves_existing_source_config():
    import mangasurf.config as appconfig
    import mangasurf.gui as gui

    os.makedirs(appconfig.DIR, exist_ok=True)
    with open(appconfig.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"sources": {"mangadex": {"enabled": False, "rank": 3}}}, f)
    with open(appconfig.LEGACY_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"theme": "nord"}, f)

    assert gui.load_settings()["theme"] == "nord"
    assert appconfig.get_source_config("mangadex")["enabled"] is False


def test_migration_does_not_override_newer_settings():
    """Once config.json owns the settings, a stale settings.json is ignored."""
    import mangasurf.config as appconfig
    import mangasurf.gui as gui

    gui.save_settings({**gui.load_settings(), "theme": "mocha"})
    with open(appconfig.LEGACY_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump({"theme": "nord"}, f)

    assert gui.load_settings()["theme"] == "mocha"


def test_migration_survives_a_corrupt_legacy_file():
    import mangasurf.config as appconfig
    import mangasurf.gui as gui

    os.makedirs(appconfig.DIR, exist_ok=True)
    with open(appconfig.LEGACY_SETTINGS_PATH, "w", encoding="utf-8") as f:
        f.write("not json at all")
    assert gui.load_settings()["theme"] == "midnight"


# ============================================================== shared


def test_tui_shares_the_same_store():
    """The TUI imports these directly, so it inherits the fix."""
    source = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "mangasurf", "tui.py"), encoding="utf-8").read()
    assert "from .gui import load_settings, save_settings" in source


def test_gui_no_longer_writes_settings_by_hand():
    """A bare open()/json.dump here is the bug, not the fix."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = open(os.path.join(root, "mangasurf", "gui", "__init__.py"),
                  encoding="utf-8").read()
    body = source[source.index("def save_settings"):]
    body = body[:body.index("\n\n\n")]
    assert "json.dump" not in body
    assert "appconfig.save_settings" in body
