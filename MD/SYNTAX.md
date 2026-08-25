# Mangasurf — command syntax

Complete reference for the `mangasurf` command line. Every example here was run
against the real build.

Four ways to drive the same engine:

| | Command | Best for |
|---|---|---|
| **CLI** | `mangasurf …` | scripting, one-off downloads |
| **Menu** | `mangasurf menu` | numbered prompts, nothing to memorise |
| **TUI** | `mangasurf tui` | full-screen terminal app (needs `textual`) |
| **GUI** | `mangasurf gui` | desktop window (needs `pywebview`) |

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
mangasurf <url>
```

Paste any URL from a supported site. The source is detected, every chapter is
downloaded, and you get one CBZ. Nothing else is required.

---

## Invocation

```
mangasurf [options] <url>
mangasurf [options] <command> [arguments]
```

`mangasurf` is the installed entry point. All three of these are equivalent:

```bash
mangasurf search "berserk"           # installed script
python -m mangasurf.cli search "berserk"
py cli.py search "berserk"         # run the file directly, from mangasurf/
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
mangasurf https://mangadex.org/title/<uuid>
mangasurf https://asuracomic.net/series/emperor-of-solo-play
mangasurf https://witchscans.com/manga/afterlife-diner/
```

A bare MangaDex UUID also works:

```bash
mangasurf a1c7c817-4e59-43b7-9365-09675a149a6f
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
mangasurf <url> -c latest
mangasurf <url> -c 1,5,10-20
mangasurf <url> -c 50-
```

### Output format and bundling

```bash
mangasurf <url> -f cbz          # default
mangasurf <url> -f pdf
mangasurf <url> -f epub
mangasurf <url> -f images       # loose image files, no archive
```

`--per N` controls how chapters are grouped into files:

| Flag | Result |
|---|---|
| `--per 0` | everything in one file (default) |
| `--per 1` | one file per chapter |
| `--per 10` | one file per ten chapters |

```bash
mangasurf <url> --per 10                 # one CBZ per 10 chapters
mangasurf <url> -c 1-50 -f pdf           # chapters 1-50 as a single PDF
mangasurf <url> --also epub              # CBZ *and* EPUB (repeatable)
mangasurf <url> -f cbz --keep-images     # keep the raw pages too
mangasurf <url> -o ~/Manga               # choose the output directory
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
mangasurf <url> --per 1 --name-chapter "{title} Ch.{chapter}"
```

### Speed and politeness

| Flag | Default | Range |
|---|---|---|
| `-w`, `--workers` | 3 | 1–8 concurrent chapters |
| `--image-workers` | 6 | 1–10 concurrent pages per chapter |
| `--delay` | 0.5 | seconds between chapters |

```bash
mangasurf <url> -w 6 --image-workers 10     # faster, heavier on the site
mangasurf <url> -w 1 --delay 2              # gentle
```

Please leave the defaults alone unless you have a reason. They are set to be
polite to sites that are mostly run by volunteers.

### Other download flags

```bash
mangasurf <url> -y            # skip the confirmation prompt
mangasurf <url> --plain       # plain log lines, no progress UI (good for cron)
mangasurf resume              # resume whatever was interrupted
```

---

## Searching and discovery

```bash
mangasurf search "one piece"              # every enabled source, in parallel
mangasurf search "berserk" -s mangadex    # one source
mangasurf search                          # no query -> trending
```

### Filters

| Flag | Values | Notes |
|---|---|---|
| `--type` | `manga`, `manhwa`, `manhua`, `comic`, `novel`, `any` | lowercase |
| `--status` | `Ongoing`, `Completed`, … | |
| `-g`, `--genre` | any name from `mangasurf genres` | comma-separate for several |
| `-n`, `--limit` | a number | results **per source** |
| `--sort` | `title`, `source`, `chapters`, `year` | |
| `--reverse` | | flip the sort |

`--type` is *derived*, not requested: almost no site accepts a type filter, so
Mangasurf infers it from the origin language and tags. Results whose type cannot
be determined are **kept** — dropping them would erase whole sources from a
filtered search.

```bash
mangasurf search "solo" --type manhwa
mangasurf search "one piece" --status Ongoing
mangasurf search "blue" -g Romance
mangasurf search "blue" -g "Romance,Comedy"
mangasurf search "berserk" --sort chapters --reverse
```

### Output modes

```bash
mangasurf search "blue" --json      # machine-readable
mangasurf search "blue" --urls      # URLs only, one per line
```

`--urls` is built for pipes:

```bash
mangasurf search "murim" --type manhwa --urls | head -3 | xargs -n1 mangasurf -c 1
```

### Acting on a result

```bash
mangasurf search "berserk" --open 1        # show details for result 1
mangasurf search "berserk" --download 1    # download result 1
```

### Browsing

```bash
mangasurf trending                  # popular across every source
mangasurf trending romance          # popular in one genre
mangasurf trending -s mangadex      # one source
mangasurf genres                    # every genre and who offers it
mangasurf info <url>                # details for one series
```

---

## Sources (32 Registered Scrapers)

```bash
mangasurf sources                   # every site, with capabilities
```

### Supported Scrapers

| Source ID | Name | Primary Domains | Capabilities | Content |
|---|---|---|---|---|
| `mangadex` | MangaDex | `mangadex.org` | Search, Browse, Languages, Scanlators | Manga/Manhwa (SFW) |
| `mangakatana` | Mangakatana | `mangakatana.com` | Search, Browse, Genres | Manga/Manhwa (SFW) |
| `weebcentral` | Weeb Central | `weebcentral.com` | Search, Browse, Series Types | Manga/Manhwa (SFW) |
| `kagane` | Kagane | `kagane.to`, `kstatic.to` | Search, Browse, Genres | Manga/Manhwa (SFW) |
| `comix` | Comix | `comix.to` | Search, Browse, Genres | Manga/Manhwa (SFW) |
| `vymanga` | VyManga | `vymanga.co`, `mangavyvy.net` | Search, Browse, Genres | Manga/Manhwa (SFW) |
| `mangadotnet` | MangaDotNet | `manga.net` | Search, Browse | Manga/Manhwa (SFW) |
| `mangadistrict` | MangaDistrict | `mangadistrict.com` | Search, Browse, Genres | Manhwa/Webtoons (SFW) |
| `hitomi` | Hitomi.la | `hitomi.la`, `gold-usergeneratedcontent.net` | Search, Browse, Nozomi binary index | Doujinshi/Hentai (18+) |
| `simplyhentai` | Simply-Hentai | `simply-hentai.com` | Search, Multi-tag combinations | Hentai (18+) |
| `natomanga` | Natomanga | `natomanga.com` | Search, Browse | Manga/Manhwa (SFW) |
| `asurascans` | Asura Scans | `asuracomic.net` | Search, Browse | Manhwa/Action (SFW) |
| `flamecomics` | Flame Comics | `flamecomics.me` | Search, Browse | Manhwa/Action (SFW) |
| `demonicscans` | Demonic Scans | `demonicscans.org` | Search, Browse | Manhwa/Action (SFW) |
| `madarascans` | Madara Scans | `madarascans.com` | Search, Browse | Manhwa/Webtoons (SFW) |
| `omegascans` | Omega Scans | `omegascans.org` | Search, Browse | Manhwa/Webtoons (SFW) |
| `manhwaread` | ManhwaRead | `manhwaread.com` | Search, Browse | Manhwa/Webtoons (SFW) |
| `madaranet` | Madara Network | Aggregate | Search, Browse | Manhwa/Webtoons (SFW) |
| `witchscans` | Witchtoons | `witchtoons.net`, `witchscans.com` | Search, Browse, RSS feeds | Manhua/Webtoons (SFW) |
| `writerscans` | WriterScans | `writerscans.com` | Search, Browse | Manhwa/Action (SFW) |
| `webtoons` | Webtoons | `webtoons.com` | Search, Browse | Official Webtoons (SFW) |
| `mangadass` | Mangadass | `mangadass.com` | Search, Browse | Manga/Manhwa (SFW) |
| `manhwa18` | Manhwa18 | `manhwa18.com` | Search, Browse | Adult Manhwa (18+) |
| `manga18club` | Manga18Club | `manga18.club` | Search, Browse | Adult Manhwa (18+) |
| `mewhen18` | Mewhen18 | `mewhen18.com` | Search, Browse | Hentai (18+) |
| `nhentai` | nhentai | `nhentai.to` | Search, Tag routing | Doujinshi/Hentai (18+) |
| `chikari` | Chikari | `chikari.moe` | Search, Browse, Lists, Tag IDs | Manhwa (SFW + 18+) |
| `kuramanga` | KuraManga | `kuramanga.com`, `shadowabyss.com` | Search, Browse, Infinite IDs | Manhwa (SFW) |
| `kurahentai` | KuraHentai | `kurahentai.com`, `shadowabyss.com` | Search, Browse, Supabase REST | Doujinshi/Hentai (18+) |
| `hiperdex` | Hiperdex | `hiperdex.com`, `r2d2storage.com` | Search, Browse, tRPC API | Adult Manhwa (18+) |
| `madaradex` | MadaraDex | `madaradex.org` | Search, Browse | Adult Manhwa (18+) |
| `mangak` | MangaK | `mangak.io`, `resmk.org` | Search, Browse, SSR Props | Manhwa (SFW) |

Force one with `-s`:

```bash
mangasurf search "naruto" -s natomanga
mangasurf search "solo" -s chikari
```

### Curated List Bulk Downloading

Download all chapters from every manga in a curated list with a single command:

```bash
mangasurf https://chikari.moe/lists/461-my-manhwa-list
```

### Phone Server & OPDS Catalog

```bash
mangasurf server                            # LAN Web reader on :8577
mangasurf server --port 9000 --gui          # with small control window
mangasurf server --no-auth                  # trusted networks only

mangasurf opds                              # OPDS 1.2 catalog on :8578
mangasurf opds --port 9001 --gui            # with control window
```

MangaDex-only options:

```bash
mangasurf <url> -l fr                       # translation language
mangasurf <url> --scanlator "Group Name"    # preferred group
mangasurf <url> --data-saver                # smaller, compressed pages
```

### Enabling, disabling and ranking

Rank decides which copy wins when a series exists on several sites; lower is
better.

```bash
mangasurf config                                  # show the table
mangasurf config disable natomanga                # skip it everywhere but URLs
mangasurf config enable natomanga
mangasurf config up mangakatana                   # move up one place
mangasurf config down mangakatana
mangasurf config rank mangadex asurascans chikari # set the order outright
mangasurf config reset
```

A **disabled** source is skipped everywhere except direct URLs, so a link
someone sends you still works.

### Cloudflare & FlareSolverr

Sources with Cloudflare Turnstile bot protection automatically route challenges
through [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) on
`http://localhost:8191/v1`. Start FlareSolverr in the background or configure
its endpoint under **Settings › Sources & FlareSolverr**.

---

## Library, watching and disk

```bash
mangasurf library                      # verify every entry resolves on disk
mangasurf library verify
mangasurf library scan ~/Manga         # re-link and index monitored folder
mangasurf library metadata             # generate and sync manga.json metadata files
mangasurf library relocate             # update moved directories without losing progress
```s you moved
mangasurf library move <url> <folder>  # relocate one series
mangasurf export out.json              # or: out.csv / out.md
```

```bash
mangasurf watch add <url>              # track a series
mangasurf watch list
mangasurf watch check                  # check everything for new chapters
mangasurf watch remove <url>
```

```bash
mangasurf disk usage                   # size per series
mangasurf disk dupes                   # duplicate files
mangasurf disk orphans                 # files with no library entry
mangasurf stats
mangasurf health                       # breaker state, cache hit rates
```

---

## Configuration and privacy

Everything lives in `~/.mangasurf/`:

| File | Contents |
|---|---|
| `config.json` | settings **and** per-source config, written atomically |
| `library.json` | what you have downloaded |
| `logs/` | rotating logs |

```bash
mangasurf lock status
mangasurf lock set        # set a passcode
mangasurf lock change
mangasurf lock off
mangasurf history         # recent searches
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
NO_COLOR=1 mangasurf sources
FORCE_COLOR=1 mangasurf search "blue" | less -R
mangasurf <url> --plain            # no progress bar at all; one line per event
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
mangasurf covers --dry-run           # show the plan, change nothing
mangasurf covers                     # rebuild, taking the best-ranked cover
mangasurf covers -o ~/Manga          # scan any folder you like
mangasurf covers -o ~/Manga --sort-only   # just split a flat folder by series
mangasurf covers --replace           # replace covers that already exist
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

**Smart search** (the GUI button, and what `mangasurf covers` now does) picks
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
* **Open Mangasurf** to bring the window back, **Pause queue**, and **Quit**

The tray needs an optional dependency and a desktop session:

```bash
pip install "mangasurf[tray]"
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
mangasurf <url> -y || echo "download failed"
```

---

## Recipes

**Grab only what is new, quietly, from cron**

```bash
mangasurf watch check --plain
```

**One file per chapter, into a per-series folder**

```bash
mangasurf <url> --per 1 -o ~/Manga
```

**Everything a source has for one genre, as URLs**

```bash
mangasurf trending romance -s toonily --urls
```

**Search, pick, download in one line**

```bash
mangasurf search "solo leveling" --type manhwa --download 1 -y
```

**Mirror a series as both CBZ and EPUB**

```bash
mangasurf <url> -f cbz --also epub
```

**Slow, polite full-series archive**

```bash
mangasurf <url> -w 1 --delay 2 --per 25 -o ~/Archive
```

**Check what a URL is before committing**

```bash
mangasurf info <url>
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
