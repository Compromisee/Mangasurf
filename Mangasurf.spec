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

# ─── Hard build-time dependency guard ────────────────────────────────────────
# curl_cffi is the ONLY HTTP layer in Mangasurf (``requests`` was removed).
# If it is not importable in the build environment, PyInstaller silently skips
# it and ships an exe that dies at runtime with
#     ModuleNotFoundError: No module named 'curl_cffi'
# (seen in a onefile build of the phone-server / opds / gui children).
# Fail *now*, with a clear message, rather than letting a broken binary out.
try:
    import curl_cffi  # noqa: F401
    import cffi  # noqa: F401
except ImportError as _exc:
    _curl_err = _exc

    # The likeliest cause is an interpreter mismatch: curl_cffi is installed
    # in a .venv, but PyInstaller was invoked with the *base* interpreter
    # (a bare `pyinstaller` often resolves to a different Python than the
    # `python` whose venv you activated). Detect that and say exactly what
    # to run, instead of telling the user to "just install curl_cffi" (which
    # they may have already done — into the wrong interpreter).
    def _venv_with_curl(root):
        """Return a venv interpreter that bundles curl_cffi, or None."""
        site_pkg_rel = ("Lib", "site-packages") if sys.platform == "win32" \
            else ("lib", "site-packages")
        for name in (".venv", "venv", "env", ".env"):
            base = os.path.join(root, name)
            sp = os.path.join(base, site_pkg_rel[0], site_pkg_rel[1])
            if not os.path.isdir(os.path.join(sp, "curl_cffi")):
                continue
            for rel in (os.path.join("Scripts", "python.exe"),
                        os.path.join("bin", "python"),
                        os.path.join("bin", "python3")):
                cand = os.path.join(base, rel)
                if os.path.isfile(cand):
                    return cand
        return None

    build_python = sys.executable
    venv_py = None
    for root in (os.getcwd(), os.path.dirname(os.getcwd())):
        venv_py = _venv_with_curl(root)
        if venv_py:
            break
    hint = ""
    if venv_py:
        in_venv = sys.prefix != sys.base_prefix
        hint = ("\n\ncurl_cffi IS installed, just in the wrong interpreter.\n"
                f"    PyInstaller is running on:  {build_python}\n"
                f"    curl_cffi was found in:      {venv_py}\n"
                + (f"\nThis process IS a venv but it does not have curl_cffi.\n"
                   "    Activate it and pip install curl_cffi there, or use:\n"
                   if in_venv else
                   f"\nYou are running the BASE interpreter, not your venv.\n"
                   "Activate the venv or build with its Python explicitly:\n")
                + f"    \"{venv_py}\" -m PyInstaller Mangasurf.spec -- --onefile\n"
                + "    # or, in a shell:\n"
                + "    .venv\\Scripts\\activate  &&  pyinstaller Mangasurf.spec -- --onefile")
    elif _exc.name == "curl_cffi" and not hint:
        hint = ("\n\nIt was not found in any venv either. Install it into the "
                "interpreter PyInstaller is using:\n"
                f"    {build_python} -m pip install curl_cffi cffi")

    raise SystemExit(
        "Build aborted: the interpreter running PyInstaller cannot import "
        f"curl_cffi (and cffi).\nPython: {build_python}\n\n"
        "Without curl_cffi PyInstaller ships an exe that crashes immediately "
        f"with \"No module named 'curl_cffi'\" ({_curl_err})." + hint
    ) from _exc

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
    # pywebview's Windows backend is pythonnet (the .NET CLR). Missing /\
    # misbundled versions have been seen to abort a fresh GUI child with a
    # fatal CLR access violation, so pull the runtime modules in explicitly.
    "pythonnet",
    "clr",
    "clr_loader",
    "pythonnet.load",
    "webview.lib",
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
    # curl_cffi is the HTTP layer; cffi backs its compiled _wrapper extension.
    # Listed explicitly so the bundle is never built without them.
    "curl_cffi",
    "curl_cffi.requests",
    "curl_cffi.requests.exceptions",
    "cffi",
    "_cffi_backend",
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
