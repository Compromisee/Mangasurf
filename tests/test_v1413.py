"""Regression tests for v1.4.13 -- CLI search syntax and the interactive menu.

Two additions and one bug fix:

* ``readerm search`` gained ``--type``, ``--status``, ``-n/--limit``,
  ``--sort``, ``--reverse``, ``--json``, ``--urls``, ``--open`` and
  ``--download``.
* ``readerm menu`` is a progressive, numbered interface that needs nothing
  beyond ``rich`` -- the Textual TUI is an optional extra that is frequently
  not installed.
* ``readerm tui`` crashed with a raw ``ModuleNotFoundError`` traceback when
  Textual was missing, because the friendly message lived *after* the
  module-level import.
"""

import importlib
import json
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    import mangasurf.config as appconfig
    import mangasurf.features as features
    import mangasurf.library as library
    for module in (appconfig, features, library):
        importlib.reload(module)
    yield home


@pytest.fixture(autouse=True)
def restore_menu_console():
    """Several tests swap menu.console for a scripted stand-in.

    It is a module global, so without restoring it the fake leaks into every
    later test -- which is exactly how the "no terminal" test came to see an
    empty capsys instead of the real message.
    """
    import mangasurf.menu as menu

    original = menu.console
    yield
    menu.console = original


# =========================================================== CLI syntax


def test_new_search_flags_are_accepted():
    from mangasurf.cli import build_parser

    args = build_parser().parse_args([
        "search", "one piece", "--type", "manhwa", "--status", "Ongoing",
        "-n", "5", "--sort", "title", "--reverse", "--json",
    ])
    assert args.type == "manhwa"
    assert args.status == "Ongoing"
    assert args.limit == 5
    assert args.sort == "title"
    assert args.reverse is True
    assert args.json is True


def test_invalid_type_is_rejected():
    from mangasurf.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["search", "x", "--type", "nonsense"])


def test_invalid_sort_key_is_rejected():
    from mangasurf.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["search", "x", "--sort", "nonsense"])


def test_menu_is_a_known_command():
    from mangasurf.cli import build_parser

    for name in ("menu", "i", "interactive"):
        assert build_parser().parse_args([name]).target == name


# ------------------------------------------------------------ narrowing


def test_type_narrowing_keeps_unknown_types():
    """A source that reports no type must not vanish from a filtered search."""
    from mangasurf.cli import _narrow

    rows = [
        {"title": "A", "series_type": "Manga", "source": "mangadex"},
        {"title": "B", "series_type": "Manhwa", "source": "mangadex"},
        {"title": "C", "source": "nosuchsource"},
    ]
    kept = [r["title"] for r in _narrow(rows, series_type="manhwa")]
    assert kept == ["B", "C"]


def test_type_any_is_a_noop():
    from mangasurf.cli import _narrow

    rows = [{"title": "A", "series_type": "Manga", "source": "mangadex"}]
    assert _narrow(rows, series_type="any") == rows
    assert _narrow(rows, series_type=None) == rows


def test_status_narrowing_keeps_unknown_status():
    from mangasurf.cli import _narrow

    rows = [{"title": "A", "status": "Ongoing"},
            {"title": "B", "status": "Completed"},
            {"title": "C"}]
    kept = [r["title"] for r in _narrow(rows, status="Completed")]
    assert kept == ["B", "C"]


def test_source_level_type_fallback_applies():
    from mangasurf.cli import _narrow

    rows = [{"title": "W", "source": "webtoons"}]
    assert len(_narrow(rows, series_type="manhwa")) == 1
    assert len(_narrow(rows, series_type="manga")) == 0


# -------------------------------------------------------------- sorting


def test_sort_by_title():
    from mangasurf.cli import _sort_results

    rows = [{"title": "Zed"}, {"title": "alpha"}, {"title": "Mid"}]
    assert [r["title"] for r in _sort_results(rows, "title")] == \
        ["alpha", "Mid", "Zed"]


def test_sort_by_chapters_puts_unknown_last():
    """Unknown counts must not sort as zero and bury real results."""
    from mangasurf.cli import _sort_results

    rows = [{"title": "few", "chapter_count": 3},
            {"title": "unknown"},
            {"title": "many", "chapter_count": 900}]
    assert [r["title"] for r in _sort_results(rows, "chapters")] == \
        ["many", "few", "unknown"]


def test_sort_is_stable_without_a_key():
    from mangasurf.cli import _sort_results

    rows = [{"title": "b"}, {"title": "a"}]
    assert _sort_results(rows, None) == rows


def test_reverse_flips_the_order():
    from mangasurf.cli import _sort_results

    rows = [{"title": "a"}, {"title": "b"}]
    assert [r["title"] for r in _sort_results(rows, "title", reverse=True)] == \
        ["b", "a"]


# ------------------------------------------------------- machine output


def test_urls_only_prints_bare_urls(capsys):
    from mangasurf.cli import _emit

    rows = [{"url": "https://a/1"}, {"url": "https://a/2"}]
    assert _emit(rows, urls_only=True) is True
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["https://a/1", "https://a/2"]


def test_json_output_is_parseable(capsys):
    from mangasurf.cli import _emit

    rows = [{"title": "A", "url": "https://a/1"}]
    assert _emit(rows, as_json=True) is True
    assert json.loads(capsys.readouterr().out) == rows


def test_emit_declines_when_neither_flag_is_set():
    from mangasurf.cli import _emit

    assert _emit([{"title": "A"}]) is False


# ============================================================== the menu


def test_menu_module_imports_without_textual():
    """The menu must work on a bare install; that is its whole point."""
    import mangasurf.menu as menu

    for name in ("run_menu", "choose", "ask", "ask_number", "confirm"):
        assert hasattr(menu, name), name


def test_choose_returns_a_zero_based_index():
    import mangasurf.menu as menu

    menu.console = _FakeConsole(["2"])
    assert menu.choose("t", ["a", "b", "c"]) == 1


def test_quit_and_back_work_at_any_prompt():
    import mangasurf.menu as menu

    menu.console = _FakeConsole(["q"])
    with pytest.raises(menu.Quit):
        menu.ask("x")

    menu.console = _FakeConsole(["b"])
    with pytest.raises(menu.Back):
        menu.ask("x")


def test_eof_exits_cleanly_instead_of_raising():
    """A closed stdin -- a pipe that ran out -- must not look like a crash."""
    import mangasurf.menu as menu

    menu.console = _FakeConsole([])
    with pytest.raises(menu.Quit):
        menu.ask("x")


def test_ask_number_reprompts_until_valid():
    import mangasurf.menu as menu

    menu.console = _FakeConsole(["", "99", "abc", "2"])
    assert menu.ask_number("n", 1, 3) == 2


def test_confirm_defaults_both_ways():
    import mangasurf.menu as menu

    menu.console = _FakeConsole([""])
    assert menu.confirm("ok?", default=True) is True
    menu.console = _FakeConsole([""])
    assert menu.confirm("ok?", default=False) is False


def test_menu_refuses_to_run_without_a_terminal(monkeypatch, capsys):
    """Otherwise it would block forever reading a stdin that never answers."""
    import mangasurf.menu as menu

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    assert menu.run_menu() == 1
    assert "terminal" in capsys.readouterr().out.lower()


def test_every_main_menu_entry_is_handled():
    """A number with no branch behind it would silently do nothing."""
    import inspect

    import mangasurf.menu as menu

    body = inspect.getsource(menu.run_menu)
    for index in range(len(menu.MAIN_MENU)):
        assert f"index == {index}" in body, f"menu item {index} has no branch"


# ==================================================== the tui crash fix


def test_tui_module_imports_without_textual():
    """It used to raise ModuleNotFoundError while still being imported, so
    the friendly message in run_tui() never printed."""
    import mangasurf.tui as tui

    importlib.reload(tui)
    assert hasattr(tui, "run_tui")
    assert hasattr(tui, "TEXTUAL_AVAILABLE")


@pytest.mark.skipif(
    importlib.util.find_spec("textual") is not None,
    reason="Textual is installed, so the fallback path cannot be exercised")
def test_missing_textual_prints_guidance_not_a_traceback():
    result = subprocess.run(
        [sys.executable, "-m", "mangasurf.cli", "tui"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert "Traceback" not in result.stderr
    assert "pip install textual" in result.stdout
    # and it points at the thing that does work without an extra install
    assert "readerm menu" in result.stdout


def test_cli_help_documents_the_new_syntax():
    result = subprocess.run(
        [sys.executable, "-m", "mangasurf.cli", "--help"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    for fragment in ("--type", "--sort", "--urls", "--json",
                     "--open", "--download", "readerm menu"):
        assert fragment in result.stdout, fragment


class _FakeConsole:
    """Stand-in console that replays scripted answers."""

    def __init__(self, answers):
        self.answers = list(answers)

    def input(self, *_args, **_kwargs):
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    def print(self, *_args, **_kwargs):
        pass

    def status(self, *_args, **_kwargs):
        import contextlib
        return contextlib.nullcontext()


# ============================ v1.4.14: direct execution / landing page redesign


def test_menu_can_be_run_as_a_bare_file():
    """`py menu.py` from inside the package raised ImportError.

    cli.py and tui.py already self-bootstrap; menu.py was added without that
    block, so its relative imports had no parent package.
    """
    result = subprocess.run(
        [sys.executable, "menu.py"],
        cwd=os.path.join(ROOT, "readerm"),
        capture_output=True, text=True, timeout=120,
    )
    assert "attempted relative import" not in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("module", [
    "cli", "tui", "menu", "config", "downloader", "packager", "scraper",
])
def test_every_relative_import_module_self_bootstraps(module):
    """Generalises the fix, so the next added module cannot repeat it."""
    src = open(os.path.join(ROOT, "readerm", f"{module}.py"),
               encoding="utf-8").read()
    assert '__package__ in (None, "")' in src, f"{module}.py cannot run directly"


def test_no_module_using_relative_imports_is_left_unguarded():
    import re

    unguarded = []
    package = os.path.join(ROOT, "readerm")
    for name in sorted(os.listdir(package)):
        if not name.endswith(".py") or name.startswith("__"):
            continue
        src = open(os.path.join(package, name), encoding="utf-8").read()
        if re.search(r"^from \.", src, re.M) and '__package__ in (None, "")' not in src:
            unguarded.append(name)
    assert unguarded == [], f"cannot be run directly: {unguarded}"


def test_menu_runs_the_menu_when_executed_directly():
    src = open(os.path.join(ROOT, "readerm", "menu.py"), encoding="utf-8").read()
    assert '__name__ == "__main__"' in src
    assert "run_menu()" in src
