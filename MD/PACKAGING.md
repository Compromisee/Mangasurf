# Packaging — building an all-inclusive executable (v1.7.0)

This guide produces a standalone **Mangasurf v1.7.0** executable containing the
GUI, TUI and CLI in one binary — no Python installation needed on the target
machine.

| Command | Result |
|---|---|
| `Mangasurf.exe` (double-click) | **Launcher window** — pick any interface |
| `Mangasurf.exe gui` | Desktop app with 3D Depth Carousel & Foliate reader |
| `Mangasurf.exe menu` | Interactive terminal menu |
| `Mangasurf.exe tui` | Full-screen terminal UI |
| `Mangasurf.exe server` | LAN server for your phone |
| `Mangasurf.exe server --gui` | ...with its control window |
| `Mangasurf.exe opds` | OPDS 1.2 catalog for Readest, Panels, Aldiko |
| `Mangasurf.exe <manga-url> --per 10` | CLI download (32 sources supported) |
| `Mangasurf.exe search "one piece"` | CLI search |
| `Mangasurf.exe resume` | Resume interrupted download |

Double-clicking opens the **launcher**, not the desktop app. The exe is five
programs in one, and a double-click used to commit you to the GUI with no way
to reach the TUI, the menu or the phone server without a terminal. Reaching
the desktop app is now one click, and `Mangasurf.exe gui` still goes straight
there, so an existing shortcut is unaffected.

The build is driven by **[`Mangasurf.spec`](Mangasurf.spec)** and the
unified entry point **[`launcher.py`](launcher.py)**.

---

## 1. Prerequisites

- Python **3.9 – 3.12** (PyInstaller support is best here; 3.13 usually works too)
- A clean **virtual environment** (strongly recommended — PyInstaller bundles
  everything importable, so a lean venv means a smaller exe)

```bash
git clone https://github.com/Compromisee/mangasurf.git
cd MDL

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install pyinstaller
```

> Build on the OS you are targeting. PyInstaller does **not** cross-compile:
> a Windows exe must be built on Windows, a macOS app on macOS, etc.

---

## 2. Build

### One-folder build (recommended)

Fast startup, easy to debug, updates only changed files:

```bash
pyinstaller Mangasurf.spec
```

Output: `dist/Mangasurf/` — ship the whole folder. The executable is
`dist/Mangasurf/Mangasurf(.exe)`.

### One-file build

A single portable executable (slower startup — it unpacks to a temp dir):

```bash
pyinstaller Mangasurf.spec -- --onefile
```

Output: `dist/Mangasurf.exe` (or `dist/Mangasurf` on macOS/Linux).

### Clean rebuild

```bash
pyinstaller Mangasurf.spec --clean --noconfirm
```

---

## 3. What the spec bundles

- The whole `mangasurf` package (CLI + TUI + GUI + engine)
- `mangasurf/gui/web/` — the GUI's HTML/CSS/JS (the code auto-detects the
  PyInstaller location via `sys._MEIPASS`)
- Textual's data files (TUI styling)
- pywebview's platform backends as hidden imports (WinForms/EdgeChromium on
  Windows, Cocoa on macOS, GTK/Qt on Linux — only the matching one loads)
- Rotating-log handler (`logging.handlers`)

Excluded to keep size down: tkinter, numpy/matplotlib/etc. (unused).

Typical sizes: roughly 80–140 MB one-folder, 40–80 MB one-file (varies by
OS and installed backends). Measured on Linux with every extra installed:
**138 MB one-folder, 57 MB one-file** — both verified to launch, route
every subcommand, and serve the phone UI from inside the bundle.

UPX compression is deliberately **off** in the spec. It routinely trips
antivirus heuristics on a freshly built, unsigned exe, and the saving is
not worth a download that gets quarantined before it runs.

---

## 4. Platform notes

### Windows

- The exe uses **Microsoft Edge WebView2** for the GUI. Windows 11 and
  updated Windows 10 machines already have it; otherwise users can install
  the [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).
- The spec sets `console=True` so `tui` / CLI subcommands work. Double-click
  still opens the GUI, but with a console window behind it. If you want a
  console-free GUI exe, build a second binary: copy the spec, set
  `console=False`, name it `MangaDLGUI`, and ship both.
- An icon is used automatically if `docs/icon.ico` exists.
- SmartScreen may warn on unsigned exes — sign the binary
  (`signtool sign /fd SHA256 ...`) or tell users to click "More info → Run
  anyway".

### macOS

- The one-folder build also produces **`dist/Mangasurf.app`** for
  double-click launching; the CLI/TUI binary is inside
  `Mangasurf.app/Contents/MacOS/`.
- Gatekeeper blocks unsigned apps: either
  `codesign --deep -s "Developer ID Application: ..." dist/Mangasurf.app`
  and notarize, or instruct users to right-click → Open the first time.
- Build separate x86_64 / arm64 binaries on the corresponding Macs (or use
  `target_arch='universal2'` in the EXE section if all deps provide
  universal wheels).

### Linux

- The GUI needs WebKitGTK at runtime:
  `sudo apt install gir1.2-webkit2-4.1` (Debian/Ubuntu) or the distro
  equivalent. Alternatively `pip install pywebview[qt]` **before building**
  so the Qt backend is bundled.
- Build on the **oldest** distro you want to support (glibc compatibility).
- Mark the binary executable: `chmod +x dist/Mangasurf/Mangasurf`.

---

## 5. Testing the build

```bash
# GUI
dist/Mangasurf/Mangasurf

# CLI
dist/Mangasurf/Mangasurf --help
dist/Mangasurf/Mangasurf search "vinland saga"

# TUI (run from a real terminal)
dist/Mangasurf/Mangasurf tui
```

Smoke checklist:

- [ ] GUI opens, themes/orbs/dot-matrix render
- [ ] Search returns covers; manga page loads
- [ ] A 1-chapter download completes and packs a CBZ
- [ ] Library/bookmarks persist (`~/.mangasurf/`)
- [ ] `search`, `info`, `resume`, `tui` subcommands work
- [ ] Log file appears in `~/.mangasurf/logs/`

User data (settings, library, bookmarks, logs, job journal) always lives in
`~/.mangasurf/`, never next to the exe — so upgrading is just replacing
the binary/folder.

---

## 6. Releasing on GitHub

```bash
# tag and build per platform, then:
gh release create v2.5.0 \
    dist/Mangasurf-windows-x64.zip \
    dist/Mangasurf-macos-arm64.zip \
    dist/Mangasurf-linux-x64.tar.gz \
    --title "v2.5.0" --notes-file CHANGELOG.md
```

Suggested archive naming: `Mangasurf-<os>-<arch>.<zip|tar.gz>` with the
one-folder build zipped inside.

### CI (GitHub Actions Automation Suite)

Mangasurf ships with 8 dedicated production GitHub Actions workflows in `.github/workflows/`:

1. **`release.yml`**: Multi-platform PyInstaller standalone onefile builder across Windows x64 (`.exe`), Linux x86_64 (`.tar.gz`), macOS ARM64 Apple Silicon (`.zip`), and macOS Intel (`.zip`). Automatically formats release notes from `MD/CHANGELOG.md`, generates `SHA256SUMS.txt`, and publishes GitHub Releases.
2. **`ci.yml`**: Multi-OS & Multi-Python (3.10–3.13) test matrix running the full pytest suite, flake8 linting, and web asset syntax validation.
3. **`nightly.yml`**: Daily automated bleeding-edge onefile builds and continuous pre-release publishing.
4. **`source-health.yml`**: Scheduled 6-hour radar testing and uptime monitoring for all 32 scraper sources.
5. **`pages.yml`**: Automated zero-config deployment of the animated landing page (`docs/`) to GitHub Pages.
6. **`docker.yml`**: Multi-arch container image builder (`linux/amd64`, `linux/arm64`) publishing headless server and OPDS catalog to GitHub Container Registry (`ghcr.io/compromisee/mangasurf`).
7. **`security.yml`**: GitHub CodeQL static code analysis, Bandit Python AST security scanner, and dependency vulnerability audits.
8. **`pypi.yml`**: Python package build (`sdist` & `bdist_wheel`) and twine validation pipeline.

---

## 7. Troubleshooting builds

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` at runtime | Add the module to `hiddenimports` in the spec and rebuild. |
| GUI opens blank / file not found | Web assets missing — confirm the `datas` entry and that `run_gui` resolves `sys._MEIPASS` (already handled). |
| Huge executable | Build in a clean venv; check `excludes`; avoid installing dev tools in the build env. |
| Antivirus flags the exe | Common with PyInstaller one-file. Prefer one-folder, sign the binary, or submit a false-positive report. |
| `webview` backend error on Linux | Install WebKitGTK (`gir1.2-webkit2-4.1`) or rebuild with `pywebview[qt]` installed. |
| Windows: console floods with `window.native` / recursion errors | Bridge noise from Edge's accessibility layer probing pywebview's .NET object; handled in-app since v2.6.1. If accompanied by `E_NOINTERFACE` COM errors, the target machine's **WebView2 Runtime is outdated** — install the current [Evergreen WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). |
| TUI garbled on Windows | Use Windows Terminal (not legacy conhost). |
