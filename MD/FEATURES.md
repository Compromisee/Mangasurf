# Features

Everything Mangasurf does, grouped by what you are trying to achieve.

For command syntax see **[SYNTAX.md](SYNTAX.md)**. For what changed in each
release, see **[CHANGELOG.md](CHANGELOG.md)**.

**Contents**

- [At a glance](#at-a-glance)
- [Sources](#sources)
- [Searching and browsing](#searching-and-browsing)
- [Downloading](#downloading)
- [Output files](#output-files)
- [Reliability](#reliability)
- [The reader](#the-reader)
- [The desktop app](#the-desktop-app)
- [The queue](#the-queue)
- [Statistics](#statistics)
- [Library and bookmarks](#library-and-bookmarks)
- [Reading progress and updates](#reading-progress-and-updates)
- [Cover rebuilder](#cover-rebuilder)
- [Background mode](#background-mode)
- [Privacy and safety](#privacy-and-safety)
- [The command line](#the-command-line)
- [Picking an interface](#picking-an-interface)
- [Reading it in an e-reader](#reading-it-in-an-e-reader)
- [Covers for folders of images](#covers-for-folders-of-images)
- [Using it from your phone](#using-it-from-your-phone)
- [The terminal menu and TUI](#the-terminal-menu-and-tui)
- [Configuration](#configuration)
- [Packaging](#packaging)
- [Python API](#python-api)

---

## At a glance

| | |
|---|---|
| **Sources** | 32 registered, covering 45+ sites |
| **Interfaces** | desktop app, terminal menu, TUI, CLI, phone server, OPDS catalog |
| **Output** | CBZ, PDF, EPUB, raw images — several at once |
| **Concurrency** | multiple series in parallel, each with parallel chapters and pages |
| **Resume** | per-job journal; a crash costs the current chapter, not the run |
| **Requirements** | Python 3.9+; everything else is optional |

All four interfaces share one engine, one settings file and one library, so
a change in the app is visible to the CLI immediately.

---

## Sources

### Registered sources

| Source | Site | Notes |
|---|---|---|
| MangaDex | mangadex.org | Official JSON API; language and scanlator preferences |
| Mangakatana | mangakatana.com | Obfuscated JS page decoding |
| Natomanga | natomanga.com | Manganato/Mangakakalot successor, JSON chapter endpoint |
| Weeb Central | weebcentral.com | Behind Cloudflare — see below |
| Asura Scans | asuracomic.net | Uses the JSON API; the website itself is an SPA |
| Flame Comics | flamecomics.xyz | Whole catalogue in one Next.js payload |
| Demonic Scans | demonicscans.org | HTML-fragment search backend |
| Madara Scans | madarascans.org | Themesia theme, not the Madara theme |
| Omega Scans | omegascans.org | |
| ManhwaRead | manhwaread.com | |
| **Madara Sites** | 10 sites | One source fanning out across ten Madara-theme installs |
| Witch Scans | witchscans.com | |
| Writers' Scans | writerscans.com | Page URLs rebuilt from `uid` attributes |
| Webtoons | webtoons.com | |
| Mangadass | mangadass.com | 18+ |
| Manhwa18 | manhwa18.net | 18+ |
| Manga18.club | manga18.club | 18+ |
| HentaiAkane | hentaiakane.com | 18+ |
| nhentai | nhentai.net | 18+ |

**Madara Sites** is a single entry that covers Toonily, Manhua Plus, Manhua
Top, Manhwa Top, MangaRead, Coffee Manga, Manga Sushi, MangaOwl, MangaGG and
Setsu Scans. Members have namespaced ids (`madara.toonily`) and can be
addressed individually, but they share one row in Settings.

Three unrelated things are called "Madara" and are easy to confuse: the
**Madara Sites** aggregate, the site **Madara Scans** (which does *not* run
the Madara theme), and the internal scraping engine for that theme.

### How sources behave

- The source is detected from any pasted URL, including URLs carrying
  tracking parameters.
- Bare MangaDex UUIDs are accepted in place of a URL.
- `-s/--source` forces a specific source; a disabled source still works from
  a direct URL.
- Each source declares its own capabilities (genres, browsing, languages,
  scanlators, Cloudflare), and the UI adapts rather than showing dead
  controls.
- Adding a site is one file plus one registry line — nothing in the CLI, the
  menu or the app needs to change.
- Shared plumbing gives every source retries with backoff, rate-limit
  handling, `Retry-After` support, magic-byte image validation and
  per-chapter `Referer` overrides for hotlink-protected CDNs.

### Cloudflare

Weeb Central and Setsu Scans sit behind Cloudflare. With
[FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) running they
work normally. Without it they fail fast and fall back to a stored snapshot
instead of stalling every other source — a missing solver used to cost 62
seconds of retries per request.

---

## Searching and browsing

- One query searches every enabled source in parallel.
- Duplicates across sites are merged, with the highest-ranked copy kept and
  the others listed as "also on". Matching is Unicode-safe, so CJK titles
  are never collapsed together.
- Interleave mode round-robins the sources instead of grouping them.
- Filters: sort order, ascending/descending, status, series type, genre
  (multiple, with any/all matching), chapter-count range, official-only.
- Results whose data a source does not report are kept rather than silently
  dropped, so a filter cannot make a whole source vanish.
- An empty search box shows a trending/browse feed instead of a blank page.
- Search history with type-ahead suggestions.
- Paste a series URL into the search box to jump straight to it.

### Results you already have

Settings → **Already downloaded** controls what happens to search results
that are in your library:

| Mode | Behaviour |
|---|---|
| **Show normally** | No change |
| **Darken** (default) | Dimmed; hovering fills the cover up to the fraction you have and shows the percentage |
| **Hide** | Removed from the grid, with a note saying how many were hidden |

The percentage is only shown when the source reports a total chapter count.
When it does not, the badge shows the number of chapters you have rather
than inventing a percentage.

---

**Content filters.** A collapsible panel on the Search view, applied to every
source at once: minimum and maximum chapters, blocked titles, tags and authors
(substring matches, case-insensitive), hide results with no cover, and safe
mode to drop adult ratings where the source reports them. The panel header
summarises what is active — `>= 10 ch . <= 200 ch . 4 blocked . safe mode`.

Chapter limits only apply when a count is actually known. Many sources never
report one — MangaDex leaves it empty for every ongoing series — so those
results are kept rather than letting a filter make whole sources disappear.
**Strict chapter range** turns that leniency off when you want a hard filter.


**The series page.** Clicking a search result or a library card opens a detail
page rather than starting anything: cover, title, source, authors and artists,
tags, a description with show-more, and the facts a source reports — year,
type, demographic, language, content rating, last chapter.

Download options sit beside it (format, bundling, save-to), with a chapter
picker underneath: All / None / New only / Latest / Invert, quick-select
ranges like `1-20, 25, 30-40`, min and max chapter, a name filter, sort order
and hide-downloaded. Chapters already on disk are marked, and a **Read** button
appears when there is something to read.

**Bookmarks.** A tab of everything saved, with folders, a folder filter and a
name filter. Bookmark and watch buttons live on the series page.


## Downloading

- Chapter selection: `all`, `5`, `23.5`, `1-20`, `1,5,10-20`, `50-`, `-10`,
  `latest`, `first`.
- Several series download at once (configurable limit), each with parallel
  chapters (1–8) and parallel pages within a chapter (1–10).
- Every progress event carries its job id, so two series downloading
  simultaneously never mix their chapters or their counters.
- Queue jobs while others run; pause and resume the queue without
  interrupting a download in flight.
- A "new only" shortcut selects just the chapters you do not have.
- Large-download confirmation above a configurable threshold.

---

## Output files

- **CBZ**, **PDF** (pages sized exactly to each image), **EPUB** (with a
  chapter table of contents), or raw **images**.
- Produce several formats in one run with `--also`.
- Bundling: everything in one file, one file per chapter, or one file per
  every N chapters.
- Naming templates with `{title}`, `{chapter}`, `{chapters}`, `{start}` and
  `{end}` placeholders, with a live preview in Settings.
- Output goes into a per-series folder, with the cover saved alongside.
- Optionally open the folder when a download finishes.

---

## Reliability

- **Crash-safe resume.** Page-count-verified checkpoints, atomic `.part`
  writes, and one journal file per job. Resume from the app banner or
  `mangasurf resume`; finished chapters are skipped and a partial chapter
  continues from the exact page it stopped at. Concurrent jobs each get
  their own journal, so one finishing cannot erase another's.
- **Fail fast on dead ends.** 404 and 410 are not retried — a wrong genre
  path used to cost 31 seconds per attempt.
- **Timeouts everywhere that touches the network**, including the genre
  listing that runs at startup.
- **Rotating log file** shared by every interface, with export and clear
  actions in Settings.
- Failures are reported per chapter; one bad chapter does not abort a run.

---

## The reader

Mangasurf reads what it downloads. The engine is a fork of
[foliate-js](https://github.com/johnfactotum/foliate-js) (MIT) — the engine
behind [Foliate](https://github.com/johnfactotum/foliate), and the one Readest
forked when it went cross-platform.

Foliate *itself* is GTK4 + GJS + WebKitGTK and does not run on Windows; MSYS2,
the only realistic Windows GTK channel, ships neither `gjs` nor `webkitgtk`.
The engine has no GTK, GJS or Node calls at all, so it runs unchanged in
WebView2 on Windows, WebKitGTK on Linux and WKWebView on macOS.

**Reading modes.** Webtoon (continuous vertical, no gaps), vertical
(continuous, with gaps), paged left-to-right, and paged right-to-left for
Japanese reading order — where the right-hand key turns *back* a page and a
double-page spread reverses so the binding sits in the middle.

Webtoon mode is this fork's own work: upstream sends comics to a fixed-layout
renderer that only paginates, so long-strip comics were unreadable.

**Auto-scroll.** Hands-free reading for long strips. `S` starts and stops it,
`+` and `−` change speed, and it stops on its own at the end of a chapter.

**Progress that tells the truth.** Position is measured in pages, not scroll
pixels. That matters because a lazy-loaded strip *grows* as it loads — an
80vh placeholder becoming a real 1200px image adds height below you — so a
pixel-based fraction slides backwards while you sit still, and a finished
chapter reads 89%. Page counts are known when the chapter opens and never
change.

**Rebindable shortcuts.** Every action is in one list, so the settings page,
the help sheet and the dispatcher cannot disagree. 26 actions, each
rebindable by clicking its key and pressing a new one, with conflicts
flagged rather than silently accepted. Four presets ship — Mangasurf, Vim
(hjkl), WASD and one-hand — and only your changes are saved, so a later
release can improve a default without pinning you to the old one.

**Page controls.** Fit contain / width / height / original, zoom, page width,
gap between pages, and a double-page spread toggle.

**Themes.** Eight — Midnight, Mocha, Forest, Plum, Ocean and OLED in the dark
set; Light and Paper in the light set — with six accent colours, a square-corner
mode, an animations toggle and an optional dot-matrix background. Each theme carries a
*page* filter as well as chrome colours, because a dark mode that only darkens
the frame still fires a white page at you in a dark room. Filters can also be
set by hand: dim, dimmer, sepia, grayscale or invert.

**What it opens.** A packaged `.cbz`, `.epub`, `.pdf`, `.mobi`, `.azw3` or
`.fb2` — *or* a chapter that is still a plain folder of `.jpg` files, which an
ordinary e-reader cannot open at all. Pages stream one at a time, so a chapter
is readable while the rest of it is still downloading. `.cbr` is recognised and
honestly refused: unrar is not bundled.

**Everything else in one window.** Library with a continue-reading shelf and a
stats strip, source search, the download queue, a chapter list with per-chapter
progress, bookmarks and notes, resume-where-you-stopped, full-text search
inside EPUB and PDF, tap zones, and a keyboard-shortcut sheet on `?`.

**On your phone.** `python server.py` serves the same reader over the LAN, so a
phone gets webtoon mode, themes and auto-scroll too.

**In the reader.** A pages sidebar (`P`) listing every page by name, with the
current position marked, a filter box, and the book's cover in the header.
Bookmarks appear on hover beside each page and stay visible once set. The icon
in the top-left corner is the `cover.ext` from the chapter's folder.

**Minimalist mode** (`M`) hides everything but the page; move the pointer to the
top or bottom edge and the toolbars come back.


## The desktop app

### Search

- Cover-art grid with staggered entrance animations.
- Animated hero that compacts to the top once results arrive.
- Source badges, "also on" counts, and an active-filter indicator.
- Covers that require a referrer are proxied server-side so they render
  instead of showing a blank tile.

### Series page

- Cover, title, author, status, tags, description, bookmark toggle.
- Downloaded chapters are highlighted with a counter pill — and the counter
  belongs to the series you are looking at, not whatever is downloading.
- All / None / New only / Latest shortcuts, plus a quick-range box.
- Format, bundling and destination pickers.

### Appearance

- Six themes (Midnight, Mocha, Forest, Plum, Ocean, Light) and six accents.
- Rounded or square corners throughout.
- Animations toggle, honouring the OS "reduce motion" setting.
- Optional animated dot-matrix backdrop.
- Google Material Symbols throughout — no emoji.
- Collapsible side rail, configurable grid density.

### Other views

- **Bookmarks** with drag-and-drop folders, optional per-folder locking.
- **Library** listing every downloaded series, its parts and their sizes,
  with missing files flagged and a **Read** button that opens your
  configured reader.
- **Updates** for watched series.
- **Tools**: disk usage, library health, search history, moved-file repair,
  and the cover rebuilder.

---

## The queue

- One collapsible tile per series rather than a flat list of chapters.
- Collapsed: cover thumbnail, source, live transfer-rate sparkline, ETA, and
  a `done/total` chapter pill.
- Expanded: larger cover, source, speed, ETA, bytes downloaded, overall
  progress, and the chapters currently in flight with their page counts.
- Chapter rows update in place, so an open tile does not flicker or collapse
  while you are reading it.
- Overall progress and the Stop button live in the queue card itself.
- **Advanced logging** (Settings, or the checkbox on the Queue tab) records
  every engine event — page fetches, retries, packaging — instead of just
  milestones. Off by default.

---

## Statistics

A **Stats** tab with four views.

**Activity** — a GitHub-style contribution calendar over the last year, three
months or six, one square per day tinted by how much you downloaded. Alongside
it: current streak, longest streak, active days and the busiest single day,
plus totals for chapters, pages, bytes, jobs and time spent.

**Sources** — every site you have downloaded from, ranked by volume, with a
bar proportional to its share and the bytes it accounts for.

**Library** — series held, chapters held, readable items, sources used, and
the biggest series by chapter count.

**Reading** — how many books are in progress against finished, pages read, and
the last few things you opened, each resumable in one click.

## Library shelves

Folders for the books you have on disk, stored in `~/.mangasurf/shelves.json`.
They are kept separate from bookmark folders on purpose: those group remote
series you may not have downloaded, and one record trying to describe both
would end up half empty either way.

- **Nested folders**, shown as a tree beside the library grid. They arrive
  collapsed; selecting one narrows the grid, and typing then searches within
  it.
- **Tags** on any shelf, with tag pills that filter the tree. A parent stays
  visible when a descendant matches, so filtering never hides the path to
  the thing you asked for.
- **Pin to top**, for the two or three shelves you actually use.
- **Optional passcode locks**, independent of pinning — "lock" and "ask every
  time" are separate choices.
- Books are filed by library key rather than by path, so relocating a
  download does not knock it off its shelf.

**What a lock does, precisely.** A locked shelf's titles are never sent to
the page. Python withholds them from the grid, from the continue-reading row
and from `reader_open`, so a path you kept from earlier will not open the
book either. The tree still shows the padlock and an honest count — "12
hidden" — because pretending the shelf is empty is its own kind of lie.
Locks reuse the app passcode's PBKDF2-HMAC-SHA256 verifier at 240,000 rounds
with a per-shelf salt; the passcode is never stored and the salt never
reaches the interface. Unlocking lasts for the session only.

**It is a privacy screen, not encryption.** The files stay readable on disk
and anyone with the machine can open them directly. It stops someone
glancing at your library; it is not a vault.

---

## Library and bookmarks

- `~/.mangasurf/library.json` records every downloaded chapter per series:
  name, page count, date, output files, title and folder.
- Multi-part downloads are tracked part by part, with file sizes.
- Missing output files are detected and flagged, and moved files can be
  found again and relinked.
- Bookmarks live in `~/.mangasurf/bookmarks.json`, organised into folders.
- Export the library as JSON, CSV or Markdown; import merges rather than
  overwrites.
- Notes, 0–5 star ratings, custom tags and named collections per series.

---

## Reading progress and updates

- Mark chapters read or unread, individually or in bulk.
- Per-series percentage and unread count; jump to the next unread chapter.
- Watch a series for new chapters; checks run in parallel across the
  watchlist and a failing site is skipped rather than fatal.
- New-chapter badges, acknowledged to clear.

---

## Cover rebuilder

Rebuild or replace the cover inside existing CBZ files — including ones
Mangasurf did not create.

- Point it at any folder; it works recursively.
- Understands Mangasurf's own names (`Chapters 001-050`) and third-party ones
  (`[Group] Title (2024) v03`, `Ch.001-036`, `Cap. 12`, `Episode 200`).
- Titles that happen to contain marker words survive intact — Chainsaw Man,
  Case Closed, Cells at Work, Eden's Zero.
- **Smart search** picks a cover automatically using your Settings source
  ranking, preferring a good resolution.
- Sort a flat folder of loose CBZ files into one folder per series.
- `--dry-run` to preview, `--sort-only` to organise without touching covers,
  `--replace` to overwrite existing artwork.

---

## Background mode

- **One app at a time.** Launching Mangasurf while it is already running
  raises the existing window instead of starting a second copy — which used
  to leave two tray icons and two download engines on the same library.
- Optional **system tray** mode: closing the window hides it and downloads
  keep running.
- The tray tooltip and menu show live speed, ETA, chapters remaining, queued
  jobs and each running download.
- Reopen, pause/resume the queue, or quit from the tray menu.
- Optional notification when a download finishes, de-duplicated so a repeated
  window event cannot produce a stream of balloons.
- The setting takes effect immediately — no restart.

Requires the `tray` extra (`pip install -e ".[tray]"`).

---

## Privacy and safety

- Optional **passcode lock**: PBKDF2-HMAC-SHA256, 240,000 rounds, per-install
  random salt, constant-time comparison. The passcode is never stored.
- A one-time recovery key is issued at setup, and the recovery flow is built
  into the lock screen.
- Attempt throttling after five failures with an escalating cooldown capped
  at 15 minutes.
- Auto-lock after N idle minutes, optional lock on start, optional cover
  blurring behind the lock screen.
- **Safe mode** hides adult-rated results; adult sources are tagged and can
  be disabled individually.
- Content filters for blocked tags, title words and authors.

---

## The command line

```
mangasurf <url>                    every chapter as one CBZ
mangasurf --url <url> -c 1-50 -f pdf --also epub
mangasurf --url <url> --per 10     one file per ten chapters
mangasurf resume                   continue an interrupted run

mangasurf search "query"           every enabled source at once
mangasurf search "query" --json    machine readable
mangasurf search "query" --urls    one URL per line, for pipes
mangasurf search "query" --open N  details for result N
mangasurf search "query" --download N

mangasurf library [--check]        what you have, and what moved
mangasurf covers <folder>          rebuild CBZ covers
mangasurf updates                  new chapters for watched series
mangasurf config --list|--set k=v
mangasurf sources [--enable|--disable|--rank]
mangasurf lock status|set|change|off
```

- Colour output with progress bars, percentages and ETA, degrading to plain
  ASCII when Rich is unavailable or output is piped.
- `--plain` for scripts and CI.
- Colours respect `NO_COLOR` and `FORCE_COLOR`.

Full reference in **[SYNTAX.md](SYNTAX.md)**.

---

## Picking an interface

`python landing.py` — or double-clicking the packaged `Mangasurf.exe` —
opens a small window listing all five interfaces, and starts whichever
you choose:

| | |
|---|---|
| **Desktop app** | the full window interface |
| **Terminal menu** | numbered prompts, no extra dependencies |
| **Full-screen TUI** | keyboard-driven, works over SSH |
| **Command line** | a shell with the CLI help, ready to type into |
| **Phone server** | serve the interface over Wi-Fi |

The terminal ones open in a real terminal window rather than a pipe, because
a TUI written to a pipe is useless.

It also solves the venv problem. Launching `tui.py` from a file manager does
not inherit your virtual environment, so the child gets the *system* Python,
which has none of Mangasurf's dependencies and dies with `ImportError` — a
failure that looks like a bug in the app. The launcher looks for a venv in
the interpreter it is already running under, `$VIRTUAL_ENV`, and then
`.venv`/`venv`/`env` in the project folder and up to two directories above
it. Whichever it picks is shown in the window, because "which Python is this
using" is the first question when something will not start.

A log panel sits collapsed at the bottom and opens on first launch, showing
the exact command that was run and anything the child said on the way out.

---

## Reading it in an e-reader

`python opdsserve.py` publishes your downloads as an **OPDS 1.2 catalog**, so
Readest, Panels, KyBook, Chunky, Aldiko, Thorium and anything else that
speaks OPDS can browse your library with covers and download straight from
your PC.

```
python opdsserve.py              # http://<this-pc>:8578/opds
python opdsserve.py --gui        # with a control window
python opdsserve.py --no-auth    # no password (trusted networks only)
```

Add the printed URL in your reader. The **password** is the same access
token as the phone server — any username works, because readers insist on a
username field and there is no second secret worth inventing.

Turn on **Settings → Phone server → Start the catalog with the app** and it
comes up whenever the desktop app does, sharing the process so it always
sees the library the app is writing.

### What the catalog contains

| Shelf | Contents |
|---|---|
| All titles | everything, alphabetically |
| Recently added | newest downloads first |
| By source | grouped by the site it came from |
| Alphabetical | A–Z shelves |
| Search | OpenSearch, so the reader gets a search box |

Each publication carries its cover, its chapter and page counts, its file
size, and one acquisition link per format you downloaded — CBZ, EPUB and PDF
each get the correct media type, which is what decides whether a reader
shows the book at all.

Entries use stable ids derived from the series URL, so a reader can tell an
existing book from a new one instead of re-downloading the shelf on every
sync. Files that have been moved or deleted since download are left out of
the feed rather than offered as a 404.

It runs on its own port (8578 by default) so the catalog and the phone
server can both be up at once.

---

## Covers for folders of images

A folder of loose page images — an unpacked chapter, an imported scan, a
`raw` dump — has no cover file, so every shelf that reads folders shows a
blank tile.

**Settings → Phone server → Covers for image folders**, the OPDS window, or
`mangasurf covers`, will give every such folder its own cover:

- the **first page** is used, sorted naturally so page 2 comes before
  page 10;
- the cover is **copied, never moved or re-encoded** — the page is still
  part of the chapter;
- the extension follows the source, so a PNG page yields `cover.png` rather
  than a PNG named `.jpg` that strict readers reject;
- `raw/` and other working folders are skipped;
- folders that already have a cover are left alone unless you ask to
  overwrite;
- **Preview** shows what would change before anything is written.

You can also point a single folder at a specific image to change its cover;
any cover under a different extension is removed, so readers cannot
disagree about which one wins.

---

## Using it from your phone & GUI Server Hub

You can launch and manage the LAN server directly from the **GUI Settings › Servers & OPDS Hub** or via CLI:

```
python server.py                  # http://<this-pc>:8577
python server.py --port 9000
python server.py --host 127.0.0.1 # this machine only
python server.py --no-auth        # skip the access token
```

### GUI Server & OPDS Hub Features:
- **Direct Start / Stop / Restart Controls**: Toggle the LAN Web Server and OPDS Catalog on the fly with live status badges.
- **Live Device Tracking & Active Sessions**: Real-time monitor displaying all connected mobile phones, tablets, e-readers, and desktop clients (device name, IP address, connection type, active requests, bandwidth, and last seen time).
- **QR Code Pairing**: Instant scan-to-connect QR codes for phone camera pairing.
- **Tailscale VPN Support**: Automatic detection of Tailscale mesh IPs for secure remote reading.
- **Autostart Options**: Configure LAN Server and/or OPDS Catalog to launch automatically with Mangasurf.
- **Real-Time Traffic Console**: Live log streaming with filtering for easy diagnostics.

**Everything runs on the host computer.** The phone sends the request; this
machine executes it. So:

- the phone never contacts a manga site — every scrape leaves the host's IP;
- files are written to the host's disk, in the host's output folder;
- the library, settings and job journals stay in the host's `~/.mangasurf/`;
- closing the browser, or leaving Wi-Fi range, does not interrupt a download.

It is the same UI, not a cut-down one: the page is served straight from
`mangasurf/gui/web`, with a small shim that makes `fetch` look like the
pywebview bridge it normally talks to. Layout adapts below 820px — the side
rail becomes a bottom bar and the cover grid reflows.

Two things cannot work remotely and say so rather than failing silently: the
**folder and file pickers** (a native dialog would open on the host's screen,
where nobody is looking — type the path instead), and **Open folder / Open in
reader**, which are allowed but act on the host.

### The access token

The token is a **saved setting**, not a value regenerated at each launch —
one that changed every restart meant re-pairing the phone every time and any
bookmarked link quietly breaking.

Set it in **Settings → Phone server** in the desktop app, in the server's own
window, or leave it and one is generated and saved on first run. Minimum 16
characters; only characters that survive a URL untouched are accepted, so the
printed link never needs escaping. Generated tokens skip `l`, `I`, `1`, `0`
and `O`, because this string gets copied off a screen by hand.

It is a shared secret over plain HTTP for a home network — do not
port-forward it.

### The control window

`python server.py --gui` opens a small window instead of running headless:
the link to open on your phone with a Copy button, the token and port with
validation as you type, a verbose toggle, and a live colour-coded log. The
log always shows rejected tokens and errors; verbose mode adds every call the
phone makes.

Requires the `server` extra (`pip install -e ".[server]"`).

---

## The terminal menu and TUI

**`mangasurf menu`** — a numbered menu needing no extra dependencies. Answer
with a number, `b` goes back, `q` quits. Covers search, download, library,
bookmarks, updates and settings.

**`mangasurf-tui`** — a full-screen Textual interface for working over SSH:
tabs for Search / Manga / Downloads / Settings, chapter multi-select, format
and bundling pickers, live progress and a colour log. Requires the `tui`
extra.

---

## Configuration

Everything lives in `~/.mangasurf/`:

| File | Contents |
|---|---|
| `config.json` | Settings and per-source configuration |
| `library.json` | What you have downloaded |
| `bookmarks.json` | Bookmarks and folders |
| `stats.json` | Download statistics |
| `jobs/` | Crash-resume journals, one per job |
| `logs/` | Rotating log files |

Settings are written atomically under a lock, so two saves at once cannot
clobber each other.

### Source ranking

- Drag to reorder in the app, or use the keyboard-friendly up/down buttons.
- Rank decides which copy wins when a series exists on several sites.
- Per-source overrides: enabled, searchable, result limit, duplicate weight,
  language, extra delay, free-text note.
- New sources are appended and ranked last; stale entries are pruned.
- The same ranking is used by the CLI, the app and the TUI.

---

## Packaging

`Mangasurf.spec` plus `launcher.py` build a standalone executable with
PyInstaller. Double-clicking it opens the **launcher window**; every
interface is also reachable as a subcommand (`Mangasurf.exe gui`,
`… menu`, `… tui`, `… server`).

Both one-folder and one-file modes are supported and verified to build and
run — 138 MB and 57 MB respectively on Linux with every extra installed. The
phone server works from inside the bundle: its web assets resolve through
`sys._MEIPASS`. See **[PACKAGING.md](PACKAGING.md)**.

---

## Python API

```python
from mangasurf.downloader import DownloadEngine, DownloadOptions

result = DownloadEngine(DownloadOptions(url="...", bundle=10)).run()
```

Sources can be used directly too:

```python
from mangasurf.sources import get_source, search_all

results = search_all("solo leveling")        # every enabled source
source = get_source("mangadex")
chapters = source.get_chapters(results[0]["url"])
```
