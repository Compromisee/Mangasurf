"""v1.4.30: the launcher is the exe's default, and everything is bundled.

Two packaging bugs, both found by actually building rather than reading the
spec:

* ``server.py`` and ``landing.py`` were top-level scripts, so
  ``collect_submodules("mangasurf")`` never saw them and the exe shipped
  without the phone server or the launcher at all;
* ``mangasurf/serverui.py`` and the GUI did ``import server``, which only
  resolves when the repo root is on ``sys.path`` -- true from a checkout,
  false inside a bundle.

Both are now modules in the package, with thin wrappers at the repo root so
``python server.py`` keeps working.
"""

import os
import re
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    return open(path, encoding="utf-8").read()


# ============================================== the modules are packaged


def test_server_and_landing_live_in_the_package():
    """A top-level script is invisible to collect_submodules."""
    for name in ("server.py", "landing.py"):
        assert os.path.isfile(os.path.join(ROOT, "mangasurf", name)), name


def test_collect_submodules_sees_them():
    """The actual mechanism the spec relies on."""
    from PyInstaller.utils.hooks import collect_submodules

    found = collect_submodules("mangasurf")
    for module in ("mangasurf.server", "mangasurf.landing",
                   "mangasurf.serverui", "mangasurf.servercfg"):
        assert module in found, f"{module} would not be bundled"


def test_the_root_wrappers_still_work():
    """`python server.py` is documented everywhere; it must keep working."""
    for name in ("server.py", "landing.py"):
        path = os.path.join(ROOT, name)
        assert os.path.isfile(path), name
        source = read(path)
        assert "from mangasurf." in source, f"{name} is not a wrapper"
        # Thin: the real code must not have been duplicated back.
        assert len(source.splitlines()) < 30, f"{name} is not thin"


def test_nothing_imports_the_old_top_level_module():
    """`import server` only resolves with the repo root on sys.path."""
    offenders = []
    for folder in ("mangasurf",):
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, folder)):
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                for line in read(path).splitlines():
                    stripped = line.strip()
                    if re.match(r"^import server\b", stripped) or \
                       re.match(r"^import landing\b", stripped):
                        offenders.append(f"{path}: {stripped}")
    assert offenders == [], offenders


def test_server_finds_its_web_assets_when_frozen():
    """Asset paths must resolve under _MEIPASS, not next to the module.

    Since v3.0.0 server.py delegates to reader.assets.ASSET_ROOT, so the
    frozen-build handling lives there and is asserted there.
    """
    source = read(os.path.join(ROOT, "mangasurf", "reader", "assets.py"))
    block = source[source.index("def _asset_root()"):]
    block = block[:block.index("ASSET_ROOT = _asset_root()")]
    assert "_MEIPASS" in block
    assert 'getattr(sys, "frozen"' in block


def test_web_dir_points_at_real_assets():
    from mangasurf.server import WEB_DIR

    assert os.path.isfile(os.path.join(WEB_DIR, "index.html"))
    assert os.path.isfile(os.path.join(WEB_DIR, "app.js"))
    assert os.path.isfile(os.path.join(WEB_DIR, "manga-view.js"))


def test_both_moved_modules_can_be_run_directly():
    """The repo convention: relative imports need a __package__ guard."""
    for name in ("server.py", "landing.py"):
        source = read(os.path.join(ROOT, "mangasurf", name))
        if re.search(r"^from \.", source, re.M):
            assert '__package__ in (None, "")' in source, name


# =================================================== the exe's default


def test_no_arguments_opens_the_launcher():
    """The exe is five programs in one; a double-click used to commit you
    to the GUI with no way to reach the others."""
    source = read(os.path.join(ROOT, "launcher.py"))
    body = source[source.index("def main():"):]
    head = body[:body.index("command = args[0]")]
    assert "if not args:" in head
    assert "run_landing" in head, "no-args does not open the launcher"


def test_gui_subcommand_still_goes_straight_there():
    """An existing shortcut must not change behaviour."""
    source = read(os.path.join(ROOT, "launcher.py"))
    assert 'command == "gui"' in source
    body = source[source.index('command == "gui"'):]
    assert "run_gui" in body[:200]


def test_the_launcher_routes_every_interface():
    source = read(os.path.join(ROOT, "launcher.py"))
    for command in ("gui", "server", "launcher"):
        assert f'command == "{command}"' in source, command
    # menu/tui fall through to the CLI, which already handles them.
    cli = read(os.path.join(ROOT, "mangasurf", "cli.py"))
    assert 'command == "tui"' in cli
    assert 'command in ("menu"' in cli


def test_a_missing_pywebview_falls_back_rather_than_crashing():
    source = read(os.path.join(ROOT, "launcher.py"))
    head = source[source.index("if not args:"):source.index("command = args[0]")]
    assert "except ImportError" in head
    assert "run_gui" in head


@pytest.mark.parametrize("args,expect", [
    (["--help"], "usage:"),
    (["server", "--help"], "server"),
])
def test_the_launcher_actually_runs(args, expect, tmp_path):
    """Drive launcher.py as a real process."""
    env = dict(os.environ, HOME=str(tmp_path))
    proc = subprocess.run([sys.executable, "launcher.py"] + args,
                          cwd=ROOT, env=env, capture_output=True,
                          text=True, timeout=120)
    assert expect in proc.stdout.lower(), proc.stdout[:300] + proc.stderr[:300]


# ==================================================== frozen behaviour


def test_landing_has_frozen_arguments_for_every_target():
    """A bundle has no .py files, so each tile must re-invoke the exe."""
    from mangasurf.landing import Launcher

    assert set(Launcher.TARGETS) == set(Launcher.FROZEN_ARGS), (
        "a target has no frozen equivalent, so it would fail in the exe")


def test_frozen_arguments_match_what_the_launcher_routes():
    """ReaderM.exe <arg> has to reach the interface the tile promises."""
    from mangasurf.landing import Launcher

    routed = read(os.path.join(ROOT, "launcher.py"))
    cli = read(os.path.join(ROOT, "mangasurf", "cli.py"))
    for target, args in Launcher.FROZEN_ARGS.items():
        first = args[0]
        if first.startswith("-"):
            continue                      # --help goes to the CLI parser
        assert (f'command == "{first}"' in routed
                or f'command == "{first}"' in cli
                or f'command in ("{first}"' in cli), (
            f"'{first}' is not routed anywhere")


def test_frozen_paths_resolve(tmp_path, monkeypatch):
    """HERE and find_python must not point inside the bundle's temp dir."""
    import importlib

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ReaderM"),
                        raising=False)
    from mangasurf import landing
    importlib.reload(landing)
    try:
        assert landing.FROZEN is True
        assert landing.HERE == str(tmp_path)
        path, where = landing.find_python()
        assert path == str(tmp_path / "ReaderM")
        assert "packaged" in where
    finally:
        monkeypatch.undo()
        importlib.reload(landing)


def test_a_frozen_launcher_does_not_warn_about_a_venv(tmp_path, monkeypatch):
    """There is no venv to find in a packaged build; saying so is noise."""
    import importlib

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ReaderM"),
                        raising=False)
    from mangasurf import landing
    importlib.reload(landing)
    try:
        text = " ".join(l["text"] for l in landing.Launcher().get_log()["lines"])
        assert "No virtual environment" not in text
        assert "Packaged build" in text
    finally:
        monkeypatch.undo()
        importlib.reload(landing)


def test_no_display_reports_something_actionable(tmp_path):
    """pywebview prints two screens of ImportError tracebacks on the way
    out; the last word must be advice, not noise -- and the exit code must
    say nothing was launched.

    Run as a real process: grepping the source for `return 1` matched an
    unrelated early-exit and passed with the bug reintroduced.
    """
    env = dict(os.environ, HOME=str(tmp_path))
    env.pop("DISPLAY", None)          # force the failure
    proc = subprocess.run([sys.executable, "landing.py"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 1, (
        f"a failed launch exited {proc.returncode}; nothing was started")
    assert "could not open" in output.lower(), output[-400:]
    # It must end with usable advice, not a traceback.
    tail = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    assert any("gui" in line for line in tail[-8:]), tail[-8:]


def test_direct_commands_differ_when_frozen(tmp_path, monkeypatch):
    """Telling someone to run `python gui.py` next to an exe is useless."""
    import importlib

    from mangasurf import landing
    assert any("python" in c for c in landing._direct_commands())

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ReaderM"),
                        raising=False)
    importlib.reload(landing)
    try:
        commands = landing._direct_commands()
        assert all("python" not in c for c in commands), commands
        assert any(c.endswith(" gui") for c in commands)
    finally:
        monkeypatch.undo()
        importlib.reload(landing)


# ========================================================== the spec


def test_the_spec_bundles_the_new_modules():
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    for module in ("mangasurf.server", "mangasurf.landing", "mangasurf.serverui",
                   "mangasurf.servercfg", "flask"):
        assert f'"{module}"' in spec, f"{module} missing from the spec"


def test_the_spec_bundles_the_web_assets():
    """The GUI page and the phone server both need them."""
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    assert '("mangasurf/reader/app", "mangasurf/reader/app")' in spec
    assert '("mangasurf/reader/foliate", "mangasurf/reader/foliate")' in spec


def test_the_spec_builds_from_the_launcher():
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    assert 'Analysis(\n    ["launcher.py"]' in spec


def test_the_spec_supports_onefile():
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    assert 'ONEFILE = "--onefile" in sys.argv' in spec
    assert "if ONEFILE:" in spec
    # In onefile mode the binaries and datas go into the EXE itself; leaving
    # them out produces an exe that starts and then cannot find anything.
    block = spec[spec.index("if ONEFILE:"):spec.index("else:")]
    assert "a.binaries" in block and "a.datas" in block


def test_upx_is_off():
    """UPX trips antivirus heuristics on unsigned exes; the saving is not
    worth a download that gets quarantined."""
    spec = read(os.path.join(ROOT, "ReaderM.spec"))
    assert "upx=True" not in spec


def test_the_spec_is_valid_python():
    import ast

    ast.parse(read(os.path.join(ROOT, "ReaderM.spec")))


# ================================================ covers.scan("") bug


def test_scan_of_an_empty_root_is_empty():
    """os.path.abspath("") is the current directory, so scan("") used to
    walk wherever the process happened to be -- picking up build output
    from a checkout, or the user's home in a packaged build."""
    from mangasurf.covers import scan

    assert scan("") == []
    assert scan("   ") == []
    assert scan(None) == []


def test_scan_does_not_depend_on_the_working_directory(tmp_path, monkeypatch):
    from mangasurf.covers import scan

    monkeypatch.chdir(ROOT)
    assert scan("") == []
    monkeypatch.chdir(tmp_path)
    assert scan("") == []
