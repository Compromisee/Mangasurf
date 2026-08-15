# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Mangasurf — all-inclusive executable.

Build:
    pyinstaller Mangasurf.spec                 # one-folder build
    pyinstaller Mangasurf.spec -- --onefile    # single-file build

Output lands in dist/Mangasurf/ (or dist/Mangasurf.exe for onefile).
"""

import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ONEFILE = "--onefile" in sys.argv

APP_NAME = "Mangasurf"

datas = [
    ("readerm/reader/app", "readerm/reader/app"),
    ("readerm/reader/foliate", "readerm/reader/foliate"),
    ("ui", "ui"),
]
datas += collect_data_files("textual")

hiddenimports = [
    "PyQt6",
    "PyQt6.QtWidgets",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
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
    "PIL.Image",
    "PIL.ImageDraw",
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
    "readerm.shelves",
    "readerm.localapi",
    "readerm.sources.weebcentral",
    "readerm.sources.mangakatana",
    "readerm.sources.kagane",
    "readerm.sources.comix",
    "readerm.sources.vymanga",
    "readerm.sources.mangadotnet",
    "logging.handlers",
]
hiddenimports += collect_submodules("readerm")
hiddenimports += collect_submodules("textual.widgets")

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

if sys.platform == "darwin" and not ONEFILE:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="io.github.mangasurf.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
        },
    )
