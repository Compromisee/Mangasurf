# Changelog

All notable changes to **ReaderM**, newest first.

This changelog starts fresh at v1.0.0 for the [Compromisee/Mangadl2](https://github.com/Compromisee/MangaDL2)
fork. Earlier upstream history is not carried over.

---

## v1.0.1 — Reading on a phone, a local API, and a keymap you can change

### The version number

The project renumbered from 3.2.4 to 1.0.0/1.0.1. Nothing regressed; the old
numbering had drifted from any release meaning. Three tests asserted the
version *number* (`major >= 2`, `startswith "3."`, `startswith "3.2"`) and
started failing on a release that had removed nothing. They now check what
they were really guarding: that the OPDS catalog still renders a feed, that
the version is a sane three-part number, and that the module agrees with the
packaging metadata.

### Added — read your library from your phone

`reader_open` hands the front-end URLs on the local asset server, which is
bound to 127.0.0.1 on purpose. On a phone that address is *the phone*, so
every page 404'd — and pointing it at the host's LAN address does not help
either: the asset server answers a non-loopback caller with 403. Both
measured.

New `/stream/page` and `/stream/book` routes proxy the bytes through the
Flask server that is already on the network, so there is still one door to
the LAN and one token. They honour `Range`, which is what lets an 88 MB CBZ
open at page one instead of after a full download. Confinement reuses
`AssetServer.is_allowed`, so the LAN route can never be more permissive than
the local one.

### Added — a read-only API for other programs

`GET /local/info | paths | books | reading | covers | sources | shelves |
stats` describes the install so another reader, a sync script or an agent can
find things without importing ReaderM or parsing its private JSON. Paths are
always absolute, books carry a stable key rather than a title, and every
response is an object with `ok`. Offline too: `readerm api books`, or
`from readerm import localapi`.

Locked shelves are respected through every one of those surfaces, and no
payload carries a salt, a hash or a passcode — there is a test that greps for
them. Documented in **MD/AGENT.md**.

### Added — rebindable keyboard shortcuts

The reader dispatched from `switch (e.key)` with the bindings written into
the case labels, so the binding, the action and the help text lived in three
places — and had already drifted, advertising keys the switch did not handle.
One `ACTIONS` list now feeds the defaults, the settings page, the help sheet
and the dispatcher. 26 actions, conflict detection, and four presets.

### Added — the app's own window frame

A themed titlebar with minimise, maximise and close, so the window controls
match the app instead of sitting in an OS-coloured strip above it. Closing
still honours *minimise to tray*, because that setting exists so a
300-chapter download survives the window being closed. `custom_titlebar: false`
restores the native frame — some Linux window managers handle frameless
windows badly, and there has to be a way back that is not editing JSON.

### Fixed — the reader's progress bar

Reported as inaccurate, sticking mid-chapter, and showing wrong percentages.
`fraction` was `scrollTop / (scrollHeight - clientHeight)`, and scrollHeight
grows all through a lazy-loaded chapter as placeholders become real images.
Measured on a 40-page strip: parked at scrollTop 4000 and untouched, the
fraction fell from 0.1411 to 0.1376 on its own — the bar slid backwards — and
the bottom of the book reported 89%.

It counts pages now. `setFraction` uses the same units, so the save/restore
round trip is exact: 0.50 used to come back as 0.456. A settle pass
re-applies a seek as the pages around it stop being placeholders.

Found while fixing that: at the very bottom the page counter said "10 / 11"
while the bar said 100%, because the midpoint rule cannot reach a final page
shorter than half the viewport — a 135px credits page under an 800px window.

### Fixed — chapters "not showing" on the manga screen

The chapter filters are per-series but live in a panel reused for every
series, so a minimum of 50 left over from one title emptied the next one.
Filters reset when a different series opens, and the empty state now names
the filters that are active and offers to clear them, instead of saying "No
chapters match those filters" with nothing to act on.

### Fixed — smaller things

* `readerm server` and `readerm opds` were documented but parsed as URLs to
  download, and their own flags were rejected before dispatch. They work.
* `localapi.sources()` called a function that does not exist inside a bare
  `except`, so it returned `[]` and looked like a build with no sources.
* `.btn.icon` had no base rule — only `.btn.icon.sm` — so icon-only buttons
  kept the text button's side padding and came out 50x38 instead of square.
* Covers had no radius of their own, so a hard-edged image sat inside a
  rounded card. They follow `--r-md`, which already collapses under
  *Square corners*.
* The Theme button is gone from the rail: it duplicated Settings ›
  Appearance. `T` still cycles, and it is on the shortcuts page.
* `ReaderM.spec` pointed at a moved document and did not name the new lazily
  imported modules. A real PyInstaller build was run to confirm: the frozen
  binary starts, reports 1.0.1 and loads all 19 sources.

### Changed — documentation

Every `.md` except `README.md` now lives in `MD/`, joined by **AGENT.md**
(the local API, for other programs) and **QUICKRUN.md** (running from source
without packaging).

---

## v1.0.0 — Shelves, HeroUI, and covers that finally load

### Fixed — MangaDex covers, diagnosed properly at the third attempt

Twice reported and twice mis-diagnosed, because the URLs return HTTP 200 and
decode fine, so the wrong thing kept being checked. Fetched with
`Referer: http://127.0.0.1`, MangaDex serves a *different image* — a
placeholder reading "You can read this at mangadex.org". At the same URL:
59,480 bytes with that referer against 77,292 without. The screenshots showed
every card rendering the placeholder graphic.

Those hosts are fetched through Python and cached. The same watch of the
browser's network errors turned up three more: `manhuatop.org`
(`ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`), `pstatic.net` (`ERR_BLOCKED_BY_ORB`)
and `webtoons.com`.

### Fixed — "failed to fetch" on a CBZ that is right there

`fetchAsFile` was a bare `fetch()` with no status check and no retry, so any
transient hiccup — or a 503 arriving as a Blob of error text — killed the
open. Three attempts with backoff, and both `res.ok` and `blob.size` checked.
Verified: the old code failed 3/3 injected transients, the new one recovers
from 3/3.

### Added — library shelves

Folders for books, with tags, pinning and optional passcode locks, shown as a
tree beside the grid. Folders start collapsed, as asked.

The lock was decorative when first written, and the screenshots showed it:
the tree hid the titles while the grid listed them one panel to the right.
Three separate paths reach a title and each needed closing — the grid
(`reader_library`), the continue-reading row (`reader_recent`, keyed by file
path and unaware of shelves) and `reader_open`, which accepted any path at
all. Locks reuse `passlock`'s PBKDF2 verifier; the passcode is never stored
and the salt never reaches the interface.

Said plainly, because it matters: this is a privacy screen, not encryption.
The files stay readable on disk.

### Added — real HeroUI

The sliders, selects, tabs, switches and chips are
[HeroUI](https://heroui.com/) components, bundled statically into one file so
the packaged app builds with PyInstaller alone.

Two bugs the token mapping introduced, both fixed before release:
`--accent: var(--accent)` is a *self-reference*, and a CSS cycle resolves to
guaranteed-invalid with the fallback skipped — measured, `--accent` came back
empty on every `[data-theme]` element and blanked the middle swatch of every
theme tile. And HeroUI swaps palette on `.dark`, which ReaderM's themes never
set, so `--overlay` painted pure white behind 13 background rules.

### Added and fixed — the reader

* Two tabs in the page sidebar: all pages, and bookmarked pages.
* Position autosaves every 30 seconds and on exit, with no popup.
* The toolbar is 43px instead of 58px.
* A centre tap no longer resizes the sidebar while the bars are hidden.
* Continue-reading thumbnails have covers — nothing ever supplied one.

---

## v3.2.4 — Library covers, a page list, and two navigation bugs

### Fixed — a library cover opened the download page

Clicking the cover of something already on disk routed to the series page,
which is the download manager. It opens the **reader** now. The series page is
still one click away: an info button appears on the corner of the card.

That needed a routing fix too — the info button sits *inside* a card carrying
`data-open`, so `closest()` walked up and opened the reader anyway. The more
specific target wins now.

### Fixed — library covers never loaded

Not a MangaDex problem. Checked first: their URLs return **200** server-side
and load fine inside the page. What did not load was the *library* cover,
which is an absolute path on disk — `/home/you/Downloads/Series/cover.jpg` —
and no browser can fetch that from an http page. Local covers are served
through the asset server now; remote URLs are passed through untouched.

### Fixed — zoom moved you off the page

`scrollTop` is an absolute offset, so the same number lands somewhere else
once the pages reflow. Measured on page 6 of 12 at 200%: `scrollHeight` fell
71216 → 57216 while `scrollTop` stayed at 35000, taking the position from
0.497 through the chapter to 0.620. Zoom, width and gap now capture the page
you are on and restore it afterwards.

### Fixed — jumping to a page landed short

Scrolling towards a distant page pulls the ones in between into the lazy-load
margin, and each swaps an 80vh placeholder for its real height — pushing the
destination further down as you travel. Measured jumping to page 8 of 12:
`offsetTop` read **8028** at click time and **27300** once the scroll settled,
landing 774px short. The offset is re-read until it stops moving.

### Added — the reader chrome from the screenshot

* **Pages sidebar** (`P`) listing every page by name, with a *Current
  position* marker, a filter box, and the book's cover and page count in the
  header.
* **Per-page bookmarks**, shown on hover in the list and kept visible once
  set. The toolbar bookmark toggles the current page and stays in step.
* **The book icon** in the top-left is the `cover.ext` from the chapter's
  folder, falling back to the series folder above it.
* **Minimalist mode** (`M`): nothing but the page, with the toolbars returning
  when the pointer nears the top or bottom edge. The hover strips are inert
  unless minimalist mode is on, so they never steal an ordinary click.

### Tests

35 new. **23 of 23 mutations caught.** Five tests initially failed for their
own reasons and were corrected rather than the code bent to fit: a wrong class
name, a slice landing on a call site instead of a definition, an assertion
matching its own explanatory comment, a click on a row the list had already
re-rendered, and a wait for "no pages pending" that can never finish because
distant pages stay unloaded by design. One more passed for the wrong reason —
the `goTo` retry compensated for a deliberately removed anchor, so that test
now scrolls by hand. Suite: **1302 passing**.

---

## v3.2.3 — Scrolling, search, and the pages that were missing

### Fixed — the reader would not scroll

`#tapzones` is a full-bleed `inset: 0` overlay for the left/right tap targets,
and it sat **above** the page strip, so it swallowed every wheel event.
Measured on a real 8-page chapter: a 15,728px strip in a 720px window, and
`scrollTop` still `0` after a 900px wheel.

Making the overlay `pointer-events: none` was not enough on its own — the
`.tap` children re-enabled pointer input and put a hit target straight back
over the strip. The zones are inert now, and the click is caught on the reader
with the third worked out from the pointer position, which is what the overlay
was really encoding anyway. `touch-action: pan-y` keeps touch drags scrolling
rather than starting a tap gesture.

| | Before | After |
|---|---|---|
| `scrollTop` after a wheel | `0` | **`900`** |

### Fixed — slider fills froze

`r-width`, `r-gap`, `r-zoom` and `r-auto-speed` went through raw
`addEventListener` instead of `bindSlider`, so they never repainted their
track. Dragging zoom to 250% left the fill at **20%**; it follows the dot now
and each has a live value chip.

### Fixed — search failed with `'str' object has no attribute 'get'`

`Api.search(query, filters: dict)`, but the front-end passed the source id as
a bare string. Every search with a source selected died. The API accepts both
shapes now, and the interface sends a proper object carrying sort, order,
status, type, genres and the genre match mode.

### Fixed — search was slow

19 sources through a thread pool of **4** is five sequential waves, and one
slow site holds up everything behind it. Measured over the full registry,
identical 182 results each time:

| workers | time |
|---|---|
| 4 | 4.23s |
| 8 | 2.53s |
| **12** | **2.32s** |
| 16 | 2.58s |

Past twelve there is nothing left to win. `browse_all` — the empty-query and
genre path — was left at 4 as well and now shares the setting. End to end,
`Api.search` across all sources went **4.0s → 2.28s**.

### Fixed — `hidden` did not hide

`.field { display: flex }` overrides the user-agent's `[hidden] { display: none }`,
so "Chapters per file" stayed on screen while "Single file" was selected.

### Added — a series page

Clicking a result (or a library card) now opens a detail page: cover, title,
source, authors and artists, tags, description with show-more, and facts —
year, type, demographic, language, rating, last chapter.

Beside it, download options — format, bundling, save-to — and a chapter picker
with All / None / New only / Latest / Invert, quick-select ranges
(`1-20, 25, 30-40`), min/max, name filter, sort order, hide-downloaded, and a
**Read** button that jumps into the reader when the series is already on disk.
Downloaded chapters are marked; bookmark and watch are in the header.

### Added — a Bookmarks tab

Everything saved, with folders, a folder filter, a name filter, and
create/delete. Backed by the `bookmark_*` endpoints that already existed.

### Added — genres, sorts and filters in search

A **Refine** panel: sort (trending, latest, popular, newest, rating, title),
order, status, series type, genre match (all/any), and per-source genre chips.
An empty query with a genre chosen now browses instead of refusing.

### Tests

62 new. **23 of 23 mutations caught** — one initially passed for the wrong
reason: the "any junk filters" test only excluded the *str* message, so a list
slipped through with `'list' object has no attribute 'get'`. Six existing
reader tests were updated: a library card opens the detail page now, and the
Read button is what enters the reader. Suite: **1267 passing**.

---

## v3.2.2 — The API fallback answered 501

`app.js` waits up to three seconds for `window.pywebview` to appear and then
falls back to `POST ./_api/<method>` over HTTP. Nothing ever served that route,
so the fallback got a bare **`501 Unsupported method`** from
`BaseHTTPRequestHandler` and *every* call in the interface failed — no
settings, no library, no sources, no filters. An app that opens and then does
nothing.

That path is taken whenever the pywebview bridge is late or missing, which is
precisely what the fallback exists for.

Two faults, again. The route did not exist, and nothing had attached the `Api`
object to the asset server, so even once the route was added there was nothing
behind it. `_assets` is a class attribute shared by every `Api` instance, so a
server created before `reader_info()` runs now adopts the API rather than
keeping `api = None` for the rest of the session.

Measured, booting the real UI with no bridge injected at all:

| | Before | After |
|---|---|---|
| `POST /_api/get_settings` | `501` | **`200`** |
| Settings loaded | 0 | **59** |
| Filters loaded | 0 | **8** |
| Sources in the dropdown | 0 | **20** |
| Console errors | — | **none** |

The bridge is deliberately strict: it still requires the token, refuses private
names and non-callable attributes, turns wrong arity into a `400` with the real
message rather than a `500`, answers malformed JSON with a `400`, and reports an
unserialisable return value instead of dropping the connection.

### Also checked

Nine startup states were driven end to end while chasing this — fresh machine,
upgrading from MangaDL, corrupt `config.json`, corrupt `library.json`,
zero-byte files, a config where every value is the wrong type, a read-only data
folder, an unreadable legacy file, and a stale singleton record — plus a second
launch while the first still runs, a third after both exited, and the tray
path. All start cleanly; none of them was the fault.

### Tests

26 new. **14 of 14 mutations caught** — two initially passed for the wrong
reason: the "serve any POST path" mutation still produced a `404` from the
*method* lookup, so the test now checks the body rather than the status, and
the late-attach branch needed a case that creates the server before the API
exists. Suite: **1205 passing**. Frozen exe rebuilt and re-verified.

---

## v3.2.1 — The stylesheet never loaded, and the filters had no controls

### Fixed — the interface rendered unstyled

The window opens `http://127.0.0.1:<port>/?t=<token>`. That page then loads
`./style.css` and `./app.js` by *relative* URL, and a browser does not copy a
query string onto a sub-resource — so every one of them arrived with no token
and came back **403**.

Measured on the real asset server before the fix:

| | Before | After |
|---|---|---|
| Failed requests | 4 × `403` | **0** |
| `body` background | `rgba(0, 0, 0, 0)` | `rgb(20, 20, 27)` |
| `body` font | `"Times New Roman"` | Inter |
| Rail width | 1084px (no layout) | 80px |
| `window.__readerReady` | `false` | `true` |

Two faults, not one. Even *with* a token the assets 404'd: `index.html` is
served from `/`, but its files live under `/app/`, so `./style.css` resolved to
`/style.css`, which no route handled.

Fixing the routing alone was not enough either. A `Referer` fallback got the
page's own links working, then `theme.css` and `themes.js` still failed —
because CSS `@import` and JS module imports send the *stylesheet or module* as
the Referer, not the page. Rather than chase that chain, the first request that
presents the token now sets an `HttpOnly; SameSite=Strict` session cookie, and
every later asset rides on it. The 403 path deliberately does not set it, so a
refused request cannot hand out the key it was just denied.

### Fixed — search filters had no interface

`features.DEFAULT_FILTERS` — minimum and maximum chapters, strict chapter
range, blocked titles, tags and authors, hide-no-cover, safe mode — has been
applied to every search and browse call on the Python side for a long time.
Nothing in the interface could set any of it, so min/max chapters simply did
nothing.

The Search view now has a collapsible **Filters** panel with all eight,
a live summary in the header (`≥ 10 ch · ≤ 200 ch · 4 blocked · safe mode`),
and a Clear button. Block lists split on commas *or* newlines, and an empty
number box means "no limit" rather than `NaN`.

Strict chapter range is off by default and says why: many sources never report
a chapter count — MangaDex leaves it empty for every ongoing series — so an
unknown count is kept unless you ask for it to be dropped.

### Tests

29 new. **17 of 17 mutations caught** — three initially passed for the wrong
reason: `_deny()` never sends a cookie so the "leak the token" mutation had to
target the denial path itself, one anchor missed on indentation, and a
traversal mutation only changed *which* refusal code came back rather than
leaking anything. Suite: **1179 passing**. Frozen exe rebuilt and re-verified.

---

## v3.2.0 — ReaderM

The app is called **ReaderM** now. The package is `readerm`, the commands are
`readerm`, `readerm-gui` and `readerm-tui`, the executable is `ReaderM`, and
data lives in `~/.readerm`.

### Your existing library is not lost

The risky part of a rename is the data folder: an install with a year of
downloads keeps its library, settings, bookmarks, reading positions and
password in `~/.mangadl`, and a renamed build that ignored them would look
exactly like data loss.

So on first launch, if `~/.readerm` does not exist and `~/.mangadl` does, the
JSON state is **copied** across — copied, not moved, so the old folder stays as
a backup and downgrading still works. Only real state travels; `instance.json`
is a live singleton handshake and the logs describe a build that is no longer
running, so both are deliberately left behind. A failed copy is reported and
the app still starts: an empty library is recoverable, a crash loop is not.

All eight modules that used to compute `~/.mangadl` for themselves now share
`readerm.paths`, so there is one place to get this right instead of eight.

### Added — a Stats tab

A GitHub-style contribution calendar over the last year (or 3/6 months),
current and longest streak, active days, and totals for chapters, pages, bytes,
jobs and time spent. Three more tabs behind it: **Sources** ranked by volume,
**Library** with the biggest series, and **Reading** split into in-progress and
finished. The data was already there — `features.stat_calendar` and
`get_stats` have existed since v1.4.24 — it just had nowhere to show.

### Added — the settings that were still missing

Thirteen preferences that the backend stored but no control exposed: pages to
preload, animate page turns, open fullscreen, external reader path, default
source, preferred language, preferred scanlator, interleave when browsing, data
saver, chapters per file, confirm before deleting, automatic snapshots, and the
OPDS cover folder. A test now fails the build if a key in `DEFAULT_SETTINGS`
has no control.

### Changed — the interface

* **Type.** Inter with a proper 1.2 scale, per-size tracking (Inter needs
  negative tracking as it grows), tabular numerals wherever figures line up in
  columns, and disambiguated `1`/`l` via `cv05`.
* **Sliders** are drawn by hand. `accent-color` alone gives the platform
  control: a thin grey groove with a dot, cramped on Windows, and it ignores
  the theme. They now have a filled accent track, a ringed thumb that grows on
  hover, and a live value chip with its unit.
* **Checkboxes** are themed too, for the same reason.
* **Tabs** with an underline that tracks the active one, and optional counts.
* **Spacing** comes from a 4px scale rather than ad-hoc pixels, so panels,
  cards and forms share a rhythm.

### Fixed

* **Calendar month labels drifted.** Cells are 12px with a 3px gap — a 15px
  column pitch — but the label strip used 12px. Three pixels a week compounds:
  across a year the months sat above the wrong columns entirely.
* **Legend swatches were invisible.** The level colours were scoped to `.cal`,
  so every `.cal-legend i` measured `rgba(0, 0, 0, 0)`.

### Tests

56 new tests. **22 of 22 mutations caught** — four initially passed for the
wrong reason: two migration guards are redundant by design (so the mutation had
to defeat both), a slider test survived because `Math.max(2, …)` floors bars at
a visible width, and one run passed on **stale bytecode** left by the mutation
harness, which now purges `__pycache__` between runs. Suite: **1151 passing**.

---

## v3.1.0 — The appearance settings do something again

A quiet bug, and the reason for this release: `theme`, `accent`, `corners`,
`matrix`, `animations` and `columns` were still in Python's `DEFAULT_SETTINGS`
and still being written to `config.json` after v3.0.0 replaced the front-end.
Nothing read them. **Six settings that saved, loaded, and did nothing.**

### Added — the design system, back from the pre-v3 shell

* **Eight themes** — Midnight, Mocha, Forest, Plum, Ocean, OLED, Light, Paper.
  Every palette defines the same token set, checked by a test, because a token
  used in CSS but missing from one theme is an invisible control: the old GUI
  shipped a 0.03-contrast queue exactly that way.
* **Six accents** — blue, violet, teal, rose, amber, mint, with a *separate*
  table for light themes. Pastels that read fine on `#16161e` fail contrast on
  white, so `#7aa2f7` becomes `#2962ff` there.
* **Square-corner mode.** One switch flattens every radius, in the shell and in
  the reader.
* **Dot matrix background.** The animated canvas field from the old shell,
  kept with its tuning intact: 30fps rather than 60, a hard cap of 420 dots
  with spacing widening instead of density growing, colour cached on theme
  change (a `getComputedStyle` inside a rAF loop forces a style recalc every
  frame), and paused when the window is hidden or the app is locked.
* **Animations toggle**, honouring `prefers-reduced-motion` unless overridden.
* **Grid density** — auto, or a fixed 3–8 columns.

### Added — settings ported back from the old UI

Drag-to-rank sources (with up/down buttons alongside, because a drag gesture
is not reachable from a keyboard), per-source enable switches and capability
chips, the password lock with hint and blur-covers, output folder and format,
file-name templates, performance sliders, phone-server and OPDS ports and
token, and the background/tray group — all in collapsible sections.

### Changed

* Typography: Inter with a real type scale and tabular numerals; Material
  Symbols instead of hand-drawn SVG paths. Both load **non-blocking** — icons
  stay hidden until the font resolves, because Material Symbols are ligatures
  and the browser otherwise paints the literal word "settings".
* Chrome colours are now entirely token-driven. A test fails the build on any
  hard-coded hex in `style.css`.

### Fixed

* **Settings were being silently dropped.** `pushSettings` debounced by
  restarting a timer but only sending the newest change object, so three
  settings changed inside the 250 ms window saved one and lost two — measured:
  theme + accent + corners went in, only `{corners}` came out. Pending changes
  now accumulate.
* Theme preview tiles showed two swatches instead of three: the middle bar was
  `--surface-2` on a `--surface` tile, invisible in every dark theme.

### Tests

24 new browser tests measuring contrast, colour and layout off the *rendered*
page rather than the source text. **22 of 22 mutations caught** — two tests
initially passed for the wrong reason (one asserted `0px` on an element that
had no radius to begin with; one scanned line-by-line for a `<link>` whose
`rel` and `href` sit on different lines) and were rewritten until reverting
the fix failed them. Suite: **1095 passing**.

---

## v3.0.0 — A real manga reader, built on Foliate

ReaderM no longer hands your downloads to somebody else's app. It reads them.

The reading engine is a fork of [foliate-js](https://github.com/johnfactotum/foliate-js)
(MIT), the same engine [Foliate](https://github.com/johnfactotum/foliate) uses —
and the same one Readest forked when it went cross-platform.

### Why the engine and not the Foliate app

Foliate itself is GTK4 + GJS + WebKitGTK and **does not run on Windows**. That
was checked, not assumed: MSYS2, the only realistic Windows GTK channel, has
**no `gjs` package and no `webkitgtk` package**. Wikipedia puts it plainly —
"Foliate cannot be installed on Windows, MacOS and Android as a native app".
A literal fork of the app would have shipped a Linux-only reader.

`foliate-js`, by contrast, contains no GTK, GJS or Node calls at all
(`grep -lE "require\(|gi://|imports\.|process\."` over every file: no
matches), so it runs unchanged in WebView2. Vendored at commit `78914ae`,
licence and attribution kept in `readerm/reader/VENDOR.md`.

### Added — the reader

* **Webtoon mode.** Continuous vertical, zero gaps, for long-strip comics.
  This had to be *built*: foliate-js routes comics to `fixed-layout.js`, whose
  entire attribute surface is `static observedAttributes = ['zoom']`.
  `flow: scrolled` lives only in `paginator.js`, which handles reflowable
  text, so upstream has no long-strip mode at all.
* **Four reading modes** — webtoon, vertical (with gaps), paged left-to-right,
  and paged right-to-left for Japanese reading order, where the right-hand key
  goes *back* a page and the spread reverses.
* **Double-page spreads**, fit modes (contain / width / height / original),
  zoom, adjustable page width and gap.
* **Nine themes**, six dark and three light. Each carries a *page* filter as
  well as chrome colours, because a dark mode that only darkens the frame
  still fires a white page at you in a dark room.
* **Reads what you actually have.** A packaged `.cbz`/`.epub`/`.pdf`, *or* a
  chapter that is still a folder of `.jpg` files — the case an ordinary
  e-reader cannot open at all. Pages stream individually, so a chapter is
  readable while the rest of it is still downloading.
* **Auto-scroll** for long strips — hands-free webtoon reading, `S` to
  start and stop, `+`/`-` to change speed. Driven by requestAnimationFrame
  with a sub-pixel accumulator: an integer `scrollTop` step per tick rounds
  a slow speed to zero and nothing moves at all.
* Library, source search, download queue, chapter list, bookmarks, notes,
  resume-where-you-stopped, a library stats strip, a keyboard-shortcut
  sheet (`?`) and tap zones, all in the same window.

### Changed

* **The old hand-written front-end is gone.** `readerm/gui/web/` (9,700 lines
  of HTML/JS/CSS) was deleted and replaced by `readerm/reader/app/`. The
  `Api` object behind it survives untouched — the CLI, TUI, phone server and
  OPDS catalog all call into it, so replacing it wholesale would have broken
  every one of them. Reader endpoints are mixed in on top.
* **The window is served over `http://127.0.0.1`, not `file://`.** ES modules
  are blocked over `file://` by CORS — measured, not guessed:
  *"Access to script at 'file:///…' from origin 'null' has been blocked by
  CORS policy"*. The new loopback asset server also streams book files with
  Range support and gates everything behind a per-process token and an
  explicit allow-list of library folders.
* The phone server now serves the same reader, so a phone gets webtoon mode
  and themes too.

### Fixed

* **Collapsed webtoon strip.** Unloaded `<img>` elements have no intrinsic
  height, so every page stacked at offset 0: measured `scrollHeight 640 ==
  clientHeight 640` — the strip would not scroll and reported the *last* page
  the instant a chapter opened. Pending pages now reserve a screenful.
* **Lost reading position.** Resuming straight after open raced the first
  images; with no scrollable span yet the seek landed at 0 and the saved spot
  was silently thrown away. `setFraction` now retries across frames.
* **Unclickable toolbar.** The options drawer sat at `top: 0`, over the very
  buttons that open and close it (Playwright: *"<h3>Reading</h3> intercepts
  pointer events"*, for thirty seconds).
* **Colliding annotation ids.** A millisecond timestamp gave a bookmark and a
  note the same id when both were added in one tick, so deleting one removed
  the other.
* **Engine 404 in the packaged exe.** Caught by testing a real PyInstaller
  build rather than the source tree: `foliate/` sits beside the app directory,
  and the generic asset route confined everything to it, so every engine file
  404'd while every `app/` file returned 200 — a reader that loads and then
  never boots.

### Housekeeping

* 111 new tests (`test_v300.py`, `test_v300_reader.py`), including a real
  Chromium driving the renderer. **30 of 30 deliberate mutations were caught.**
* 222 tests that covered the deleted front-end were removed, chosen from the
  measured failure list so no backend test was thrown away with them.
* ~24 MB of scraped HTML fixtures and one-off debug harnesses deleted;
  the vendored PDF engine ships without its 7.7 MB of source maps.

---

## v2.0.0 — Your library, in any e-reader

The version jump is for the new surface: ReaderM now *publishes* what it
downloads, not just fetches it.

### Added — an OPDS catalog

```
python opdsserve.py              # http://<this-pc>:8578/opds
python opdsserve.py --gui        # with a control window
```

Point **Readest** — or Panels, KyBook, Chunky, Aldiko, Thorium — at the
printed URL and your downloads appear as a browsable catalog with covers,
served from the machine that downloaded them.

Built against [the OPDS 1.2 spec](https://specs.opds.io/opds-1.2.html)
rather than by copying another implementation, because readers fail quietly:
a mislabelled link type usually shows an *empty shelf*, not an error. The
things that had to be exactly right:

* navigation and acquisition feeds carry different `kind=` parameters;
* every publication has at least one acquisition link **with a media type**
  — CBZ, EPUB and PDF each get their own, which is what decides whether a
  reader shows the book at all;
* `atom:updated` is RFC 3339, or entries get dropped;
* facets appear only in acquisition feeds, with at most one active;
* hrefs are absolute, because several readers resolve relative ones against
  the wrong base after a redirect.

Shelves: **All titles**, **Recently added**, **By source**, **A–Z**, and
OpenSearch so the reader gets a working search box. Entry ids are derived
from the series URL and are stable across restarts, so a reader can tell an
existing book from a new one instead of re-downloading the shelf every sync.
Files moved or deleted since download are omitted rather than offered as a
404.

**Authentication is HTTP Basic**, because that is what the spec names and
what readers implement — a bearer token, as the phone server uses, is not
something you can tell an OPDS client about. The password is the same access
token; the username is ignored, since readers insist on the field and there
is no second secret worth inventing.

It runs on **port 8578**, separate from the phone server's 8577, so both can
be up at once. Turn on **Settings → Phone server → Start the catalog with
the app** and it comes up with the GUI, sharing the process so it always
sees the library the app is writing.

### Added — covers for folders of images

A folder of loose page images has no cover file, so every shelf that reads
folders shows a blank tile. One button now fixes that everywhere:

* the **first page** is used, sorted naturally — page 2 before page 10,
  which plain string sorting gets wrong;
* the cover is **copied, never moved or re-encoded**;
* the extension **follows the source**, so a PNG page yields `cover.png`
  rather than a PNG named `.jpg` that strict readers reject;
* `raw/` and other working folders are skipped;
* existing covers are left alone unless you ask to overwrite;
* **Preview** shows what would change before anything is written.

Changing a single folder's cover removes any cover under a different
extension, so two files cannot disagree about which one wins.

### Added — a sixth interface

`landing.py` gains an **OPDS catalog** tile, `ReaderM.exe opds` routes to it,
and the spec bundles the new modules.

### Fixed

* `readerm/opds.py` used relative imports without the direct-run guard the
  repo requires — caught by the existing convention test.
* A leftover `from . import opdsserve` inside the GUI helper pointed at the
  wrong package and made *Start now* fail with an ImportError. Caught by
  running it rather than by reading it.
* The FEATURES.md table-of-contents test stripped hyphens when slugifying
  headings, so a correct link to `#reading-it-in-an-e-reader` looked broken.
  GitHub keeps hyphens; the rule now matches, and still catches a genuinely
  wrong anchor.

### Tests

55 new tests, 1148 passing. Each behaviour was reverted to confirm its test
fails: **24 of 24 caught** — including mislabelled feed types, untyped
acquisition links, wrong media types, random ids, non-RFC3339 dates,
unauthenticated downloads, string-sorted pages, and covers written with the
wrong extension.

One test of mine asserted the wrong thing: I expected a CJK title to fall
into the `#` bucket, but `str.isalpha()` is Unicode-aware, so 岸 gets its own
shelf. The code was right — shelving a Japanese title under `#` would be
worse — so the test was corrected and now also checks that digits and
punctuation *do* bucket together.

---

## v1.4.30 — The exe opens the launcher, and actually contains everything

Verified by building rather than by reading the spec — which is how both of
the following turned up.

### Fixed — the packaged exe shipped without the server or the launcher

`server.py` and `landing.py` were top-level scripts, so
`collect_submodules("readerm")` never saw them:

```
collect_submodules('readerm') -> 47 modules
  serverui included: True
  servercfg included: True
  landing  included: False      <-- not in the bundle
  server   included: False      <-- not in the bundle
```

Worse, `readerm/serverui.py` and the GUI both did `import server`, which
only resolves with the repo root on `sys.path` — true from a checkout, false
inside a bundle. So the phone server was doubly broken in the exe.

Both are now `readerm/server.py` and `readerm/landing.py`, with thin
wrappers left at the repo root so `python server.py` keeps working. Two path
bugs came with the move and are fixed: the server's `WEB_DIR` pointed one
directory too high, and now resolves through `sys._MEIPASS` when frozen;
the launcher's `HERE` pointed inside the package instead of at the project
root.

### Changed — double-clicking opens the launcher

The exe is five programs in one, and a double-click committed you to the
desktop app with no way to reach the TUI, the menu or the phone server
without opening a terminal and knowing the subcommand. It now opens the
launcher window. `ReaderM.exe gui` still goes straight to the app, so an
existing shortcut is unaffected, and `menu`, `tui` and `server` are
subcommands too.

A frozen build has no `.py` files, so every launcher tile would have failed
with *can't open file 'gui.py'*. Each target now has a frozen equivalent
that re-invokes the executable with a subcommand, and a test asserts every
one of those is actually routed by `launcher.py`.

### Fixed — a failed launch was a wall of tracebacks

With no display, pywebview prints a full `ImportError` traceback for each
backend it tries. The launcher now silences that and ends with something
usable — and exits **1**, not 0:

```
  The launcher window could not open.
  You must have either QT or GTK with Python extensions installed...
  Start an interface directly instead:
    ReaderM gui
    ReaderM menu
    ...
```

The advice differs when frozen, because telling someone to run
`python gui.py` next to an exe is useless.

### Fixed — `covers.scan("")` walked the current directory

`os.path.abspath("")` is the working directory, so an empty root scanned
wherever the process happened to be. Found because a local build left
`build/` behind and a test that expected `[]` picked it up. In a packaged
build that would have been the user's home folder.

### Build results

Both modes built and run:

| | size | verified |
|---|---|---|
| one-folder | 138 MB | `--help`, `server --help`, serves the phone UI, live API |
| one-file | 57 MB | same, with assets unpacking from `_MEIPASS` |

UPX is now **off**. It routinely trips antivirus heuristics on a freshly
built unsigned exe, and the saving is not worth a download that gets
quarantined.

### Tests

27 new tests, 1093 passing. Each change was reverted to confirm its test
fails: **15 of 15 caught**. One initially passed for the wrong reason — it
grepped the source for `return 1`, which matched an unrelated early exit, so
it now runs `landing.py` as a real process and checks the exit code.

---

## v1.4.29 — Your own server token, a server window, and one launcher

### Changed — the access token is yours, and it persists

It was `secrets.token_urlsafe(12)`, regenerated on **every launch**. That
meant re-pairing the phone each restart, and any bookmarked link quietly
breaking. It is now a saved setting:

* set it in the app under **Settings → Phone server**, in the server's own
  window, or on the command line — all three go through the same validator
  in `readerm/servercfg.py`, because three copies of a length check is how
  one of them ends up accepting four characters;
* **minimum 16 characters**, enforced with live feedback as you type;
* only URL-safe characters, so the printed link never needs escaping;
* generated tokens skip `l`, `I`, `1`, `0` and `O` — this string gets copied
  off a screen by hand;
* a rejected value never overwrites the working one, and a hand-corrupted
  entry in `config.json` is replaced rather than locking you out.

Port and verbose logging are settings too.

### Added — `python server.py --gui`

A small pywebview window instead of a bare terminal:

* the phone link, with **Copy** (and a select-the-text fallback, because the
  clipboard API refuses outside a secure context) and **Open here**;
* token and port with validation as you type, plus **Generate**;
* a verbose toggle;
* a live colour-coded log. Rejected tokens and errors always show; verbose
  adds every call the phone makes, with timings. It autoscrolls only when
  you are already at the bottom, so reading back is not yanked away.

`stop` is honest about its limitation: Werkzeug has no clean cross-thread
shutdown once inside `serve_forever`, so the window says "close this window
to stop the server" rather than pretending to have stopped it.

### Added — `python landing.py`

One window listing all five interfaces — desktop app, terminal menu, TUI,
CLI, phone server — that starts whichever you pick. Terminal ones open in a
real terminal window (a TUI written to a pipe is useless), trying
`x-terminal-emulator`, `gnome-terminal`, `konsole`, `xfce4-terminal`,
`alacritty`, `kitty` and `xterm` on Linux, `osascript` on macOS and
`cmd /k` on Windows.

**It solves the venv problem.** Launching `tui.py` from a file manager does
not inherit your virtual environment, so the child gets the system Python,
has none of the dependencies, and dies with `ImportError` — a failure that
looks like a bug in the app. The launcher searches the interpreter it is
already running under, `$VIRTUAL_ENV`, then `.venv`/`venv`/`env` in the
project folder and **up to two directories above it**, since a checkout is
often one folder inside a workspace that owns the venv. Verified at all
three depths.

Whichever Python it picked is shown in the window, with a warning when none
was found — "which Python is this using" is the first question when
something will not start. A log panel sits collapsed at the bottom, opens
automatically on the first launch, and records the exact command run.

### Fixed

The Phone server settings card was nested **inside** the Background card —
my edit ate a closing `</div>` and the panel rendered as a box within a box.
Caught by screenshotting rather than trusting the markup. Two tests now
assert that no settings card is nested inside another.

### Tests

45 new tests, 1068 passing. Each change was reverted to confirm its test
fails: **17 of 17 caught**, including dropping the length minimum, allowing
URL-unsafe characters, going back to a per-launch random token, letting a
rejected token overwrite a good one, ignoring the verbose flag, and only
searching the project folder for a venv.

---

## v1.4.28 — Madara downloads fixed, and a phone server

### Fixed — downloading from a Madara site failed

```
ScrapeError: Unknown source 'madara.manhuatop'
```

Aggregate members (`madara.toonily`, `madara.manhuatop`, …) are real sources
that are **not in the registry** — only their parent, `madaranet`, is.
v1.4.20 taught `Api._source()` to resolve them, which fixed cover proxying
and browsing. But `DownloadEngine` builds its source through
`sources.get_source()`, which never learned. So the series page loaded fine
and the download button died — which is exactly how you hit it.

The same hole existed in the CLI, the TUI and the cover tools, all of which
call `get_source()` directly.

Resolution now lives in the registry, so every caller gets it. The GUI's
private copy is deleted rather than left to drift again.

One thing worth recording: the first attempt used
`hasattr(parent_cls, "MEMBERS")` to spot an aggregate. `MEMBERS` is a
**module** constant in `madaranet.py`, not a class attribute, so that is
always `False` and the fix silently did nothing. It now tests for the
capability — a callable `member()` — and a test asserts the distinction so
it cannot regress quietly.

| | before | after |
|---|---|---|
| `get_source("madara.manhuatop")` | ScrapeError | Manhua Top |
| all 10 Madara members | ScrapeError | resolve |
| `DownloadEngine(source="madara.*")` | ScrapeError | builds |
| unknown ids (`madara.nope`) | ScrapeError | ScrapeError |

### Added — `server.py`, ReaderM from your phone

```
python server.py                  # http://<this-pc>:8577
python server.py --port 9000
python server.py --host 127.0.0.1 # this machine only
python server.py --no-auth        # skip the access token
```

**Everything runs on the host computer.** The phone sends the request; this
machine executes it, with the same `Api` object the desktop app uses. So the
phone never contacts a manga site, files land on the host's disk, the
library stays in the host's `~/.readerm/`, and closing the browser — or
walking out of Wi-Fi range — does not interrupt a download. That is the
whole point of routing through the host rather than peer-to-peer.

It serves the **existing UI**, not a cut-down mobile one.
`readerm/gui/web` already talks to Python through one narrow bridge
(`window.pywebview.api.<method>()` returning a promise), so `/bridge.js`
reimplements exactly that shape over `fetch`. One UI to maintain, and the
two cannot drift apart. The shim uses a `Proxy`, so all 113 endpoints work
and a new one needs no wiring.

Engine events are the one thing that could not be reused: the desktop pushes
them in with `evaluate_js`, which has no equivalent to a browser on another
device. They are buffered and long-polled instead — an idle app costs one
open connection rather than a request per second, and a phone that sleeps
and reconnects resumes from its cursor.

Two things genuinely cannot work remotely, and say so rather than failing
silently: the **file and folder pickers** (a native dialog would open on the
host's screen, where nobody is looking) and **Open folder / Open in reader**,
which are allowed but act on the host.

The layout adapts below 820px — the side rail becomes a bottom bar, the
cover grid reflows to two columns, and settings rows stack. Measured on a
390px viewport: zero horizontal overflow, where before the search button
overflowed the page.

An access token is generated at startup and printed with the URL. It is a
shared secret over plain HTTP for a home network — **do not port-forward
it.**

Requires the `server` extra (`pip install -e ".[server]"`); `requirements.txt`
covers it too.

### Tests

35 new tests, 1023 passing. Each fix was reverted to confirm its test fails:
**14 of 15 caught**. The fifteenth is the static-file traversal guard — I
removed it and re-ran the attacks, and Werkzeug's own URL normalisation
refuses them anyway, so the guard is genuine defence-in-depth rather than
the thing doing the work. The comment and the test now say so instead of
claiming credit.

One test of mine asserted the wrong contract: a wrong-arity API call returns
`{"ok": false}` with a 200, because `_safe_endpoint` wraps every endpoint
before the server sees it. That is the better shape — the UI already
understands it — so the test was corrected rather than the code.

---

## v1.4.27 — One app at a time, and the Windows crash

Both fixes come from a crash log covering 116 sessions.

### Fixed — every launch started another copy

Nothing stopped a second ReaderM starting while the first sat hidden in the
tray. And running it again is the *obvious* way to reopen a hidden window,
so the bug was easy to hit repeatedly. Reproduced with three launches
against one profile:

| | before | after |
|---|---|---|
| processes alive | **3** | 1 |
| tray icons | 3 | 1 |
| download engines on one `library.json` | 3 | 1 |

New `readerm/singleton.py`. A loopback TCP server whose port is recorded in
`~/.readerm/instance.json`:

* **The socket is the lock.** Binding is atomic and the OS releases it when
  the process dies, so a killed instance never leaves a stale lock that
  needs cleaning up — the classic failure of PID-file locking. A stale port
  file simply fails to connect and startup continues.
* **It doubles as the wake-up channel.** The second launch sends `show` and
  exits; the running instance raises its window, which is what the user
  wanted. Refusing silently would have been worse than the duplicate.
* A random token in the file must match before any command is honoured, and
  only `127.0.0.1` is bound.

### Fixed — the access violation on startup

```
Windows fatal exception: access violation
  Thread : pystray/_win32.py _mainloop      <- tray loop already running
  Current: clr_loader/types.py __call__     <- .NET CLR loading
           webview/platforms/winforms.py <module>
```

The tray icon runs a Win32 message loop of its own, and it was started
*before* `webview.start()` — which is where pywebview loads the .NET CLR.
Two message loops racing during CLR startup is a hard crash, not something
`try/except` can catch.

The tray now installs **after** the toolkit is up, on the window's `shown`
event. Three things could otherwise go wrong, and all three are covered:

* a backend that never fires `shown` → a 4-second fallback timer;
* the window closed before either fires → installed synchronously on close,
  so "minimise to tray" is never lost to a race with the user's click;
* all three firing at once → the install is idempotent, verified by counting
  icons rather than reading the source.

The second crash in the log is the same shape, one layer down: after a
backend import failed, `run_gui` retried the next backend and walked back
into the CLR load that had just died. On Windows it now stops after the
first failure.

The single-instance check also runs **before** `import webview`, so a
duplicate never reaches the CLR at all.

### Changed — crash.log no longer buries the evidence

The supplied log was 116 session markers around exactly 2 real tracebacks.
It is now trimmed to 512 KB on startup, cut at a session boundary so it
never opens mid-traceback, and the marker says plainly that no crash below
it means a clean run.

A lazily-written header would have been nicer, and I tried it —
`faulthandler.enable()` calls `fileno()` immediately and writes to that
descriptor from the signal handler, so the header cannot be deferred.
Measured, not assumed.

### Changed — new screenshots

The committed shots were from v1.4.14, twelve releases ago. They predated
the grouped queue, the contribution calendar, the source carousel, the tools
tab and the downloaded-result overlays, so both the README and the landing
page were advertising a UI that no longer exists.

All eight are regenerated at 2× against the current build, with seven stale
files deleted. Covers are generated gradients rather than hotlinked artwork.
Two new tests keep them honest: every referenced image must exist, and no
screenshot may sit in `docs/` unreferenced — an unused shot is one nobody
remembers to update.

### Tests

21 new tests, 988 passing. Each fix was reverted to confirm its test fails:
**12 of 12 deliberate regressions caught**. One test initially passed for
the wrong reason — it asserted the tray install had moved by searching for
a source string that legitimately still exists inside the deferred helper,
so it now checks indentation and the event wiring instead.

---

## v1.4.26 — Tray reopen fixed, downloaded results, readable FEATURES.md

### Fixed — opening from the tray flashed the window and lost it

Reported: the GUI "opens for a quick second then disappears".

This was my own regression from v1.4.24. `_hold_for_tray()` ended its wait
as soon as nothing was downloading, on the reasoning that a tray which
failed to draw an icon must not strand an invisible process. That conflated
two different things — **"no downloads running" is not "nobody wants this
app"**.

Measured in a real subprocess: closing to the tray with an idle queue tore
the process down **0.74s later**. Clicking *Open ReaderM* raced a shutdown
that was already in flight, so the window appeared and then vanished under
it.

| | before | after |
|---|---|---|
| idle queue, hidden in tray | exits in 0.74s | stays up |
| reopened from the tray | window vanishes | window stays |
| Quit from the tray | exits | exits (1.2s) |
| no tray installed | exits | exits (0.3s) |

The original worry is handled where it belongs: `_install_tray()` only
returns a controller once the icon is actually running, so if the hold is
active there is a way to reach the app. If the icon later dies,
`wait_for_quit()` notices and returns on its own.

### Added — what to do with results you already have

**Settings → Sources & ranking → Already downloaded**, with three modes:

| Mode | Behaviour |
|---|---|
| Show normally | no change |
| **Darken** (default) | dimmed cover; hovering fills it up to the fraction you have and shows the percentage |
| Hide | removed from the grid, with a note saying how many were hidden |

The fill animates from the bottom, so "how much of this do I have" reads as
a level rather than a number to parse. Measured: a series with 100 of 200
chapters fills to **50.0%** of the cover.

**The percentage is only ever shown when the source reports a total.**
Plenty do not. Rounding "12 downloaded, total unknown" up to a confident
100% would mark an ongoing series as finished, so those cards show the
chapter count instead and draw no fill at all.

Status comes from one batched `downloaded_status` call per page of results —
doing it per card meant one bridge call and one library re-read per result.
Only matches are returned, so a page of 40 unknown results costs a tiny
reply.

### Changed — FEATURES.md is readable now

It was **816 lines of numbered items ordered by release** — a changelog
wearing a feature list's clothes, where "541. `readerm search --urls`" sat
between two unrelated things because they shipped together.

Now **429 lines grouped by what you are trying to achieve**: Sources,
Searching, Downloading, Output files, Reliability, The desktop app, The
queue, Statistics, Library, Cover rebuilder, Background mode, Privacy, CLI,
Configuration, Packaging, Python API. With a table of contents, a source
table, and comparison tables instead of prose lists.

The landing page's *"N documented features"* badge is gone with it. There is
no honest count to quote from a prose document, and inventing one would be
exactly the kind of fabricated statistic the test suite exists to prevent.
The test still fires if that claim ever reappears without a real count
behind it.

### Also

* `requirements.txt` now includes `pystray`, so a plain
  `pip install -r requirements.txt` gets working tray mode. It was only in
  the `[tray]` extra.
* README gained the two features it was missing: downloaded-result handling
  and the contribution calendar.

### Tests

23 new tests, 967 passing. Each fix was reverted to confirm its test fails:
**14 of 14 deliberate regressions caught**, including inventing a
percentage from an unknown total, letting the percentage exceed 100, hiding
results with no explanation, and putting the numbered wall back in
FEATURES.md. One test assumption of mine was wrong and was corrected — the
fill's resting height is 2px, not 0, because of its top border.

---

## v1.4.25 — Notification loop fixed, landing page rebuilt

### Fixed — repeated tray notifications, over and over

Reported as running in the background but "repeated notifications over and
over like a loop", and reproduced before touching anything.

`_on_closing()` notified **unconditionally** on every close event, with no
duplicate suppression and no check for "already hidden". Window managers
deliver that event more than once — minimise/restore, a taskbar *Close
window*, or the backend-retry path in `run_gui()`, which closes the window
once per attempt. Measured:

| close events | before | after |
|---|---|---|
| 10 in 0.50s | **10 balloons** | 1 |
| 20 in 0.41s | **20 balloons** | 0 (already hidden) |
| 3 backend retries | 3 | 1 |
| same text 10× | 10 | 1 |

Three layers, because one was not enough:

* `_on_closing` returns early when the window is already hidden, so a
  repeat event is vetoed silently.
* `TrayController.notify()` de-duplicates by message text within 30s, and
  supports `once=True` for messages that are only news the first time.
* Reopening the window — from the tray menu or the `shown` event — clears
  both, so the next genuine hide notifies again.

**The dedupe is keyed on the message, not on a blanket rate limit.** Five
books finishing in quick succession are five real events and all five
deserve a balloon. A first attempt used a global floor between any two
notifications and silently ate 4 of 5 genuine "download finished" messages;
the job-completion harness caught it, and that distinction is now a test.

### Fixed — the close message claimed downloads that did not exist

Closing to the tray always said *"Still downloading in the background."*,
even with an empty queue. It now checks `get_progress()` and says
*"ReaderM is still running in the tray."* when nothing is running.

### Changed — the landing page, rebuilt

* **Google Material Symbols throughout, no emoji.** The old page used
  emoji glyphs for its feature icons, which render differently on every OS
  and showed as empty boxes in headless Chromium.
* A new layout: sticky nav, an asymmetric hero with a live terminal, a
  six-cell bento grid, a four-way interface comparison, a filterable source
  grid, a tabbed CLI reference, tabbed screenshots and a three-step install.
* A fine grid backdrop with soft colour fields, rather than the plain
  gradient wash that every project page has.
* **Source tiles are links now**, each with its domain, a colour badge, and
  `18+` / `CF` tags where they apply.
* Filter the source list by All / General / 18+ in place.
* Light and dark themes, remembered between visits.
* Fonts load without blocking first paint — the same fix the app itself
  got in v1.4.24.
* Content is never hidden when JavaScript does not run: the scroll-reveal
  animation is gated behind a class only JS adds, with a 4s safety net and
  a print handler.
* Every repository link points at `Compromisee/ReaderM`.

Every number on the page is still checked against the repository by the
test suite — sources against the registry, features against `FEATURES.md`,
and the passing-test count against what pytest actually collects.

### Tests

29 new tests, 944 passing. Each fix was reverted to confirm its test fails:
**16 of 16 deliberate regressions caught** (6 notification, 10 landing
page). Four tests that initially passed for the wrong reason were
rewritten — one matched a CSS comment as if it were a selector, one could
not tell a bound listener from a mention in a payload, and two keyed on
class names a redesign had already changed.

---

## v1.4.24 — The tray really keeps running, and a contribution calendar

### Fixed — closing to the tray still killed the app

The flag was set, the window hid, and the process died anyway.

The tray icon runs on a **daemon** thread, and so does every download
worker. Python kills daemon threads at interpreter exit, so the moment
`webview.start()` returned there was nothing non-daemon left to hold the
process open. Measured in a real subprocess:

| | before | after |
|---|---|---|
| process lifetime after the window closes, downloads running | **0.06s** | held open |
| Quit chosen from the tray | 0.06s | 1.2s (releases) |
| queue empties while hidden | 0.06s | 0.7s (exits on its own) |
| no tray installed | 0.06s | 0.2s (unchanged) |

`run_gui()` now blocks the main thread in `TrayController.wait_for_quit()`
once the GUI loop returns. It ends on Quit, and also when the queue drains,
so a tray that silently failed to draw an icon cannot strand an invisible
process.

Three related tray bugs went with it:

* **The setting was frozen at startup.** The close handler captured
  `minimize_to_tray` once, so turning it off and closing still hid the
  window. It is re-read on every close.
* **The switches saved nothing.** `minimize_to_tray` and
  `tray_notifications` were in the payload of the settings save handler but
  their checkboxes were never in the list of ids that got a listener, so
  flipping one on its own did nothing. Caught by a browser test that clicks
  the real switch — the string-matching test I wrote first passed with the
  bug reintroduced.
* **The packaged exe had no tray at all.** pystray picks its backend through
  a chain of `try/except` imports that PyInstaller cannot follow;
  `ReaderM.spec` now names them.

### Fixed — the page sat unstyled for up to 20 seconds on startup

`index.html` loaded two render-blocking stylesheets from
`fonts.googleapis.com` **before** its own `style.css`. A desktop app should
never block first paint on a remote host it does not need.

| font CDN | before | after |
|---|---|---|
| reachable | 77ms | 79ms |
| slow (3s) | **timed out past 45s** | 94ms |
| blackholed (10s) | **timed out past 45s** | 52ms |

`style.css` is now first, and the font links are `media="print"` with an
`onload` promotion, which fetches them without blocking. Because icons are
ligatures and render as their literal names (`chevron_right`) until the
font arrives, they are hidden until it loads — with a 1.2s timeout so an
offline app is still usable.

### Fixed — the bouncing search icon was clipped

`.hero-icon` floats 7px upward forever inside `.hero-title`, which is
`overflow: hidden` so the title can collapse when results appear. There was
no headroom, so the top of the icon was sliced off. Sampled across one full
5s bounce:

| | worst headroom | clipped frames |
|---|---|---|
| before | **-6.44px** | 20 of 21 |
| after | +2.76px | 0 of 21 |

### Fixed — the queue ignored the theme

`--panel-2` and `--edge-c` were used by the queue tiles, the cover picker
and the tool paths but **were never defined anywhere**, so all four fell
back to hardcoded literals (`#1b1b26`, `#2a2a38`). On a dark theme nobody
noticed; on the light theme the queue was near-black slabs carrying
near-black text — measured, title `rgb(28,29,31)` on background
`rgb(27,27,38)`, a luminance difference of **0.03**. After: **0.887**.

`.spark` was also declared twice: the stats bar chart claimed it
(`display:flex; height:110px`) and the queue's inline SVG silently inherited
it. The sparkline is now `.q-sparkline`.

### Changed — the queue tab is one panel

* The floating *"N downloads / Stop"* card that repeated the queue's totals
  is merged into the queue card header.
* The **Active chapters** card is gone: it listed exactly the same in-flight
  chapters as the expanded tiles, so every chapter was on screen twice.
* A single download now renders a tile. The card required two rows, so the
  commonest case showed no tile at all.
* Collapsed tiles gained a cover thumbnail, the source, and a live ETA.
* Chapter rows update in place instead of being rebuilt every second, which
  was restarting their entry animation and making the block flicker.

### Added — advanced queue logging

A switch in **Settings → Background**, mirrored on the Queue tab, that logs
every engine event (per-page fetches, retries) instead of just milestones.
Off by default; the line cap rises from 200 to 2000 when it is on.

### Added — contribution calendar and source carousel

**Recent activity** is now a GitHub-style grid: one square per day for 53
weeks, whole weeks starting Sunday, empty days included.

* Brightness scales with that day's chapters, bucketed against the busiest
  day in the window so both light and heavy users get a readable spread.
* Every source has a stable colour hashed from its id by golden-angle hue
  rotation, so adding a site never renumbers anyone else's hue.
* A day's square is the **weighted mix** of the colours of the sources that
  contributed to it.
* Hovering a day names each source as a fraction — *MangaDex 23/55*.
* A carousel below it gives each source a card with its total, its share,
  and a mini activity strip; hovering shows its chapters as a fraction of
  the whole library.

This required recording per-day-per-source statistics, which the app was not
keeping. Days recorded before this release still count toward the totals and
simply have no source breakdown — dropping real history to keep the new
field tidy would misreport what you downloaded.

Charts also label sources by display name now, instead of raw ids like
`flamecomics` and `madara.toonily`.

### Tests

47 new tests. Every one was verified by reverting its fix and confirming it
fails: **16 of 16 deliberate regressions were caught**. Two tests that
initially passed for the wrong reason were rewritten — one matched a comment
describing a removal rather than the removal itself, the other could not
tell a bound listener from a mention in the saved payload.

---

## v1.4.23 — Queue redesign, and a cross-book counter bug

### Fixed — "downloaded chapters" climbing on the wrong book

Reported, and reproduced in a browser before touching anything: with a
download running, opening **any other** manga from search showed its
*"N downloaded"* pill counting 1, 2, 3… in step with the *other* book's
progress.

The cause was one line. `markChapterDownloaded()` wrote into `state.downloaded`
and the pill for whatever page happened to be open, and `chapter_done` carries
no manga of its own — only a job id. Reproduction, before:

```
viewing Book B, pill: 0 downloaded
…3 chapters of Book A finish elsewhere…
pill now says: 3 downloaded          ← wrong book
state.downloaded: [Chapter 1, 2, 3]
```

After: the pill stays empty for Book B and still updates correctly when
Book B itself is the one downloading. Matching is on the job's URL,
case-insensitively and ignoring a trailing slash, since sources spell the
same link differently.

### Changed — the download queue is now grouped and collapsible

One tile per manga rather than one row per job.

**Collapsed** (the default — a long queue should read as a list of books):
* a live **sparkline** of the transfer rate, drawn as an inline SVG
* the current rate
* a **chapter fraction pill** — `0/20`, `10/100` — which pulses on change

**Expanded**:
* larger cover, source chip, status and percentage
* **speed, ETA, downloaded bytes and the chapter fraction**
* a progress bar
* the chapters **downloading right now**, each with its own page progress

Grouping keys on the URL, not the title, so one book never splits into two
tiles. The live refresh patches only the values that changed rather than
re-rendering the list — rebuilding would collapse a tile the moment you
opened it. Rate polling runs once a second while something is downloading and
stops itself when nothing is.

### Added — animations

Tile entry, chevron rotation, expand/collapse (via `grid-template-rows`, so
it animates to auto height), pill pulse, progress-bar easing, toast entry,
card entry, and button press feedback.

All of it is wrapped in `prefers-reduced-motion: reduce` — motion is
decoration here, never the only signal, so the OS setting switches it off.

### Details

* Per-job snapshots now carry `speed_text`, `eta_text`, `downloaded_text` and
  a bounded rate `history` for the sparkline.
* The history is sampled at most every 0.4s. Sampling on every read made the
  sparkline scroll far too fast, and `summary()` was calling `snapshot()`
  four times per job — so it sampled four times per tick.

874 passing.

---

## v1.4.22 — Smart search: one button, covers chosen for you

### Added — Smart search

One button in Tools → Rebuild covers. It walks the folder, works out every
series, searches all enabled sources, **chooses a cover itself**, and applies
it — sorting loose archives into folders on the way. Progress is reported per
series: what it picked, from which source, at what resolution.

Verified end to end on a flat folder of four archives: *"3 cover(s) saved,
4 archive(s) sorted"*, no console errors.

### How it chooses

In order of priority:

1. **Exact title match.** A cover for the wrong series is a failure however
   good it looks.
2. **Your source ranking from Settings.** This is the user saying which sites
   they trust, so it decides between equally valid covers.
3. **Resolution**, but only to reject a list thumbnail.

That third rule exists because ranking alone picks badly. Measured across
three titles, the top-ranked candidate was **6–15× smaller in pixels** than
the best available:

| Series | Rank-1 pick | Largest available |
|---|---|---|
| Solo Leveling | 230×310 | 800×1080 (12.1×) |
| Nano Machine | 512×742 | 2000×2898 (15.3×) |
| Close Family | 512×683 | 1280×1707 (6.2×) |

The same series ships at 175×238 on one site and 800×1164 on another, so a
rank-only auto-pick lands on a list thumbnail surprisingly often.

But size is deliberately *not* the primary key. Between two genuine covers the
ranking wins — letting resolution override it would mean silently ignoring the
Settings order whenever some lower-ranked site served a bigger JPEG. Both
rules have a test that fails if the other is allowed to dominate.

A source that blocks measuring is not penalised for it; being strict about
hotlinking says nothing about cover quality.

### Details

* Runs on a background thread — a large library is one search per series,
  far too slow to block the UI on.
* **Stop** halts cleanly after the current series.
* A second scan is refused while one is running.
* The bytes fetched while measuring are reused when saving, so a cover is
  never downloaded twice.
* `readerm covers` now uses the same logic and prints the chosen resolution.

### Note

The ranking was already respected before this — `search_all` merges in rank
order and the score sort is stable — so the existing manual picker listed
candidates in your preferred order too. What is new is that the choice no
longer needs a human.

853 passing.

---

## v1.4.21 — Cover rebuilder: pick a folder, sort a flat library

Three questions, three answers: **yes, yes, and yes** — one of them already
worked, one needed a fix, one needed a button.

### Added — choose which folder to scan

The rebuilder always accepted a folder argument, but only the CLI could pass
one; the GUI silently used your downloads directory. There is now a
**Choose folder** button in Tools → Rebuild covers, the chosen path is shown,
and **Reset** goes back to the configured downloads folder. It still recurses
into every subfolder.

### Fixed — `Ch.001-036` style names

`Close Family Ch.001-036.cbz` already resolved to *Close Family*, but several
near neighbours did not. `Chs.001-036` became **"Close Family Chs 001"**,
because the pattern tried `ch` before `chs` and left the `s` stranded in the
title. Now the longest spelling matches first, and `Chapt.`, `Cap.`,
`Capitulo` and `~` ranges are recognised too.

Titles that *contain* a marker word are unaffected — Chainsaw Man, Case
Closed, Cells at Work, Chi's Sweet Home, Eden's Zero, Ex-Arm and E-Rank Healer
all survive whole, because a marker only counts when a number follows it.

### Added — sort a flat folder into one folder per series

For the "everything is in one directory" case there is now a **Sort into
folders** button, and `readerm covers --sort-only`. It moves every loose
archive into a folder named after its series and stops there — no cover
downloads, no network calls at all.

Multi-volume sets group correctly: `Close Family Ch.001-036.cbz` and
`Close Family Ch.037-072.cbz` land in the same folder. Verified on a flat
folder of loose archives: 5 files, 4 folders, both Close Family volumes
together.

The button only appears when there is something loose to tidy, and the scan
line says how many groups are still sharing a folder.

### Changed — dedicated CLI flags

`--dry-run`, `--sort-only` and `--replace` replace the overloaded `--urls`
and `--reverse`. Reusing `--sort` was a mistake: it has a fixed choice list,
so `--sort folders` was rejected by argparse before the command ever ran.
`--urls` still works as a dry run for anyone who scripted it.

842 passing.

---

## v1.4.20 — Cover rebuilder

### Added — Tools → Rebuild covers

Point it at a folder and it walks the whole tree, finds every `.cbz`, works
out which series each one belongs to, searches every enabled source, and
writes `cover.jpg` **beside that archive**.

You pick the cover. Candidates are shown as thumbnails ranked best-first
(exact title match scores highest), because a fuzzy hit on a large catalogue
is usually a different series — applying that silently would be worse than
asking.

**Covers go in the archive's own folder, never a shared parent.** Where
several different series sit loose in one directory, each is first moved into
a folder of its own — otherwise one `cover.jpg` there would be wrong for all
but one of them. A directory that already holds a single series is left
exactly as it is; this never reorganises a tidy library.

### Recovering titles from filenames

A CBZ is named for its contents, not the series, so the title has to be
reconstructed. All of these resolve correctly:

| Filename | Title |
|---|---|
| `Afterlife Diner - Chapters 001-050.cbz` | Afterlife Diner |
| `Afterlife Diner - Chapters 001-003, 007-008, 020.cbz` | Afterlife Diner |
| `[Group] Solo Leveling - c045 (2024) [1080p].cbz` | Solo Leveling |
| `Nano.Machine.Chapter.5.cbz` | Nano Machine |
| `The Beginning After The End Vol 3.cbz` | The Beginning After The End |
| `Eleceed - Episode 200.cbz` | Eleceed |
| `ワンピース - Chapters 001.cbz` | ワンピース |

The tricky part is knowing which trailing numbers to keep. `Tower of God -
005` is an index; `Kingdom 2` and `Overlord 3` are titles. Stripping every
trailing number truncated real titles — my first attempt turned `Series 2`
into `Series` — so an index now needs a dash separator or zero-padding.

### Safety

* Scanning is read-only; nothing changes until you choose a cover.
* Folders that already have a cover are skipped unless you tick *Replace*.
* Moving never overwrites: a name clash is suffixed `(2)`.
* Running it twice does not nest folders inside folders.
* `raw/` page folders are ignored.

### Fixed — cover thumbnails rendered blank

Three of fifteen thumbnails in the picker came up empty with
`ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`. The images fetched fine from Python
(all HTTP 200) — the embedded browser was refusing them cross-origin.

Two changes: every preview is now proxied through Python as a data URI rather
than only the Referer-gated ones, and `Api._source()` learned to resolve
aggregate member ids. Covers from Madara sites carry a source id like
`madara.toonily`, which is a real source but not in the registry, so proxying
them failed with "Unknown source" and fell back to the blocked direct URL.
Now 15 of 15 preview, with zero console errors.

### Added — `readerm covers`

The same tool from the CLI. `--urls` prints the plan without changing
anything; a plain run takes the best-ranked cover, since a terminal cannot
show thumbnails.

816 passing.

---

## v1.4.19 — Background downloads in the system tray, crash-safe resume

### Added — minimise to the system tray

**Settings → Background → Minimise to system tray.** With it on, closing the
window hides it and downloads keep running; the app only exits from the tray's
**Quit**.

The tray context menu is rebuilt every time it opens, so the numbers are live:

```
↓  2.4 MB/s     ETA 4m 12s
Chapters:  7/40  (33 left)
Pages:  812/4100
Downloaded:  318.4 MB
Queued:  3 waiting
   • Solo Leveling (4/20)
   • Nano Machine (3/20)
   ────────────────────────
   Open ReaderM
   Pause queue
   Quit
```

The hover tooltip carries the same summary in one line, and the icon turns
mint with an activity dot while anything is downloading. A desktop
notification fires when a download finishes (switchable).

**Pause queue** stops *new* jobs starting; it deliberately does not interrupt
a chapter already in flight, since that would throw away partial work resume
could reuse.

`pystray` is an optional extra:

```bash
pip install "readerm[tray]"
```

It is optional for a real reason: **importing pystray raises on a machine with
no display** — on a headless box `import pystray` dies with
`Xlib.error.DisplayNameError` before any of our code runs. The import is
therefore guarded and probed lazily, the tray never blocks startup, and if it
cannot start the window keeps its ordinary close-quits behaviour. The Settings
toggle disables itself and says why rather than silently doing nothing.

### Added — transfer rate, ETA and queue depth

Nothing measured throughput before this: the engine only totalled bytes
*after* a job finished, which is no use while one is running.

* **Rolling-window rate**, not a lifetime average. A cumulative figure keeps
  reporting a high speed long after a transfer slows — precisely when the
  number matters. Bytes are counted as chunks land, not per finished file,
  which otherwise makes the rate lurch between zero and a spike.
* **ETA from pages.** Total byte size is unknowable up front (no source
  reports image sizes), but page counts arrive with each chapter. Chapters
  whose page lists have not been fetched yet are projected from the average
  so far — and only once at least one chapter has completed, so the average
  is grounded in real data.
* **Honest `--`.** When the remaining work genuinely cannot be known, the ETA
  says so instead of inventing a number.

New `Api.get_progress()` exposes all of it to the GUI as well.

### Fixed — crash resume lost concurrent downloads

The journal that backs "resume after a crash" was **a single file**. That was
fine when one download ran at a time and wrong the moment the GUI grew
concurrent jobs. Both bugs were reproduced before being fixed:

* starting job B **overwrote** job A's record — A could never be resumed;
* whichever job finished first called `clear_journal()` and **wiped the record
  of the one still running**.

Each job now owns `~/.readerm/jobs/<id>.json` and clears only its own. Writes
are atomic and fsynced, so a crash mid-write cannot leave a truncated file
that reads back as "no job", and a corrupt file is dropped rather than
breaking every future read. A pre-1.4.19 `job.json` is migrated automatically.

Verified end to end: two concurrent downloads, `os._exit(137)` mid-run — both
journals survived, both resumed, and each skipped what was already on disk
(one refetched 5 images, not 368).

`readerm resume` now lists every interrupted job. It also no longer crashes
with `EOFError` on piped input — the second prompt lacked the guard the first
one had.

### Fixed — a test that failed on correct code

`test_closed_handler_returns_nothing` used `^\s+return\s+\S`, and `\s` spans
newlines, so a bare `return` followed by the next statement matched. An early
bare return is exactly what a guard clause is. Tightened to `[^\S\n]`, and
re-verified that it still catches a real `return api.shutdown()`.

769 passing.

---

## v1.4.18 — Madara sites become one source; dedupe rewritten

### Added — "Madara Sites", one entry for ten sites

Every install of the **Madara** WordPress theme is the same software with a
different skin, so listing them separately made Settings long and pushed
"which mirror has this?" onto you. They are now a single source, `madaranet`,
that fans out across all ten in parallel and merges the results.

Replaces the six standalone entries (Toonily, Manhua Plus, Manhua Top, Manhwa
Top, MangaRead, Setsu Scans) and adds **four new sites** found by scanning ~60
candidate domains: **Coffee Manga**, **MangaSushi**, **MangaOwl**, **MangaGG**.

Settings drops from 24 rows to **19**, while reachable sites rise to **28**.

Nothing about the scraping changed — every per-install quirk measured in
v1.4.15 still applies. Pasting any member's URL still works and downloads from
that site directly; the row shows which site each hit came from.

Two candidates were **tested and rejected** rather than shipped broken:
`manhwafull.com` (search cards carry `href="/"`, so there is nothing to
follow) and `zinmanga.net` (chapter AJAX 404s and the series page embeds no
list).

### Fixed — a genre browse took 25 seconds

Two bugs, both found by timing the members individually:

1. The aggregate handed each member a genre **display name**, but the slug
   differs per install — "Action" is `action` almost everywhere and
   `genre-action-new-genre` on Manhwa Top. The wrong slug 404s.
2. **A 404 was retried five times with exponential backoff.** A definitive
   answer was costing 30+ seconds to reach.

Measured on `browse(genre="Action")`: Manhwa Top **31.0s**, MangaOwl **36.4s**
(it answers 410). Overall **25.0s → 1.4s**. The fail-fast change helps every
source, not just these.

### Fixed — dedupe destroyed CJK results, and missed obvious duplicates

The key ended with `[^a-z0-9]+ -> " "`, which deletes every non-ASCII
character. **Every** Japanese, Korean and Chinese title therefore normalised
to the empty string and they all landed in one group.

Reproduced live: a search for ワンピース put four titles in one bogus row and
**silently dropped three distinct series**. A search for 一 lost another.

Four fixes:

* **Unicode-safe key.** CJK titles survive and compare correctly.
* **Only recognised edition notes are stripped.** Stripping all parentheses
  merged "Solo Leveling" with "Solo Leveling (Pre-serialization)" and "Tower
  of God" with "Tower of God (Season 2)" — different works. `(Official
  Colored)`, `[Fan Colored]` and friends still merge.
* **Untitled rows are never grouped.** "(Oneshot)" and "[Artist]" both
  normalised to `""` and merged into one row.
* **More real duplicates caught,** as you asked: word-break variants merge
  ("Nano Machine" = "Nanomachine", "Solo Max-Level Newbie" = "SoloMax Level
  Newbie") and leading articles are ignored ("The Beginning After The End" =
  "Beginning After the End"). Live: "nano machine" now collapses 12 sites into
  one row.

Merging also **backfills metadata** now. The best-ranked copy is not always
the most complete — MangaDex often wins on rank while reporting no chapter
count, and the copy it displaced had both a count and a cover. Empty fields
are filled from the losing copies; the winner's own data is never overwritten.

### Notes

* The aggregate's id is `madaranet`, not `madara` — that would read as the
  theme engine in `madara.py`, the exact confusion v1.4.17 untangled.
* Setsu Scans still needs FlareSolverr, but the aggregate is **not** flagged
  Cloudflare: nine of ten members work without one, and a member that cannot
  be read is skipped.

734 passing.

---

## v1.4.17 — Madara Scans added, and the "Madara" name disambiguated

### Added — Madara Scans (`madarascans`)

Reported as "Madara doesn't show in settings". It genuinely was not there, and
the reason is a naming collision I created last release.

**Two unrelated things are called Madara:**

| | What it is | In Settings? |
|---|---|---|
| `readerm/sources/madara.py` | the shared scraper for the **Madara WordPress theme**, which six *other* sites run | **No** — engine code, no `base_url`, never registered |
| `readerm/sources/madarascans.py` | **Madara Scans**, an actual scanlation site | **Yes** — new in this release |

v1.4.15's changelog talked about "the Madara scraper" meaning the theme
engine, which reasonably reads as though the site had been added. It had not.
Now it is, and the registry holds **24** sources.

To stop this recurring: `MadaraSource.is_engine()` returns True for the engine
class only — a plain class attribute would inherit, so all six theme-based
sites would have claimed to be engine code — and a test fails if any
registered source claims it.

Confusingly, **Madara Scans does not run the Madara theme**: it is
`themes/mangareader` (Themesia), the same family as Witch Scans, so it shares
no code with `madara.py`.

### Findings from the live site (2026-07)

* `madarascans.com` **301s to `madarascans.org`**; both domains are claimed so
  either pasted link resolves.
* `/series/` is the catalogue — 30 cards a page, 11 pages. `/manga/` returns a
  **53-byte empty document** and the homepage renders its grid in JS with zero
  cards server-side, so either would have silently never browsed.
* Browsing pages on the **query** (`?page=2`); the path form
  `/series/page/2/` answers 200 and returns page one. So do `?paged=`,
  `?pg=`, `?offset=` and `?show=` — all four returned the identical 30 slugs.
* Search pages on the **path** (`/page/2/?s=`) — the opposite of browse.
* Chapters are `#chapters-list-container div.ch-item`. Three selectors that
  look right match **zero** anchors here: `#chapterlist` (present only inside
  a `<style>` block), `.eplister` (absent), and `li[id^="chapter-item-"]` —
  the rows are `div`, not `li`, even though `chapter-item` appears once per
  chapter. That last one cost a round of debugging: the first build returned
  25 chapters on one series and **0** on another.
* Each card links the series **twice** (cover, then title), so entries are
  de-duplicated by slug; `/series/list-mode` matches the same selector but is
  a view toggle, not a series.
* Pages come from `ts_reader.run({...})` and hotlink fine (200 `image/webp`,
  no Referer).

Verified end to end: search 5, info OK, chapters 25/38/8 on three series,
18 pages, two real page downloads (3.2 MB + 3.5 MB), cover OK, and a valid
19-page CBZ through the download engine. Browse, genres (6, all fetched and
confirmed 200) and pagination (0 overlap between pages) all check out.

### Changed

* README, `SYNTAX.md`, `FEATURES.md` and the landing page all read 24 sources.
* README gained an explicit note on the two meanings of "Madara".

707 passing.

---

## v1.4.16 — GUI startup fix, Rich made optional, SYNTAX.md

### Fixed — the GUI could freeze on open

Reported as "really prone to crashing on opening UI". Reproduced, and it was
caused by v1.4.15.

`genres_all()` was a **serial loop with no time limit**. That was harmless
while every source answered from a hardcoded constant. The six Madara sources
added last release read their genre list off the live site — they have to,
because their slugs are renamed per install (Manhwa Top ships
`genre-action-new-genre`) — so the function started doing network I/O, and the
GUI `await`s it in its boot sequence.

Measured, with six sites merely **slow** (4s each, not down):

| | before | after |
|---|---|---|
| `genres_all()` worst case | **30.0 s** | **5.0 s** |
| `genres_all()` typical | 6.5 s | 1.1 s |
| GUI boot to interactive | — | **1.0 s** |

Unreachable sites were never the problem; those fail fast. Slow ones were.

It now runs the sources in parallel under a deadline. Whatever has answered is
merged, anything still outstanding falls back to its offline list rather than
vanishing from the picker, and a partial result is **not** cached so the next
call can fill it in.

### Fixed — the CLI could not start without Rich

`cli.py` and `menu.py` imported Rich at module scope, so on a bare clone —
no `pip install` — `py cli.py` died with `ImportError: No module named 'rich'`
before argparse ran. Not even `--help` worked. `tui.py` has guarded its
optional Textual import since v1.0; these two never did.

New `readerm/console.py` uses Rich when present and falls back to an ANSI
renderer when not: tables, panels, rules, prompts and a single-line progress
bar. Verified by hiding Rich from the import system — `--help`, `sources` and
a full download all work and stay coloured.

A test now fails if any module imports Rich directly again.

### Added — colour control and a better progress bar

* `NO_COLOR`, `FORCE_COLOR` and `CLICOLOR_FORCE` are honoured.
* Colour switches off when output is piped, so redirecting to a file no longer
  produces escape-code soup.
* Windows ANSI is enabled through the console API; hosts too old for it get
  plain text instead of literal `←[36m` noise.
* The download bar gained a **percentage** and an **ETA** column. Elapsed time
  alone told you nothing on an 800-chapter series.

### Added — `SYNTAX.md`

A full command reference: every command, flag, chapter-selection form,
template placeholder, environment variable and exit code, plus worked recipes.

Every flag in it is checked against the real parser by a test, every command
is checked against the dispatch table, and the source count is checked against
the registry — so it cannot quietly drift.

### Changed

* The CLI's own `--help` description said "MangaDex, Mangakatana, Natomanga
  and Weeb Central" long after there were 23 sources. It is now derived from
  the registry.

### Not changed — the TUI

The brief was to touch it **only if it errored**. It does not: booted under
Textual 8.2.8, cycled all four tabs, listed 23 sources and 61 genres, and
logged no exceptions. Left alone deliberately.

### Could not reproduce — Natomanga

Tested end to end against the live site and every stage passed:

```
search    3 results        get_manga_info  OK
chapters  787              images          46
download  142,532 bytes    covers          6/6 HTTP 200
```

Covers came back 200 from all three shard hosts. If it is still failing for
you, please send the exact URL or search term and what you see — a regional
block or an ISP-level DNS issue would both look like this and neither is
visible from here. In the meantime the v1.4.15 Cloudflare fix and this
release's genre-deadline fix both remove ways a single source could appear to
hang the app, which may be what was actually being seen.

### Not added — Mantrra

I could not find it. `mantrra.com` is a **GoDaddy parked domain** — it serves a
114-byte redirect to a for-sale lander, no manga content. `mantrra.in` is also
a GoDaddy placeholder. `mantra.com`, `mantrra.net/.org/.co/.xyz/.to/.me`,
`mangatrra.com`, `mantrascans.com` and `mantra-scans.com` do not resolve;
`manterra.com` is a plastics manufacturer and `mantraa.com` is an M&A firm.

Rather than guess at a spelling and ship a scraper against the wrong site,
I have left it out — tell me the exact URL you use and I will add it.

---

## v1.4.15 — Eleven new manhwa/manhua sources, and a Cloudflare timeout fix

### Added — the six requested sites

| Source | Site | Notes |
|---|---|---|
| `witchscans` | witchscans.com | Manhua; `ts_reader` page lists |
| `writerscans` | writerscans.com | 27-title group; client-side catalogue |
| `manhuatop` | manhuatop.org | Manhua; Madara |
| `setsuscans` | setsuscans.com | **Cloudflare — needs FlareSolverr** |
| `manhuaplus` | manhuaplus.com | Manhua; Madara |
| `demonicscans` | demonicscans.org | MangaDemon / Demonic Scans |

### Added — five more, for "more manhwa and manhua sources"

`asurascans` (asuracomic.net), `flamecomics` (flamecomics.xyz), `toonily`,
`manhwatop` (manhwatop.com) and `mangaread` (mangaread.org). The registry now
holds **23** sources.

Every one was verified end to end before shipping: search, series info,
chapter list, page list, and two real page images plus the cover downloaded
through the engine's own code path. Ten of the eleven produced valid CBZ
archives with no corrupt entries; the eleventh is Setsu Scans, which cannot be
read at all without a solver (below).

### Added — a shared Madara scraper

Six of the new sites run the Madara WordPress theme, so the scraping lives
once in `readerm/sources/madara.py` and each site file declares only what
differs. That is not cosmetic: the parts that differ are exactly the parts
that are wrong if you guess them.

* **Genre prefix** varies per install and a wrong one is a hard 404 —
  `/manga-genre/` on Manhua Plus and Manhwa Top, `/manhua-genre/` on Manhua
  Top's namesake, `/genres/` on MangaRead, `/webtoon-genre/` on Toonily.
* **Genre slugs are read off each site's own search form**, not guessed.
  Manhwa Top ships `genre-action-new-genre` and `adventure-genre-hot`; no
  guess produces those. Labels are cleaned for display, the request uses the
  real slug.
* **Search pages with `&paged=`, never `/page/N/`.** On Toonily the path form
  returns page one — 18 results, all 18 identical to page one — so "next page"
  would have looped forever there while appearing to work elsewhere.
* **The chapter AJAX call sends an explicit empty body.** A bare POST answers
  400 with zero bytes; the same request with `Content-Length: 0` answers 200
  with the full list.
* **Manhua Top browses `/manga/`, not `/manhua/`,** even though its series
  live under `/manhua/` — `/manhua/?m_orderby=views` returns zero cards, which
  was reproduced four times, three seconds apart.

### Fixed — a Cloudflare site could stall an entire multi-source search

Adding Setsu Scans exposed a pre-existing bug in the retry path rather than
introducing one.

When a site answers with a Cloudflare challenge and no FlareSolverr instance
is running, `Source.fetch` treated the failed hand-off as a transient error
and retried with exponential backoff: 2 + 4 + 8 + 16 + 32 seconds. Retrying
cannot possibly help — a solver does not appear mid-request — so every call
to such a site burned about a minute before failing.

Measured on Setsu Scans with no solver running:

| | before | after |
|---|---|---|
| one search on that site | **67.5 s** | **0.1 s** |
| `search_all` across every source | **66.1 s** | **3.7 s** |

The whole 23-source search was being held hostage by the one site that could
not answer. `_solve_challenge` now distinguishes "the solver said no" from
"there is no solver", sets a sticky per-source flag in the latter case, and
`fetch` stops retrying. The error message now names FlareSolverr instead of
failing silently. This also speeds up Weeb Central for anyone without a solver.

### Changed

* README's source table, the landing page tiles and `FEATURES.md` all list the
  new sites; the landing page hero now reads **23 sources**.
* Two more landing-page numbers are now test-enforced. The "tests passing"
  figure is checked against what pytest actually collects — a static count of
  `def test_` reads 595, because 30 `parametrize` decorators expand it to 694,
  so the test asks pytest rather than grepping.
* The "merged genres" stat was **removed** rather than updated. It is 86 with
  every site unreachable and 207 with all 23 answering, so a static page
  cannot state it as fact. A test now fails if it comes back.

### Notes

* **Setsu Scans cannot be verified from here.** It answers 403 with
  `cf-mitigated: challenge` to every request — root, `/manga/`, `www.`, with a
  full set of browser headers. The scraper was built against the Internet
  Archive snapshot of 2025-07-09, which confirms the Madara theme and the
  `/manga/<slug>/` layout. Its genre path is the theme default and is the one
  thing in this release that is **unverified**; if you run FlareSolverr and
  genres 404, that is the line to change.
* **HentaiRead** was not added: it is Cloudflare-gated like Setsu Scans, but
  no archived copy exists to build against, so guessing would be dishonest.
* Comick and Comix remain excluded for the reasons in v1.4.4.

---

## v1.4.14 — Direct execution fixed, landing page redesigned

### Fixed — `py menu.py` crashed with an ImportError

Running the file directly from inside the package raised
`attempted relative import with no known parent package`. `cli.py` and
`tui.py` already carried a self-bootstrap block for exactly this; `menu.py`
was added in v1.4.13 without one, so its relative imports had no parent
package to resolve against.

Rather than patch the one file, the same guard was applied to every module
that uses a relative import — `config.py`, `downloader.py`, `packager.py` and
`scraper.py` were all in the same position. A test now scans the package and
fails if any module using relative imports lacks the guard, so the next file
added cannot repeat it. `menu.py` also gained a `__main__` block, so running
it directly starts the menu instead of doing nothing.

Verified: all eleven modules now execute directly without an import error.

### Changed — the landing page has its own identity

The page had been built to imitate a code host, down to the repository tabs,
language bar and star/fork/watch chrome. That was a poor fit: it framed the
project as a repository listing rather than a tool, and half the furniture
described things the page could not actually know.

Rebuilt from scratch:

* **New visual language** — deep plum-navy ground, warm coral-to-violet
  gradient, Sora for text and JetBrains Mono for code. Nothing borrowed.
* **A hero that shows the product** — a terminal mock running a real command,
  with four honest stats beside it.
* **Sections that answer questions** — why it exists, the three interfaces,
  the twelve sources as a scannable grid, the CLI as tabbed reference,
  screenshots, and a two-line install.
* **Light and dark themes**, remembered between visits.

Every number on the page is checked against the repository by a test, and the
source grid is checked against the registry, so neither can drift.

The repository is referenced as **Compromisee/MDL** throughout.

### Tests

611 offline + 21 live. The landing-page suite was rewritten for the new
structure; it also runs in 8 seconds rather than 309, because the old
history-navigation tests are gone with the tabs they tested.

---

## v1.4.13 — Interactive menu, richer CLI search

### Added — `readerm menu`

A progressive, numbered interface. Every prompt is a list you answer with a
number; `b` goes back and `q` quits from **any** depth, so it is impossible to
get stranded in a submenu. It covers search, trending, pasting a URL, the
library, bookmarks, settings (folders, formats, sources, filters) and tools.

It deliberately needs nothing beyond `rich`, which is already a hard
dependency. The full-screen `readerm tui` needs Textual, an optional extra
that in practice is often not installed — so the menu is the interface that
always works.

Edge cases that would otherwise look like crashes are handled: a closed stdin
(a pipe that ran out) and Ctrl-C both unwind cleanly, and running it without a
terminal prints guidance instead of blocking forever on a read that will never
return.

### Added — search syntax

    --type manga|manhwa|manhua|comic|novel   narrow by series type
    --status Ongoing|Completed|...           narrow by publication status
    -n, --limit N                            cap the results
    --sort title|source|chapters|year        sort, with --reverse
    --urls                                   one URL per line, for pipes
    --json                                   machine-readable output
    --open N                                 show details for result N
    --download N                             download result N

`--open` and `--download` act on the numbers just printed, so finding
something and acting on it is one command instead of a copy-paste of a URL.

`--type` is derived rather than requested, for the same reason the GUI filter
is: only one of the twelve sources accepts a type parameter. The type is
classified from origin language and tags, with a per-source default for
single-type catalogues, and results whose type cannot be determined are kept —
dropping them would erase whole sources from a filtered search. Sorting by
chapters puts unknown counts last rather than treating them as zero.

### Fixed — `readerm tui` crashed instead of explaining itself

Textual was imported at module scope while the "Textual is not installed"
message lived in `run_tui()` further down. With Textual absent the module
failed *while it was still being imported*, so the friendly message never ran
and the command died with a raw `ModuleNotFoundError` traceback. The import is
now guarded, and the message points at `readerm menu`, which needs nothing.

### Fixed — the landing page was quoting stale numbers

Six counters had drifted, three of them contradicting each other on the same
page: 330 vs 408 features, 376 vs 255 tests, and 9 sources when there are 12.
The genre metric said 99 where the live merge produces 116. All now match the
repository.

### Tests

609 offline (up from 583) + 21 live.

---

## v1.4.12 — GUI crash hardening

The GUI was described as very prone to crashing. Four measured causes, plus
one plain bug the audit turned up.

### Fixed — 87 of 102 bridge endpoints could raise into pywebview

Every public method on the API object is called from JavaScript. An exception
gets marshalled across the native bridge, which surfaces as a rejected promise
at best and can tear the view down at worst -- and the JS side cannot tell
"the endpoint blew up" from "the endpoint returned nothing". Only 15 methods
guarded themselves.

A metaclass now wraps every public method, so failures come back as
``{"ok": false, "error": ...}`` -- the shape ``callApi()`` already understands.
Measured after: 102 of 102 guarded, and 0 of 8 hostile-argument calls raise.
Doing it by hand is what decayed to 15 in the first place, so a method added
later is protected automatically.

### Fixed — a bad queue entry killed the download thread

``_start_queued()`` runs in the *finally* of a finished job's thread. A cart
entry with a non-numeric option (``retries: "not-an-int"``) made ``int()``
raise out of ``_spawn`` on that thread, with no handler: the job reported
done, the worker died, and the queue silently stalled. Verified with
``threading.excepthook`` -- before, one escaped exception; after, none.

Download options are now coerced and clamped rather than trusted, and a
malformed entry is dropped with an error event instead of taking the queue
with it.

### Fixed — the cover cache was bounded by count, not bytes

A proxied cover is a base64 data URI: 116 KB measured for one Webtoons cover.
The 240-entry cap therefore held ~28 MB, and scaled without any ceiling for a
source with larger art. It is now capped at 24 MB with proper LRU eviction --
the old code called ``clear()``, throwing away every cover the moment it
filled. Oversized items are served but not retained.

### Fixed — a rejected call left the UI hung and silent

There were no ``unhandledrejection`` or ``error`` handlers. Measured with a
failing endpoint: the loading spinner ran forever, **no message was shown at
all**, and the failure escaped to the console. There are now global handlers
that clear stranded spinners and surface a message, and the hot paths --
``search``, ``browse``, ``get_manga``, ``get_sources`` -- go through the
guarded wrapper. A failed search shows a retry action instead of a dead
screen. Measured after: 0 unhandled rejections, spinner cleared, message
shown.

### Fixed — Invert never worked

The audit found ``renderChapters()`` being called although no such function
exists; the real name is ``renderChapterList()``. Invert has thrown a
``ReferenceError`` on every click since it was added in v1.4.6 -- the
selection changed in state but the rows never repainted and the handler
aborted before updating the download button. A test now scans for any helper
that is called but never defined.

### Tests

583 offline (up from 552) + 21 live.

---

## v1.4.11 — One config.json, and the settings-loss bug behind it

### Fixed — settings resetting themselves

Theme, accent, sources, passcode preferences and the output directory would
all revert at once. The cause was not the individual settings screens, which
work: it was the store underneath them.

`settings.json` was the **only** store in the app that wrote without a lock
and without an atomic replace -- every other file (`config.json`,
`library.json`, `filters.json`, `progress.json`, `lock.json`) already used
tmp+`os.replace`. That lost data two ways:

* **An interrupted write** left truncated JSON on disk. `load_settings()`
  caught the `ValueError` and quietly returned the defaults, so a single bad
  shutdown reset every preference with no error anywhere.
* **Concurrent saves clobbered each other.** `set_settings()` did
  read-modify-write outside any lock, and so did the download-folder picker.
  Whichever landed last wrote back the state it had read, erasing the other's
  change. Measured on the old code, four threads saving at once destroyed the
  theme, accent and output directory in **5 of 5** runs; after the fix,
  **0 of 5**.

The Save button only posts 17 of the 35 keys, so any save at all could take
the appearance settings with it. That is now covered by a test.

### Changed — everything lives in config.json

`config.json` already held the per-source ranking and exclusion. It now also
holds the app settings, in two clearly separated sections::

    { "settings": { "theme": ..., "output_dir": ... },
      "sources":  { "mangadex": { "enabled": true, "rank": 0 } } }

Both sections share one `RLock` and one atomic write. `save_config()` also
refuses to drop the settings section, since its callers only ever build the
sources half.

An existing `settings.json` is folded in on first read and then left alone;
the per-source config already in `config.json` is preserved. Verified with
both files present, and with a corrupt legacy file.

### Note

While reproducing this I first wrote a browser probe that injected the
pywebview bridge after page load. `whenReady()` waits for the
`pywebviewready` event, so boot never ran and the probe "reproduced" dead
themes and an empty source list. That was the harness, not the app -- firing
the event correctly showed the UI working. The real defect was in the
persistence layer, which is what the measurements above cover.

### Tests

552 offline (up from 534) + 21 live.

---

## v1.4.10 — Bookmark drag-and-drop actually works

Dragging a bookmark did nothing. The HTML5 wiring itself was fine -- a real
mouse drag from the card body onto a folder tile did fire `dragstart` ->
`dragover` -> `drop` and call `move_bookmark`. The v1.4.7 test that "passed"
had dispatched a synthetic `drop` event, which skips the whole drag gesture,
so it never exercised the paths that were broken. Four real blockers:

**The cover swallowed the gesture.** An `<img>` is natively draggable, so
starting the drag on the artwork -- which is most of the card's surface, and
where anyone would naturally grab -- dragged the *picture* instead of the
card. Measured payload: `text/uri-list, text/html, Files`, none of which the
folder tile accepts. The cover is now `draggable = false`.

**There was often nothing to drop onto.** The folder grid is hidden when no
folders exist, so on a fresh install the drag had no target anywhere on
screen. Dragging genuinely did nothing, and there was no way to tell why.
Two floating drop zones now appear *while* a drag is in progress: **All
bookmarks** and **new folder**.

**A filed bookmark could not come back.** Once inside a folder there was no
root drop target, so filing was one-way.

**The highlight flickered off mid-drag.** `dragleave` fires when the pointer
crosses onto a *child* element, so the naive handler cleared the drop state
while the pointer was still over the tile. Enter/leave pairs are now counted.

One more, found while verifying: the first version of the drop zones toggled
`display` on an in-flow element, which reflowed the grid and **shifted the
cards out from under the pointer** the instant the drag began -- it hung the
test harness. The zones are now `position: fixed` and fade in, so the class
alone causes zero layout change (measured: card Y identical before/after).

A missed drop is also swallowed now; the browser would otherwise treat it as
"open this link" and navigate the whole app away.

### Tests

534 offline (up from 529) + 21 live. The drag tests now use real mouse
gestures rather than synthetic events, which is what let the original bug
through.

---

## v1.4.9 — Dialog inputs themed

### Fixed — the folder name field was unstyled

The themed-input rule is scoped to `.settings-card` / `.setting-row`. The
folder-name field and the prompt modal live in overlays, so nothing matched
them and they fell back to the browser default. Measured against a correctly
styled settings input:

| | settings input | dialog input (before) |
|---|---|---|
| background | `rgb(38,38,50)` | `rgb(255,255,255)` |
| text | `rgb(230,230,240)` | `rgb(0,0,0)` |
| border | `1px solid` | `2px inset` |
| radius | `12px` | `0px` |
| font | Inter 13px | Arial 13.3px |

White box, black text and an inset border on a dark panel. This is the same
bug the settings inputs had in v1.3.0, one layer up.

Rather than write a second near-duplicate block, the dialog inputs were added
to the existing rule — base, `:hover`, `:focus` and `::placeholder` — so the
two can never drift apart.

### Fixed — lock screen fields rendered in Arial

Sweeping every text input for browser defaults turned up a smaller related
issue: `.lock-input` never set `font-family`, so the passcode field and both
recovery fields used Arial while everything around them used Inter. Their
colours were already correct, which is why it read as slightly-off rather
than broken. Zero inputs now fall back to browser defaults.

### Tests

529 offline (up from 523) + 21 live, including a sweep that maps every text
input to the rule styling it.

---

## v1.4.8 — Overlay buttons fixed, shortcuts moved into Settings

### Fixed — the shortcuts X button, and every exit from the folder picker

`app.js` binds its listeners as it runs. Both overlays were declared *after*
the `<script>` tag, so at bind time `$("shortcutsClose")` and
`$("fpCancel")` were `null` and no handler was ever attached. There was no
console error, and the buttons were fully hit-testable, which is why this
looked like a styling or z-index problem rather than a missing listener.

Confirmed with CDP `DOMDebugger.getEventListeners`:

    shortcutsClose   listeners=NONE
    fpCancel         listeners=NONE
    modalCancel      listeners=['click']     <- declared above the script

The reported X button was the visible half of it. The folder picker was
worse: **Cancel, "Just bookmark it", Create and the backdrop were all dead**,
so once that dialog opened there was no way out of it. Both overlays now sit
above the script tags; all five exits verified working.

A test now enforces the rule generally — every id that `app.js` attaches a
listener to must appear before the script — so a future overlay cannot
reintroduce this.

### Changed — shortcuts live in Settings

The full list is rendered into a **Keyboard shortcuts** card in Settings,
from the same array the key handler uses, so the two cannot drift apart.
Pressing `?` still opens the quick overlay from anywhere. The rail's "Keys"
button was removed, since it was a second home for the same thing.

### Tests

523 offline (up from 517) + 21 live.

---

## v1.4.7 — Bookmark folders, type filter, cover and corner fixes

### Fixed — covers missing in Bookmarks and Library

Both views built their tile with a raw `<img src="...">`. This document sends
`no-referrer` (MangaDex serves a placeholder otherwise), so hotlink-protected
CDNs answer **403** from a bare `<img>` and sharded hosts get no mirror walk.
Search results already went through `attachCover()`, which proxies those
through Python — bookmarks and library rows did not, so covers from Webtoons
and friends were permanently blank there.

Bookmarks were also storing the *normalised* library key as their `url`.
That key has no scheme, so every bookmark linked nowhere. They now keep the
URL as given, plus any `cover_mirrors`.

### Fixed — the download queue was invisible

The queue card was nested inside `#dlActive`, which starts hidden and is only
revealed once a job is running — so a queue built up *before* pressing
Download could never be seen. It now sits outside that container and renders
whenever the Downloads view opens.

### Fixed — the Type filter did nothing

Searching "one piece" restricted to **Manhwa** returned 62 results, all of
them manga. Only one of the twelve sources (Weeb Central) implemented a
`series_type` parameter; every other source silently ignored it.

Type is now derived rather than requested: `classify_type()` maps origin
language (`ja` → Manga, `ko` → Manhwa, `zh` → Manhua) with explicit tags
taking priority, and sites with a single-type catalogue declare a
`default_series_type` fallback. Measured after: "one piece" as Manhwa returns
**0**, as Manga **41**; "solo leveling" as Manhwa returns 2, as Manga 3.

Results whose type genuinely cannot be determined are **kept** — dropping
them would erase whole sources from every filtered search.

### Fixed — square corners missed the most visible shapes

The setting flattens the radius variables, but the search box, both progress
bars and a dozen pills hardcoded `999px`, which no variable can reach. 26
such rules existed. Measured: `.searchbar` stayed at 999px in square mode
before, now 0px.

### Fixed — chapter min/max appeared to do nothing

The filter worked; the data did not exist. Only **5 of 22** results carried a
chapter count, because MangaDex leaves `lastChapter` empty for every ongoing
series and Weeb Central's search is JS-rendered. Unknown counts are kept by
design, so a `min_chapters` of 500 still showed them and the setting looked
ignored.

MangaDex now surfaces `lastChapter` where it exists (coverage 5/22 → 9/22),
and a new **Strict chapter range** option hides unknown counts for anyone who
wants a hard filter. The default stays lenient.

### Added — bookmark folders

* Create, rename and delete folders; deleting keeps the bookmarks and moves
  them back to the root, so nothing is lost by accident.
* File a bookmark by **dragging it onto a folder tile**, or pick a folder
  from a popup when bookmarking (offered only when folders exist, so the
  first bookmark is still one click).
* Optional per-folder **lock** and **blurred covers**.
* A folder's cover is the first book added to it.
* A bookmark pointing at a deleted folder falls back to the root rather than
  disappearing.

### Added — advanced info, custom columns, tidier filters

* **Advanced info** (opt-in) shows year, status, type, original language,
  demographic, last chapter/volume, authors and artists on the manga page.
  Every field is optional and omitted when a source does not report it.
* **Result columns** setting: 0 keeps the responsive fit, 1–14 pins a count.
* The **source picker was removed** from the search filter row — enabling and
  ranking sources already lives in Settings.

### Tests

517 offline (up from 464) + 21 live. The new suite gets its own isolated
`HOME` per test; without it, folder state leaked between cases.

---

## v1.4.6 — Multi-genre search, full-width layout, shortcuts, count fixes

### Fixed — "downloaded" on the manga page was wrong

Three separate causes, all measured:

* **URL variants missed the library.** The key only stripped a trailing
  slash, so of seven realistic variants of one URL, **five missed** —
  `http://` vs `https://`, a `www.` prefix, a `?query`, a `#fragment` and a
  different case. Reaching a manga by a slightly different link made an
  already-downloaded series look untouched. Keys are now normalised, and old
  entries are found and migrated rather than orphaned.
* **Chapter labels drift.** Several sources append the release date to the
  label (`Chapter 02 21/02/2026`). When a site edits that date the recorded
  name stops matching the listed one, so a downloaded chapter showed as
  missing — *while still counting toward the total*, which is why the
  "N downloaded" pill and the highlighted rows disagreed. Matching is now on
  the chapter **number**, and the pill is derived from the same match.
* **`get_library_entry` indexed the library with a raw URL**, which the
  normalised keys broke. Replaced with a tolerant `library.get_entry()`.

The stored entry keeps the URL as given — the key has no scheme, so using it
for display would have produced links that do not open.

### Fixed — URLs with tracking parameters returned zero chapters

Four sources filtered chapter links by "does this href start with the series
path?" and built that prefix from the **full** URL, query string included.
Pasting a link with `?ref=` or `utm_*` made the prefix unmatchable, so every
chapter was rejected and the manga silently showed **no chapters at all**.
Measured on ManhwaRead: 36 chapters clean, **0** with `?ref=x`. Now a shared
`Source.series_path()` strips the query and fragment; all three affected
sources return identical counts with and without parameters.

### Fixed — two genre endpoints that always 404'd

* **Manhwa18** used `/genres/<slug>`; the site serves `/webtoon-genre/<slug>`
  (`/genres/`, `/genre/` and `/manga-genre/` are all 404). Verified 24 cards
  per genre, paginated.
* **nhentai** was handed shared genre labels like "action" that are not
  nhentai tags and 404, burning four retries and logging an error each time.
  Unknown labels now fall back to its search index.

A multi-source genre browse that previously logged four 404s now logs none.

### Added — multi-genre search

Genres combine instead of replacing each other:

* Chips and the dropdown **toggle**, building a selection.
* **Match: all / any** — intersection or union — appears once two are picked.
* Picked genres show as removable chips with a Clear button.

No source accepts more than one genre per request, so each is fetched
separately and combined. The intersection is computed **per source**: the
same title has different URLs on different sites, so pairing a hit from one
with a hit from another would invent matches neither site agrees with.
Verified the AND result is exactly the set intersection (22 of 40 each for
Action ∩ Romance on MangaDex), and that every returned row lists both genres.

With a text query the extra genres are applied to result tags instead.
Results that carry no tags are kept — dropping them would silently hide whole
sources that omit them.

### Changed — content fills the window

Views sat in a fixed 1080px column and centred themselves. Measured before:

| viewport | grid | unused | columns |
|---|---|---|---|
| 1280px | 1080px | 11% | 6 |
| 1920px | 1080px | **42%** | 6 |
| 2560px | 1080px | **57%** | 6 |

After, at 1920px: 1780px wide, **4% unused, 10 columns**. The caps are now
ceilings rather than fixed widths, so wide screens gain columns while an
ultra-wide monitor does not stretch covers into one unreadable row. Settings
forms deliberately stay narrower so they remain scannable.

### Added — keyboard shortcuts and QOL

18 shortcuts with a `?` help overlay generated from the same list the handler
uses, so the two cannot drift apart.

* `/` focus search · `?` help · `Esc` close/clear · `r` refresh
* `g` then `s d b l u ,` to navigate
* On a manga: `a` all · `n` new only · `c` clear · `i` invert · `d` download
  · `q` queue · `b` bookmark · `y` copy title and link

Shortcuts are ignored while typing in any field and while the lock screen is
up, and modifier combos are left to the browser. One subtlety: Chromium
reports `Shift+/` as key `/` with `shiftKey` set, which matched "focus
search" before the help overlay could ever open — shifted keys are now
matched explicitly.

Also added: **Invert** chapter selection (acting on visible rows only, like
the other bulk buttons) and **copy title + link** with an `execCommand`
fallback, because WebView2 does not always grant clipboard-write.

### Tests

464 offline (up from 424) + 21 live.

---

## v1.4.5 — ManhwaRead bulk fix, download cart, concurrent downloads

### Fixed — ManhwaRead bulk downloads lost chapters

Downloading a range from ManhwaRead reliably dropped chapters with
`Could not decode chapterData ...: Incorrect padding`.

The reader's page list is base64-encoded JSON, and the site **strips the `=`
padding** whenever the encoded length is not a multiple of four. Python's
`base64.b64decode` is strict about padding, so those chapters raised and were
skipped. Measured over twelve consecutive chapters of one series: chapter 03
had `len % 4 == 2` and failed while the other eleven decoded fine.

That ~8% hit rate is exactly why a single chapter usually worked and a bulk
range did not — the longer the range, the likelier it contained a bad one.
Re-padding to the next multiple of four fixes it. A 1–6 range that previously
finished 5/6 with one failure now completes 6/6.

### Fixed — connection pool smaller than the worker count

Every bulk download logged `Connection pool is full, discarding connection`.
urllib3 pools ten connections per host by default while the engine runs up to
sixteen image threads, so the surplus connections were closed and reopened for
every page. The pool is now sized to the worker ceiling: measured 0 warnings
after, on a job that produced them continuously before.

### Added — download cart and concurrent downloads

Several manga can now download at the same time.

* **Add to queue** next to the download button queues a manga and lets you
  keep browsing; anything past the limit waits for a free slot and starts
  automatically when one opens.
* **Download queue** panel lists running and pending jobs with per-job status,
  and pending entries can be removed individually or cleared.
* **Concurrent manga** setting (1–5, default 2).
* Stopping is per-job: `stop_download(job_id)` stops one download and leaves
  the others running. Verified live — stopping one of two in-flight jobs let
  the other finish a full 300-page download.
* A cancelled job now reports **stopped** rather than **failed**.

### Fixed — concurrent downloads mixed up chapters

This was the real hazard in running jobs side by side, and it existed in the
event layer rather than on disk.

Progress events were coalesced into a map keyed on the **chapter name alone**,
and the UI's progress rows used the same key. Chapter names are not unique
across manga, so two series both reporting "Chapter 01" collapsed into one
entry: one series' progress silently overwrote the other's, and they shared a
single progress bar.

Every engine event is now stamped with a job id, and both the coalescing map
and the UI rows are keyed on `(job, chapter)`. Aggregate counters are summed
across jobs instead of being overwritten, and a chapter row shows its owning
manga only when more than one download is running, so a single download looks
exactly as it always has.

Verified end-to-end with three concurrent jobs including two colliding
"Chapter 01"s: 0 unstamped events, correct per-job chapter counts (5/3/2), and
each series' Chapter 01 byte-distinct (31 vs 38 pages, different hashes) — no
cross-contamination. Output paths were already per-manga, so files on disk
were never at risk.

### Tests

424 offline (up from 393) + 21 live.

---

## v1.4.4 — nhentai, Webtoons and Natomanga covers; three new sources

### Fixed — nhentai returned nothing

Two separate faults, both measured against the live site:

* **Browse was always empty.** It fetched the site root, which is a landing
  page carrying **zero** `.gallery` cards. `/popular` is the real listing and
  returns 25 per page. The `Trending` sort mapped to `/popular-today`, a 404.
* **7 of the 12 genres were invented.** The list was generic manga genres
  rather than nhentai tag slugs; `romance`, `drama`, `fantasy`, `school-life`,
  `vanilla`, `historical` and `sci-fi` all answered **404**, so those genre
  browses failed outright. Replaced with slugs verified to return results
  (`big-breasts`, `sole-female`, `nakadashi`, `full-color`, …).

Covers now also follow the ordered `data-fallbacks` list the site puts on each
card — thumbnail, then `.webp`, then the first page — instead of the single
`src`, which is not always present on the CDN.

### Fixed — Webtoons covers did not load

`webtoon-phinf.pstatic.net` answers **403 to any request whose Referer is not
webtoons.com** (measured: 403 with no Referer, with `file://` and with
`example.com`; 200 with `https://www.webtoons.com/`).

The GUI sends `<meta name="referrer" content="no-referrer">` because MangaDex
serves a "read this at MangaDex" placeholder otherwise, so the two demands are
mutually exclusive in one document and no `<img>` tag can satisfy both.

Sources can now declare `cover_needs_referer`, and those covers are fetched by
Python with the correct header and handed to the page as a `data:` URI through
a new `proxy_cover` API (bounded cache, 240 entries). Verified in Chromium: six
Webtoons covers decoded at 480×623, none blank. Of the twelve sources only
Webtoons needs this — every other cover CDN answered 200 with no Referer.

### Fixed — Natomanga covers (re-researched)

v1.4.1 treated `img-r1` / `img-r2` / `imgs-2` as interchangeable mirrors and
rewrote a failing cover onto each sibling. **Re-measuring disproved that.**
Over ten consecutive search covers, each requested from all three hosts:

| host | 200s |
|---|---|
| the host named in the page markup | **10/10** |
| `img-r1.2xstorage.com` | 3/10 |
| `img-r2.2xstorage.com` | 1/10 |
| `imgs-2.2xstorage.com` | 6/10 |

They are content shards, not mirrors: `/thumb/naruto.webp` is 200 on `img-r1`
and a hard **404** on `img-r2`. Every rewritten fallback was a likely 404, so
the failure was being made worse. The URL from the markup is now the only
candidate, and the real failure mode — a transient 429/503 on the correct
host — is handled by retrying the *same* URL once.

### Added — three sources (twelve total)

| Source | Site | Notes |
|---|---|---|
| `mangadass` | mangadass.com | 18+ |
| `manga18club` | manga18.club | 18+ |
| `hentaiakane` | hentaiakane.com | 18+ |

Findings worth recording:

* **Mangadass** — `/?s=<term>` is a decoy: it returns the homepage grid
  unchanged (identical 24 titles for `naruto`, `daddy` and no query at all).
  `/search?q=` is the real endpoint. Chapters also needed a numeric sort: the
  "Read First"/"Read Last" buttons sit above the list and point at real
  chapters, so document order yielded 2, 3, 4, 5, 6, 7, 8, **1**.
* **Manga18.club** — both `/?s=` and `/list-manga?q=` are decoys returning the
  same 20 rows for every query; the form posts `search`. The reader ships no
  usable `<img>` tags — one placeholder and an obfuscated script — with the
  pages held in `slides_p_path`, an array of base64-encoded CDN URLs. Decoding
  it in Python reproduces exactly the 11 URLs a real Chromium run requested,
  so no browser is needed. Its series cover also had to be read from
  `.detail_avatar`; the previous selector fell through to the "you may also
  like" sidebar and returned a different series' artwork.
* **HentaiAkane** — the request said "hentaikane", which does not resolve
  (`.com`, `.net`, `.org`, `.xyz`, `.to` are all NXDOMAIN); `hentaiakane.com`
  is the live site. Pages come from its `ts_reader.run({...})` payload. Cards
  are scoped to `.bs` because `a.series` on the same page is the sidebar
  popular list, which would inject unrelated titles.

All three are stamped `content_rating: pornographic` and tagged `Adult`, so
Safe mode filters them and the UI shows the `18+` chip. End-to-end verified: a
real CBZ built from HentaiAkane came to 13,279,316 bytes across 14 pages.

### Not added

* **Comix** (`comix.to`) — every `/api/v1/` endpoint answers
  `403 {"message":"Missing token."}`. The token is produced by an obfuscated
  anti-bot chunk; the call still 403s from inside a real browser session
  holding `cf_clearance`, and the SPA renders a blank page headless (0 images,
  0 API responses observed). Nothing could be read reliably.
* **Comick** — unchanged from v1.0: `md_images` is empty for every title.

### Tests

393 offline (up from 355) + 21 live. Two v1.4.1 tests that asserted the
disproven Natomanga mirror behaviour were rewritten to assert the measured
behaviour instead.

---

## v1.4.3 — Aggregator fix, chapter-count filters, Webtoons and nhentai

### Fixed — multi-source search silently lost sources

Searching a popular title with several sources enabled returned far fewer
results than it should, and appeared to work only with a single source on.

Mangakatana soft-throttles by answering **HTTP 200 with a zero-length body**
instead of a 429. Measured: roughly 60% of rapid repeat searches came back
empty, while an immediate retry succeeded. `fetch()` treated that as success,
so the source contributed nothing and the aggregate looked broken. Empty
bodies are now retried with backoff — measured 6/6 successful searches after
the fix, against ~40% before.

This was a shared bug in the base class, so every source benefits. It also
explains the Natomanga symptoms: its searches and covers were fine in
isolation but dropped out under aggregate load.

Duplicate collapsing already keeps the highest-ranked source's copy and lists
the rest under `also_on`, which is now visible because the sources actually
report in. "One Piece" went from 25–29 unstable results to 54 across six
sources.

### Added — chapter-count filters

`min_chapters` was stored in settings but never applied. Both a minimum and a
maximum now work, in Settings under Content filters. Counts are read from an
explicit count, `last_chapter`, or the newest chapter label. Series whose
count cannot be determined are never filtered out — judging an unknown count
would make whole sources disappear from every filtered search.

### Added — two sources

- **Webtoons** (`webtoons`) — official site. Episodes are paged, and the
  viewer keeps real page URLs on `data-url` rather than `src`. Its CDN is
  hotlink-protected (403 without a Referer, 200 with), so chapters carry one.
- **nhentai** (`nhentai`) — **adult only**, tagged `pornographic` so Safe
  mode removes it and it shows an 18+ chip. Thumbnails are `t`-suffixed; the
  full page is the same path without it (21 KB vs 464 KB).

Both verified downloading real CBZs with zero empty pages.

### Not added

**HentaiRead** sits behind a Cloudflare interstitial (HTTP 403, "Just a
moment"). It would need FlareSolverr running to work at all, so shipping it
as a normal source would have produced a site that silently fails for most
people.

### Testing

- 355 offline tests plus 21 live-site tests

## v1.4.2 — Search fixed, square corners, thinner rail, better lock

### Fixed — search did nothing

Only genre/category browsing worked; typing a query and pressing Enter did
nothing. The search input carried a native `<datalist>`, and in WebView2 an
open datalist popup **consumes the Enter keypress**, so `keydown` never
reached the handler. The Search button worked, which is why category
browsing appeared fine.

The datalist is gone. Enter is handled on both `keydown` and `keyup`
(debounced so one press cannot fire twice), and suggestions now render into
a themed list that can actually be styled.

### Fixed — lock screen appeared too late

The overlay started hidden and was only shown once `lock_status` returned, so
a protected app was briefly readable. It now paints on the very first frame.

Two safeguards came with that, because covering the UI up-front is risky:

- the previous lock state is remembered, so an app with no passcode never
  flashes an overlay it does not need
- a fail-safe timer clears the overlay no matter what. Without it, a missing
  bridge or a hung call left the app permanently covered — caught when the
  existing dropdown tests started timing out against an unclickable page

### Added — square corners mode

A single switch in Settings turns off all rounding. It zeroes the radius
scale and flattens pills, fields, dropdowns and switches, while leaving
genuine circles (spinner, lock badge) round so controls stay recognisable.

### Added — thinner, expandable side rail

The rail is now 60px instead of 84px. An expand button widens it to 194px
and shows the labels inline; the state is remembered between runs.

### Improved — lock screen

Show/hide passcode button, a remaining-attempts counter that turns amber
then red, a shake on a wrong entry, and a live cooldown countdown that
disables the field while it runs.

### Testing

- 331 offline tests plus 17 live-site tests

## v1.4.1 — Crash on close, Natomanga covers, lock order, rounding, saved folder

### Fixed — crash on window close

Closing the window raised `unhashable type: 'dict'`. pywebview collects event
handler return values into a **set** (`return_values.add(value)` in
`webview/event.py`), and the `closed` handler added in v1.1.0 was
`api.shutdown`, which returns `{"ok": True}` for the JS bridge. A dict is not
hashable, so every close threw. The handler is now a thin wrapper that
discards the return value; `shutdown()` keeps its dict for the bridge.

### Fixed — Natomanga covers not showing

Natomanga mirrors each thumbnail across interchangeable CDN hosts, and any
one of them intermittently fails while the others serve the identical file.
Measured live: `storage.waitst.com` returned **429** and `img-r2` returned
**404** for images that came back **HTTP 200 with identical bytes** from the
sibling hosts.

Covers now carry a mirror list, and the UI walks it on error instead of
giving up on the first failure. Only when every mirror fails does the
fallback tile appear.

### Fixed — passcode did not gate startup

The lock check ran seven steps into boot, so settings, sources, genres,
filters, statistics and the trending feed were all fetched and painted
underneath the overlay before it appeared. The lock is now the first thing
boot does, and the rest waits for the unlock. Verified: only `lock_status`
is called before the passcode is accepted.

### Fixed — inconsistent corner rounding

Radii had drifted to 13 different ad-hoc values (6, 7, 8, 9, 10, 12, 13,
14px and more), which read as sloppy across the settings panels. Everything
now snaps to a four-step scale — `--radius-sm/md/lg/xl` — with pills and
circles deliberately left alone.

### Fixed — download location was not saved

Picking a folder only filled in the field; the choice was lost on restart.
It is now written to `settings.json` immediately, whether picked from the
folder dialog or typed directly, and both folder fields stay in sync.

### Testing

- 307 offline tests plus 17 live-site tests

## v1.4.0 — Chapter-range filenames, moved-folder recovery, chapter filters

### Changed — files are named by the chapters they contain

A "download all" archive was previously just `Naruto.cbz`, which said nothing
about what was inside. Output files now carry their chapter range:

    Naruto - Chapters 001-050.cbz      one file for everything
    Naruto - Chapters 011-020.cbz      bundled by 10
    Naruto - Chapter 007.cbz           one file per chapter

Non-contiguous selections collapse into runs (`001-003, 007-008, 020`), half
chapters stay inside a run (10, 10.5, 11 -> `010-011`), and a heavily
fragmented pick truncates to `001-013 (7 chapters)` so the filename cannot
grow unbounded. Two new placeholders, `{chapters}` and `{count}`, are
available in the naming templates.

Anyone carrying the old `{title}` template from a previous version is
migrated forward automatically — otherwise the stored value would keep
overriding the new default. Custom templates are left alone.

### Added — moved your downloads? nothing breaks

Moving a downloads folder used to orphan every library entry silently. Now:

- **Check library** reports entries whose folder or files have gone
- **Find moved folders** proposes matches by folder name. Proposals are
  inert until you confirm, so a wrong guess cannot rewrite anything
- **Pick new downloads folder** adopts a new root, saves it to settings and
  re-links everything under it in one step
- Re-linking rewrites the directory *and* each output path, and preserves
  download history, title and source
- New **Moved files** panel in Tools, plus
  `readerm library verify|scan|move`

### Added — chapter min/max and sorting

The chapter list gained a minimum and maximum chapter number, a name filter,
newest/oldest sorting, and a "hide downloaded" toggle. The count pill shows
`visible / total` and a note reports how many rows a filter is hiding.

Filtering only changes what is displayed — selections are keyed by the real
chapter index, so hiding a row never silently drops it from a selection. The
bulk buttons deliberately act on *visible* chapters only: selecting rows you
have filtered out would mean downloading things you cannot see. "Latest" now
picks the highest-numbered visible chapter rather than the last array entry.

### Fixed

- The Tools tab's new panel did not load when its tab was clicked: the loader
  was wired into the view switcher but not the tool-tab handler.

### Testing

- 285 offline tests plus 17 live-site tests

## v1.3.0 — Three new sources, and the source toggles actually work

### Fixed — no way to turn a source off

The toggle existed but was invisible. The CSS targeted `.switch .track`
while most of the markup emits a bare `<span>` with no class, so **no rule
matched** and every switch in the app rendered zero-width. Measured before
the fix: `width: 0`, `matchesTrackRule: false`.

The markup was also inconsistent — 5 switches used `class="track"`, 7 did
not — so the CSS now matches both variants and the markup is normalised to
one shape. All 12 switches verified at 46x26.

Two related contrast problems went with it: the off-state track was almost
the same colour as the row behind it, and dimming a disabled row also dimmed
the control needed to re-enable it.

### Fixed — content filter inputs unstyled

The blocked-tags and blocked-titles fields matched no CSS rule at all, so
they fell back to the browser default: white background, black text, inset
border, Arial. Unreadable on every dark theme. Settings text, number and
password inputs are now themed, with a focus ring.

### Added — three sources

- **Omega Scans** (`omegascans`) — JSON API. Chapters come from
  `/chapter/query?series_id=`, not the series record, whose `seasons` array
  is always empty. Coin-locked chapters (`price > 0`) serve no images, so
  they are skipped rather than "downloaded" empty.
- **ManhwaRead** (`manhwaread`) — the reader renders pages as `blob:` URLs,
  so scraping `<img src>` yields nothing. The real list is base64 JSON in a
  `var chapterData` block. Its CDN also answers **403** without a Referer,
  so chapters carry one explicitly.
- **Manhwa18** (`manhwa18`) — **adult only.** Results are tagged
  `pornographic` so the existing Safe mode filter removes them, and the
  source shows an `18+` chip in Settings.

Verified end-to-end: all three search, list chapters and download real CBZ
files with zero empty pages.

### Cover art research

Unlike MangaDex, all three new CDNs return identical bytes with or without a
Referer, so no placeholder-swap workaround is needed for them. ManhwaRead's
page CDN is the exception and is handled per-chapter.

### Testing

- 254 offline tests plus 17 live-site tests
- Tests that hardcoded "4 sources" now count the registry, so adding a
  source no longer breaks them

## v1.2.0 — New GUI tabs and a GitHub-style landing page

### Added — three new GUI tabs

Nine backend features had no interface at all. They now do:

- **Updates** — the watchlist, with per-series new-chapter counts, a rail
  badge, and a "Check now" button that queries every source in parallel. A
  Watch button on the manga page feeds it.
- **Insights** — six headline metrics, a per-source bar chart, a fourteen-day
  activity sparkline, and biggest/most-recent series lists.
- **Tools** — five sub-panels: disk usage per series, SHA-256 duplicate
  scanning with a wasted-space total, orphan detection, live circuit-breaker
  health, and a clickable search history.

Every new view goes through a `callApi` wrapper, so a missing endpoint or a
Python-side exception logs a warning instead of blanking the tab.

### Added — GitHub-style landing page

`docs/index.html` is rebuilt on Primer design tokens as a repository page:
file listing, README pane, sidebar with topics, releases and a language
breakdown. Five deep-linkable tabs (Code, Features, Screenshots, CLI,
Sources) with working browser back/forward, real light and dark modes
remembered in localStorage, a screenshot gallery, and copy-to-clipboard
install commands.

The numbers on the page are computed from the repository — 228 features, 4
sources, the language split and the version badge. Star and fork counts were
deliberately left out: a static page cannot know them, and inventing them
would present made-up figures as fact.

### Fixed

- Bar chart fills rendered as empty tracks: `<span>` is `display: inline` by
  default, so width and height were ignored.
- Landing-page tabs did not respond to same-document hash changes, so
  in-page links and browser back/forward did nothing.

### Testing

- 241 offline tests plus 14 live-site tests

## v1.1.0 — Cover, crash, search and performance fixes

### Fixed — MangaDex covers showed a placeholder

MangaDex serves a "You can read this at MangaDex" graphic instead of the real
artwork when the `Referer` is a `file://` URL, which is exactly what the
packaged GUI loads from. Measured against the live CDN: a 59,480-byte
placeholder (600x642) in place of the 143,403-byte cover (512x728). The page
now sends `<meta name="referrer" content="no-referrer">`, which restores the
real artwork. The URLs were never wrong — every one returned HTTP 200.

### Fixed — freeze and crash 0xCFFFFFFF during downloads

The engine emitted one progress event per downloaded image, and each event
became its own `evaluate_js` call: a JSON dump interpolated into a JS string
and marshalled across the native bridge. A 700-chapter job at ~60 pages each
is over 43,000 bridge crossings, which pins a core and takes WebView2 down
with `0xCFFFFFFF`.

Progress events are now coalesced per chapter and flushed on a 120 ms timer as
a single batch, while lifecycle events (start, done, packaged, finished) are
never dropped and terminal events flush immediately. Measured on the crash
scenario: 2,480 events became **one** bridge call.

### Fixed — search results not loading

Startup was a chain of unguarded `await` calls. A single rejecting bridge call
threw out of the whole handler, so everything after it silently never ran —
including the initial trending load. Reproduced: one failing endpoint left
**zero** results rendered. Each startup step is now isolated, so a failure is
logged and the rest still runs; the same scenario now renders results
normally.

### Changed — lower resource usage

- Images stream to disk in 64 KB chunks instead of being buffered whole in
  memory, which previously meant dozens of multi-MB blobs resident at once
- One shared image thread pool per job, replacing a new pool per chapter on
  top of the chapter pool; in-flight requests are capped at 16
- Background dot matrix: capped to 30 fps, dot count bounded, device pixel
  ratio clamped, resize debounced, and it now pauses when the window is
  hidden or the lock screen is up
- The dot colour is cached per theme rather than read via `getComputedStyle`
  on every animation frame, which was forcing a style recalc 60 times a second
- Flush timer, cached sessions and sockets are released when the window closes

### Added — interface polish

- Skeleton placeholder tiles while a search is in flight, replacing a bare
  spinner
- Covers reserve their aspect ratio up front, so the grid no longer reflows as
  each image decodes, and fade in once decoded
- Series with a missing or broken cover get a titled fallback tile instead of
  an empty gap
- Empty and error states now explain what happened and offer recovery actions
  (Retry, Clear genre, Show trending)
- Reduced-motion preferences are respected throughout

### Testing

- 211 offline tests plus 14 live-site tests

## v1.0.0 — Multi-source ReaderM

The first release of the fork under its own name. ReaderM downloads manga from
four sites through a pluggable source layer, with a CLI, a full-screen TUI and
a desktop GUI sharing the same engine.

### Sources

- **MangaDex** via the official JSON API — languages, scanlation groups,
  data-saver mode, correct cover art in three sizes, per-volume covers
- **Mangakatana** — HTML scraping, including its obfuscated JavaScript page
  arrays
- **Natomanga** (Manganato / Mangakakalot successor) — HTML plus the site's
  JSON chapter endpoint
- **Weeb Central** — the original source, with FlareSolverr fallback
- The source is detected automatically from any pasted URL; `-s/--source`
  forces one
- Cross-source search fans out in parallel and merges the results
- Adding a site is one file in `readerm/sources/` plus one registry line

### Discovery: trending and genres

- **Pressing Search with an empty box shows trending titles** instead of doing
  nothing — the GUI, TUI and CLI all open on a discovery feed
- Genre browsing and genre-filtered search on every source
- 99 genres merged across sites, deduplicated case-insensitively, ordered by
  how widely each one is supported
- Quick-pick genre chips in the GUI, a genre dropdown in the TUI
- Trending results interleave sources so the first screen shows a mix
- `Load more` pagination in the GUI
- Type-ahead search suggestions drawn from your history
- `readerm trending [genre]`, `readerm genres`, `readerm search -g <genre>`

### Robust calling

- Circuit breaker per source: a site that fails repeatedly is skipped
  instantly instead of costing a full timeout on every request, then probed
  again after an escalating cooldown
- Bounded retries with exponential backoff and jitter, and a `retry_if` hook
  so hopeless failures (404s) are not retried
- TTL caches for discovery listings and genre lists — repeat browsing is
  served from memory
- `gather()` runs many calls in parallel and keeps whatever succeeds
- Rate-limit headers (`Retry-After`, `X-RateLimit-Retry-After`) are honoured
- One dead site can never break a search, a browse or a genre listing
- `readerm health` reports breaker state and cache hit rates

### Provider attribution

- The site a manga came from is shown **directly beneath its title**, with a
  coloured dot and a link back to the original page
- Provider shown in the GUI, the TUI and `readerm info`
- Source badges on GUI result cards, a source column in CLI results
- Source recorded on library entries, bookmarks and download results

### Source ranking and exclusion

- Drag-and-drop source ranking in GUI settings, with move up/down buttons
- Ranking decides which copy wins when a series exists on several sites
- Exclude a source entirely, or only from multi-source search
- Excluded sources still work from a direct URL, so a shared link never breaks
- Per-source limit, weight, language and delay overrides
- Sources tab in the TUI, and `readerm config` in the terminal

### Passcode lock

- Optional app passcode: PBKDF2-HMAC-SHA256, 240,000 rounds, per-install
  random salt, constant-time comparison
- The passcode is never stored in plaintext
- One-time recovery key, attempt throttling with escalating cooldown,
  auto-lock on idle, lock on start, optional cover blurring and a hint
- Full-screen lock overlay in the GUI with a built-in recovery flow
- Gates the interface only — downloaded files remain readable on disk

### Tracking

- Per-chapter read state, progress percentages and next-unread jump
- Watchlist with parallel update checking across every watched series
- Free-text notes and 0–5 star ratings

### Library and maintenance

- Search history with suggestions, a persistent download queue, and download
  statistics recorded automatically
- Content filters: blocked tags, titles and authors, safe mode, hide
  cover-less results
- Cross-source duplicate merging that strips decorations such as "(Colored)"
  and reports which other sites carry the same series
- Collections, snapshots, and library import/export as JSON, CSV or Markdown
- Disk usage per series, SHA-256 duplicate scanning with wasted-space totals,
  and orphan detection

### Core engine

- CBZ, PDF, EPUB and raw image output, with multiple formats in one run
- Flexible bundling: one file for everything, per chapter, or per N chapters
- Crash-safe resume with verified checkpoints and atomic image writes
- Parallel chapter and image downloads with configurable workers
- Filename templates with `{title}`, `{chapter}`, `{start}`, `{end}`

### Notable fixes made while building this

- **MangaDex covers**: the thumbnail suffix must follow the *complete*
  filename including its original extension (`abc.png.512.jpg`, not
  `abc.512.jpg`). The naive form returns 404 — the usual cause of missing
  MangaDex cover art
- **Externally hosted MangaDex chapters**: licensed titles on MangaPlus and
  Azuki report `pages: 0` and cannot be downloaded; they are filtered out
  rather than producing empty chapters
- **Mangakatana page arrays**: each chapter ships a decoy single-entry
  JavaScript array alongside the real page list, and both variable names are
  randomised per request, so the longest array is selected
- **Mangakatana listings**: a bare `div.item` selector matches sidebar cards
  that appear before the results grid, which broke pagination; `#book_list`
  now takes precedence
- **Mangakatana browse**: `/manga/page/N` ignores sorting and returns an
  alphabetical dump; the `?filter=1` form is the one the site itself uses
- **Weeb Central genres**: the search route expects `included_tag`, not
  `included_tag[]` — the bracketed form is silently ignored
- Images served as `application/octet-stream` are validated by magic bytes
  instead of being rejected
- Page ordering sorts numerically, so page 10 no longer lands before page 2

### Interface

- **Custom dropdowns** throughout the GUI. Native `<select>` popups are drawn
  by the OS and cannot be themed, so on a dark theme they appeared as bright
  system menus ignoring the accent colour. They are now themed listboxes with
  a type-to-filter box for long lists (the genre list has ~99 entries), full
  keyboard navigation, typeahead and ARIA roles.
- The real `<select>` stays in the DOM as the source of truth, so every
  existing `sel.value` / `innerHTML` / `appendChild` call site keeps working
  and real `change` events still fire.
- Fixed: closed dropdown panels were painted over the page because
  `display:flex` in author CSS overrides the user-agent `[hidden]` rule.
- Fixed: the GUI hero still carried the old pre-fork product name; it was split across
  `<span>`s so the rename missed it.

### Testing

- 182 offline tests plus 14 live-site tests behind `READERM_NETWORK_TESTS=1`
- Dropdown behaviour is covered by 27 Playwright tests driving real headless
  Chromium, since DOM, pointer and keyboard behaviour cannot be asserted from
  Python alone. They skip automatically when Playwright is unavailable.

### Not included

- **Comick** was evaluated and deliberately left out. Its `md_images` array
  comes back empty for every title and request variant tested — direct API,
  `tachiyomi=true`, browser headers and the web reader payload — so chapter
  pages cannot be resolved. Natomanga was added in its place. If Comick
  reopens that endpoint it drops in as a single new source module.
