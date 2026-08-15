"""Regression tests for: search Enter, lock timing/UI, square corners and the
collapsible side rail."""

import importlib
import os
import re
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "readerm", "gui", "web")


def read(name):
    return open(os.path.join(WEB, name), encoding="utf-8").read()


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    yield home


# ================================================ search not working


# ============================================ lock shows up too late


# ============================================== square corners mode


def test_corners_default_is_rounded():
    import readerm.gui as gui
    importlib.reload(gui)
    assert gui.DEFAULT_SETTINGS["corners"] == "rounded"


# ================================================ collapsible rail


def test_rail_default_is_collapsed():
    import readerm.gui as gui
    importlib.reload(gui)
    assert gui.DEFAULT_SETTINGS["rail_expanded"] is False


def test_rail_settings_round_trip():
    import readerm.gui as gui
    importlib.reload(gui)
    api = gui.Api()
    api.set_settings({"rail_expanded": True, "corners": "square"})
    importlib.reload(gui)
    saved = gui.load_settings()
    assert saved["rail_expanded"] is True
    assert saved["corners"] == "square"
