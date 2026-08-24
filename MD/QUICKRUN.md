# QUICKRUN.md — running Mangasurf without packaging it

For running from a source checkout. If you want a single `.exe`/`.app` to
hand someone, that is [PACKAGING.md](PACKAGING.md) instead.

---

## The one-liner

```bash
git clone https://github.com/Compromisee/mangasurf && cd mangasurf
pip install -e .
mangasurf gui
```

`pip install -e .` puts the `mangasurf`, `mangasurf-gui` and `mangasurf-tui`
commands on your PATH and keeps them pointed at the checkout, so edits take
effect immediately with no reinstall.

---

## Without installing anything

Every entry point also works as a module, straight out of the folder:

```bash
python -m mangasurf gui              # desktop window
python -m mangasurf tui              # terminal UI
python -m mangasurf server           # LAN server for your phone
python -m mangasurf --help           # the CLI
```

You still need the dependencies:

```bash
pip install -r requirements.txt        # or: pip install -e .
```

---

## What needs what

| You want | Install | Run |
|----------|---------|-----|
| CLI downloads | `pip install -e .` | `mangasurf <url>` |
| Terminal UI | `pip install -e .` | `mangasurf tui` |
| Desktop window | `pip install -e ".[gui]"` | `mangasurf gui` |
| Phone / LAN server | `pip install -e ".[server]"` | `mangasurf server` (or `readerm server`) |
| OPDS catalog | `pip install -e ".[server]"` | `mangasurf opds` (or `readerm opds`) |
| Everything | `pip install -e ".[all]"` | |

The desktop window needs `pywebview`, which needs a system webview:

* **Windows** — WebView2, already present on Windows 11 and most Windows 10.
* **macOS** — WKWebView, built in.
* **Linux** — `sudo apt install python3-gi gir1.2-webkit2-4.1` (or your
  distro's WebKitGTK package).

No webview? `mangasurf tui` and the CLI need none of it, and
`mangasurf server` gives you the full UI in an ordinary browser.

---

## Running it from a browser instead

Often the easiest path on a headless box or a Linux machine with no WebKit:

```bash
python -m mangasurf server --port 8577
```

It prints a URL and an access token. Open it on this machine, or on a phone
on the same Wi-Fi. Downloads still happen on the host — the phone is a
remote control, and closing its browser does not stop a job.

Reading works over the LAN too: pages and CBZ files stream from the host with
byte ranges, so a big archive opens without downloading it whole first.

For a quick local poke with no token:

```bash
python -m mangasurf server --host 127.0.0.1 --no-auth
```

Do not use `--no-auth` on a shared network.

---

## Rebuilding the HeroUI bundle

Only needed if you change anything under `ui/`. The built output is
committed, so a normal checkout never touches Node.

```bash
npm --prefix ui install
npm --prefix ui run build          # writes mangasurf/reader/app/vendor/
npm --prefix ui run build -- --watch
```

Node is a developer tool here. The packaged app is built by PyInstaller
alone, and someone installing from pip never needs npm.

---

## Running the tests

```bash
pip install pytest playwright
python -m playwright install chromium
python -m pytest -q
```

Roughly 1450 tests. The browser-driven ones skip themselves cleanly if
Chromium is missing, so a partial environment still gets a useful run.

Faster loops:

```bash
python -m pytest tests/test_v101_keys.py -q      # one file
python -m pytest -q -k "shelf or lock"           # by name
python -m pytest -q -x --lf                      # stop at the first failure,
                                                 # then re-run just it
```

---

## Where your data lives

Everything is under `~/.mangasurf/` (`%USERPROFILE%\.mangasurf` on Windows):

| File | What it holds |
|------|---------------|
| `library.json` | every downloaded series and chapter |
| `reading.json` | reading positions |
| `shelves.json` | library folders, tags, locks |
| `bookmarks.json`, `bookmark_folders.json` | bookmarked series |
| `annotations.json` | page bookmarks and notes |
| `tracking.json` | watched series, read/unread |
| `config.json` | settings |
| `lock.json` | the app passcode verifier — never the passcode |

`mangasurf api paths` prints all of them as JSON, with a stat for each.

Downloads go wherever you set the output folder; `mangasurf config` shows it.

To start clean, move `~/.mangasurf` aside — the app rebuilds it. Nothing is
written outside that folder and your download folder.

---

## Common problems

**`ModuleNotFoundError: mangasurf`** — run from the repo root, or
`pip install -e .`.

**The window opens white/blank** — a webview problem, not Mangasurf. Try
`mangasurf server` and use a browser; if that works, the app is fine and the
webview is not.

**`Flask is not installed`** — `pip install -e ".[server]"`.

**Icons show as words like `settings`** — the Material Symbols font has not
loaded. It reveals itself once loaded and gives up after 2.5s, so this is
usually a slow first paint rather than a fault.

**Covers are blank in search results** — some sites serve a placeholder to
anyone who hotlinks. Those hosts are fetched through Python and cached; if a
*new* site does it, that host needs adding to `HOTLINK_PROTECTED` in
`mangasurf/reader/app/app.js`.

**Tests fail with a Playwright error** — `python -m playwright install
chromium`. On Linux you may also need
`python -m playwright install-deps chromium`.

---

## A quick tour of the layout

```
mangasurf/
  cli.py            the command line
  gui/__init__.py   Api — every method the UI can call
  reader/
    app/            the front-end (HTML/CSS/JS, no framework)
      app.js          controller
      manga-view.js   the page renderer, a custom element
      shelves.js      the library tree
      keys.js         the keymap
      vendor/         the built HeroUI bundle
    api.py          reader endpoints, mixed into Api
    assets.py       the local asset server
  server.py         the LAN/phone server
  localapi.py       the read-only JSON API (see AGENT.md)
  sources/          one module per site
MD/                 all documentation except README.md
ui/                 the HeroUI build (Node, developer-only)
tests/
```

The front-end is plain ES modules — no bundler, no build step, no JSX. Edit a
file and reload.
