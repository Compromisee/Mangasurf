# ReaderM — command syntax

Complete reference for the `readerm` command line. Every example here was run
against the real build.

Four ways to drive the same engine:

| | Command | Best for |
|---|---|---|
| **CLI** | `readerm …` | scripting, one-off downloads |
| **Menu** | `readerm menu` | numbered prompts, nothing to memorise |
| **TUI** | `readerm tui` | full-screen terminal app (needs `textual`) |
| **GUI** | `readerm gui` | desktop window (needs `pywebview`) |

---

## Contents

- [The one-line version](#the-one-line-version)
- [Invocation](#invocation)
- [Downloading](#downloading)
  - [Chapter selection](#chapter-selection)
  - [Output format and bundling](#output-format-and-bundling)
  - [Filename templates](#filename-templates)
  - [Speed and politeness](#speed-and-politeness)
- [Searching and discovery](#searching-and-discovery)
- [Sources](#sources)
- [Library, watching and disk](#library-watching-and-disk)
- [Configuration and privacy](#configuration-and-privacy)
- [Colour and progress output](#colour-and-progress-output)
- [Exit codes](#exit-codes)
- [Recipes](#recipes)

---

## The one-line version

```bash
readerm <url>
```

Paste any URL from a supported site. The source is detected, every chapter is
downloaded, and you get one CBZ. Nothing else is required.

---

## Invocation

```
readerm [options] <url>
readerm [options] <command> [arguments]
```

`readerm` is the installed entry point. All three of these are equivalent:

```bash
readerm search "berserk"           # installed script
python -m readerm.cli search "berserk"
py cli.py search "berserk"         # run the file directly, from readerm/
```

Running the files directly works on purpose — every module self-bootstraps its
package. `rich` is optional: without it the CLI still runs and still colours
its output, it just uses a simpler progress bar.

### Commands

| Command | What it does |
|---|---|
| *(a URL)* | download it |
| `search <query>` | search every enabled source at once |
| `info <url>` | title, cover, description, chapter count |
| `trending [genre]` | popular titles; alias `browse`, `popular` |
| `genres` | every genre, merged across sources |
| `sources` | list supported sites and capabilities |
| `config …` | enable, disable and rank sources |
| `library …` | verify, relocate and re-link downloads |
| `watch …` | track series for new chapters |
| `disk …` | usage, duplicates, orphaned files |
| `stats` | download statistics |
| `history` | recent searches |
| `lock …` | app passcode |
| `export <file>` | export the library |
| `health` | circuit-breaker state and cache hit rates |
| `resume` | resume an interrupted download |
| `menu` / `tui` / `gui` | launch an interface |

---

## Downloading

```bash
readerm https://mangadex.org/title/<uuid>
readerm https://asuracomic.net/series/emperor-of-solo-play
readerm https://witchscans.com/manga/afterlife-diner/
```

A bare MangaDex UUID also works:

```bash
readerm a1c7c817-4e59-43b7-9365-09675a149a6f
```

### Chapter selection

`-c` / `--chapters` (default `all`):

| Value | Meaning |
|---|---|
| `all` | every chapter (default) |
| `5` | just chapter 5 |
| `1-20` | chapters 1 through 20 |
| `1,5,10-20` | mix single chapters and ranges |
| `50-` | chapter 50 to the end |
| `latest` | the newest chapter only |
| `first` | the oldest chapter only |

```bash
readerm <url> -c latest
readerm <url> -c 1,5,10-20
readerm <url> -c 50-
```

### Output format and bundling

```bash
readerm <url> -f cbz          # default
readerm <url> -f pdf
readerm <url> -f epub
readerm <url> -f images       # loose image files, no archive
```

`--per N` controls how chapters are grouped into files:

| Flag | Result |
|---|---|
| `--per 0` | everything in one file (default) |
| `--per 1` | one file per chapter |
| `--per 10` | one file per ten chapters |

```bash
readerm <url> --per 10                 # one CBZ per 10 chapters
readerm <url> -c 1-50 -f pdf           # chapters 1-50 as a single PDF
readerm <url> --also epub              # CBZ *and* EPUB (repeatable)
readerm <url> -f cbz --keep-images     # keep the raw pages too
readerm <url> -o ~/Manga               # choose the output directory
```

### Filename templates

| Flag | Applies to | Default |
|---|---|---|
| `--name-single` | one-file bundles | `{title} - Chapters {chapters}` |
| `--name-chapter` | `--per 1` output | per-chapter name |
| `--name-range` | `--per N` output | chapter-range name |

Placeholders: `{title}`, `{chapters}`, `{chapter}`, `{source}`, `{start}`,
`{end}`.

```bash
readerm <url> --per 1 --name-chapter "{title} Ch.{chapter}"
```

### Speed and politeness

| Flag | Default | Range |
|---|---|---|
| `-w`, `--workers` | 3 | 1–8 concurrent chapters |
| `--image-workers` | 6 | 1–10 concurrent pages per chapter |
| `--delay` | 0.5 | seconds between chapters |

```bash
readerm <url> -w 6 --image-workers 10     # faster, heavier on the site
readerm <url> -w 1 --delay 2              # gentle
```

Please leave the defaults alone unless you have a reason. They are set to be
polite to sites that are mostly run by volunteers.

### Other download flags

```bash
readerm <url> -y            # skip the confirmation prompt
readerm <url> --plain       # plain log lines, no progress UI (good for cron)
readerm resume              # resume whatever was interrupted
```

---

## Searching and discovery

```bash
readerm search "one piece"              # every enabled source, in parallel
readerm search "berserk" -s mangadex    # one source
readerm search                          # no query -> trending
```

### Filters

| Flag | Values | Notes |
|---|---|---|
| `--type` | `manga`, `manhwa`, `manhua`, `comic`, `novel`, `any` | lowercase |
| `--status` | `Ongoing`, `Completed`, … | |
| `-g`, `--genre` | any name from `readerm genres` | comma-separate for several |
| `-n`, `--limit` | a number | results **per source** |
| `--sort` | `title`, `source`, `chapters`, `year` | |
| `--reverse` | | flip the sort |

`--type` is *derived*, not requested: almost no site accepts a type filter, so
ReaderM infers it from the origin language and tags. Results whose type cannot
be determined are **kept** — dropping them would erase whole sources from a
filtered search.

```bash
readerm search "solo" --type manhwa
readerm search "one piece" --status Ongoing
readerm search "blue" -g Romance
readerm search "blue" -g "Romance,Comedy"
readerm search "berserk" --sort chapters --reverse
```

### Output modes

```bash
readerm search "blue" --json      # machine-readable
readerm search "blue" --urls      # URLs only, one per line
```

`--urls` is built for pipes:

```bash
readerm search "murim" --type manhwa --urls | head -3 | xargs -n1 readerm -c 1
```

### Acting on a result

```bash
readerm search "berserk" --open 1        # show details for result 1
readerm search "berserk" --download 1    # download result 1
```

### Browsing

```bash
readerm trending                  # popular across every source
readerm trending romance          # popular in one genre
readerm trending -s mangadex      # one source
readerm genres                    # every genre and who offers it
readerm info <url>                # details for one series
```

---

## Sources

```bash
readerm sources                   # every site, with capabilities
```

Force one with `-s`:

```bash
readerm search "naruto" -s natomanga
```

MangaDex-only options:

```bash
readerm <url> -l fr                       # translation language
readerm <url> --scanlator "Group Name"    # preferred group
readerm <url> --data-saver                # smaller, compressed pages
```

### Enabling, disabling and ranking

Rank decides which copy wins when a series exists on several sites; lower is
better.

```bash
readerm config                                  # show the table
readerm config disable natomanga                # skip it everywhere but URLs
readerm config enable natomanga
readerm config up mangakatana                   # move up one place
readerm config down mangakatana
readerm config rank mangadex asurascans flamecomics    # set the order outright
readerm config reset
```

A **disabled** source is skipped everywhere except direct URLs, so a link
someone sends you still works.

### Cloudflare

Weeb Central and Setsu Scans sit behind Cloudflare and need
[FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) on
`localhost:8191`. Without it they fail in milliseconds and the rest of your
search continues — they will not hold it up.

---

## Library, watching and disk

```bash
readerm library                      # verify every entry resolves on disk
readerm library verify
readerm library scan ~/Manga         # re-link folders you moved
readerm library move <url> <folder>  # relocate one series
readerm export out.json              # or: out.csv / out.md
```

```bash
readerm watch add <url>              # track a series
readerm watch list
readerm watch check                  # check everything for new chapters
readerm watch remove <url>
```

```bash
readerm disk usage                   # size per series
readerm disk dupes                   # duplicate files
readerm disk orphans                 # files with no library entry
readerm stats
readerm health                       # breaker state, cache hit rates
```

---

## Configuration and privacy

Everything lives in `~/.readerm/`:

| File | Contents |
|---|---|
| `config.json` | settings **and** per-source config, written atomically |
| `library.json` | what you have downloaded |
| `logs/` | rotating logs |

```bash
readerm lock status
readerm lock set        # set a passcode
readerm lock change
readerm lock off
readerm history         # recent searches
```

---

## Colour and progress output

Colour is on when the output is a terminal and off when piped, so redirecting
to a file never produces escape-code soup.

| Variable | Effect |
|---|---|
| `NO_COLOR=1` | never colour |
| `FORCE_COLOR=1` | colour even when piped |
| `CLICOLOR_FORCE=1` | same as `FORCE_COLOR` |
| `TERM=dumb` | never colour |

```bash
NO_COLOR=1 readerm sources
FORCE_COLOR=1 readerm search "blue" | less -R
readerm <url> --plain            # no progress bar at all; one line per event
```

On Windows, ANSI is enabled through the console API automatically. Windows 10
1511 and newer show colour; older hosts fall back to plain text rather than
printing raw escape codes.

With `rich` installed you get a spinner, a bar, `done/total`, a percentage,
elapsed time and an ETA. Without it you get a single-line bar with the same
counts. Use `--plain` in cron jobs and CI.

---

## Rebuilding CBZ covers

```bash
readerm covers --dry-run           # show the plan, change nothing
readerm covers                     # rebuild, taking the best-ranked cover
readerm covers -o ~/Manga          # scan any folder you like
readerm covers -o ~/Manga --sort-only   # just split a flat folder by series
readerm covers --replace           # replace covers that already exist
```

Walks the tree, works out the series behind each `.cbz` from its filename
(stripping `Chapters 001-050`, `[Group]`, `v03`, `c045` and the rest), searches
every enabled source, and writes `cover.jpg` **next to that archive**.

Where several different series sit loose in one folder, each is moved into a
folder of its own first — otherwise a single `cover.jpg` there would be wrong
for all but one of them. A folder that already holds one series is left alone.

Filename styles understood include `Chapters 001-050`, `Ch.001-036`,
`Chs.001-036`, `Chapt. 5`, `Cap.12`, `c045`, `v03`, `#12`, `Episode 200`,
`[Group]` prefixes and `(2024)` suffixes. Titles that contain a marker word --
Chainsaw Man, Case Closed, Cells at Work -- survive intact, because a marker
only counts when a number follows it.

**Smart search** (the GUI button, and what `readerm covers` now does) picks
for you: exact title match first, then your **source ranking from Settings**,
then image size so it never settles for a list thumbnail. Measured across
three titles, the top-ranked candidate was 6-15x smaller in pixels than the
best available, which is why size is considered at all — but between two real
covers your ranking still wins.

The GUI version (**Tools → Rebuild covers**) adds a **Choose folder** button so
you can point it anywhere, and a **Sort into folders** button that splits a
flat folder without downloading anything. It shows candidates as thumbnails so
you can pick; the CLI takes the best-ranked match, since a terminal cannot
show them.

## Background mode

With **Settings → Background → Minimise to system tray** enabled, closing the
window hides it and downloads carry on. The tray icon's context menu shows:

* current transfer rate and ETA
* chapters remaining and how many jobs are queued
* one line per running download
* **Open ReaderM** to bring the window back, **Pause queue**, and **Quit**

The tray needs an optional dependency and a desktop session:

```bash
pip install "readerm[tray]"
```

Without it the toggle is disabled and explains why; the window keeps its
ordinary close-quits behaviour.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | failure — nothing found, bad URL, download failed |
| `130` | cancelled with Ctrl-C |

```bash
readerm <url> -y || echo "download failed"
```

---

## Recipes

**Grab only what is new, quietly, from cron**

```bash
readerm watch check --plain
```

**One file per chapter, into a per-series folder**

```bash
readerm <url> --per 1 -o ~/Manga
```

**Everything a source has for one genre, as URLs**

```bash
readerm trending romance -s toonily --urls
```

**Search, pick, download in one line**

```bash
readerm search "solo leveling" --type manhwa --download 1 -y
```

**Mirror a series as both CBZ and EPUB**

```bash
readerm <url> -f cbz --also epub
```

**Slow, polite full-series archive**

```bash
readerm <url> -w 1 --delay 2 --per 25 -o ~/Archive
```

**Check what a URL is before committing**

```bash
readerm info <url>
```

---

## See also

- [`README.md`](../README.md) — install, features, source table
- `python landing.py` — a window to launch any interface
- `python server.py` — serve the interface to your phone
  (add the gui flag for a small control window)
- [`FEATURES.md`](FEATURES.md) — every feature, grouped by what it is for
- [`CHANGELOG.md`](CHANGELOG.md) — what changed, and why
- [`PACKAGING.md`](PACKAGING.md) — building a standalone executable
