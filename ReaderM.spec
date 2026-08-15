# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ReaderM — all-inclusive executable.

Build (from the repo root, inside your venv):

    pyinstaller ReaderM.spec                 # one-folder build (recommended)
    pyinstaller ReaderM.spec -- --onefile    # single-file build

Output lands in dist/ReaderM/ (or dist/ReaderM.exe for onefile).
See MD/PACKAGING.md for full instructions per platform.

Double-clicking the result opens the **launcher window**, from which any of
the five interfaces can be started. `ReaderM.exe gui` still goes straight to
the desktop app.
"""

import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# "--onefile" after "--" switches to a single-file build
ONEFILE = "--onefile" in sys.argv

APP_NAME = "ReaderM"

# ----------------------------------------------------------------- data files
# The GUI's web assets must ship inside the bundle. readerm.server serves the
# very same folder to the phone, so this one entry covers both.
datas = [
    ("readerm/reader/app", "readerm/reader/app"),
    ("readerm/reader/foliate", "readerm/reader/foliate"),
]
# Textual ships css/tcss data files
datas += collect_data_files("textual")

# ------------------------------------------------------------- hidden imports
hiddenimports = [
    # pywebview platform backends (only the matching one loads at runtime)
    "webview.platforms.winforms",   # Windows
    "webview.platforms.edgechromium",
    "webview.platforms.cocoa",      # macOS
    "webview.platforms.gtk",        # Linux (WebKitGTK)
    "webview.platforms.qt",         # Linux fallback
    # System tray. pystray picks its backend at import time via a chain of
    # try/except imports, which PyInstaller's static analysis cannot follow
    # -- so without these the packaged exe silently had no tray at all and
    # "minimise to tray" did nothing.
    "pystray",
    "pystray._win32",
    "pystray._darwin",
    "pystray._appindicator",
    "pystray._gtk",
    "pystray._xorg",
    # The tray icon is drawn with Pillow at runtime.
    "PIL.Image",
    "PIL.ImageDraw",
    # The LAN server. Flask pulls these in itself, but the launcher only
    # imports readerm.server lazily inside a function, which the static
    # analysis does not follow.
    "flask",
    "jinja2",
    "werkzeug",
    "readerm.server",
    "readerm.serverui",
    "readerm.servercfg",
    "readerm.landing",
    "readerm.opds",
    "readerm.opdsserve",
    "readerm.opdsui",
    # 1.0.x additions. collect_submodules("readerm") below already sweeps
    # these up, but they are named explicitly because they are imported
    # lazily from inside functions -- the exact pattern the static analysis
    # cannot follow, and the reason the tray and the LAN server were both
    # missing from earlier builds.
    "readerm.shelves",
    "readerm.localapi",
    # stdlib/log bits PyInstaller sometimes misses
    "logging.handlers",
]
hiddenimports += collect_submodules("readerm")
hiddenimports += collect_submodules("textual.widgets")

# ------------------------------------------------------------------- analysis
a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # trim things we never use to keep the exe smaller
        "tkinter", "unittest", "pydoc", "test",
        "numpy", "matplotlib", "scipy", "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ------------------------------------------------------------------ exe/build
# console=True so the CLI, TUI and menu subcommands work from a terminal.
# On Windows a console window appears alongside the launcher; for a
# console-free GUI-only build, set console=False and build a second exe.
#
# UPX is deliberately off. It routinely trips antivirus heuristics on a
# freshly built, unsigned exe, and the saving is not worth a download that
# gets quarantined before it runs.
if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=True,
        icon="docs/icon.ico" if sys.platform == "win32" else None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        strip=False,
        upx=False,
        console=True,
        icon="docs/icon.ico" if sys.platform == "win32" else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )

# macOS app bundle (GUI double-click support)
if sys.platform == "darwin" and not ONEFILE:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="io.github.readerm.downloader",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
