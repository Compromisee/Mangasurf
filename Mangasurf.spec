# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Mangasurf — all-inclusive standalone executable.

Build:
    pyinstaller Mangasurf.spec                 # one-folder build
    pyinstaller Mangasurf.spec -- --onefile    # single-file build

Output lands in dist/Mangasurf/ (or dist/Mangasurf.exe / dist/Mangasurf for onefile).
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ONEFILE = "--onefile" in sys.argv or os.environ.get("PYINSTALLER_ONEFILE", "").lower() in ("1", "true", "yes")

APP_NAME = "Mangasurf"

datas = [
    ("mangasurf/reader/app", "mangasurf/reader/app"),
    ("mangasurf/reader/foliate", "mangasurf/reader/foliate"),
    ("ui", "ui"),
]

# Include icons and documentation assets if present
for asset in ["docs/icon.ico", "docs/icon.png", "docs/icon.svg", "docs/index.html"]:
    if os.path.exists(asset):
        datas.append((asset, os.path.dirname(asset)))

datas += collect_data_files("textual")

hiddenimports = [
    "PyQt6",
    "PyQt6.QtWidgets",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "webview.platforms.cocoa",
    "webview.platforms.gtk",
    "webview.platforms.qt",
    "pystray",
    "pystray._win32",
    "pystray._darwin",
    "pystray._appindicator",
    "pystray._gtk",
    "pystray._xorg",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFilter",
    "flask",
    "jinja2",
    "werkzeug",
    "requests",
    "bs4",
    "rich",
    "fpdf2",
    "ebooklib",
    "ebooklib.epub",
    "mangasurf.database",
    "mangasurf.devices",
    "mangasurf.flaresolverr",
    "mangasurf.server",
    "mangasurf.serverui",
    "mangasurf.servercfg",
    "mangasurf.landing",
    "mangasurf.opds",
    "mangasurf.opdsserve",
    "mangasurf.opdsui",
    "mangasurf.shelves",
    "mangasurf.localapi",
    "mangasurf.sources",
    "logging.handlers",
]

hiddenimports += collect_submodules("mangasurf")
hiddenimports += collect_submodules("mangasurf.sources")
hiddenimports += collect_submodules("textual.widgets")

icon_file = None
if sys.platform == "win32" and os.path.exists("docs/icon.ico"):
    icon_file = "docs/icon.ico"
elif sys.platform == "darwin" and os.path.exists("docs/icon.png"):
    icon_file = "docs/icon.png"
elif os.path.exists("docs/icon.png"):
    icon_file = "docs/icon.png"

a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "test",
        "numpy", "matplotlib", "scipy", "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

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
        icon=icon_file,
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
        icon=icon_file,
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

if sys.platform == "darwin" and not ONEFILE:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=icon_file,
        bundle_identifier="io.github.mangasurf.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
