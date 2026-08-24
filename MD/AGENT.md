# AGENT.md — reading a Mangasurf install from another program

This file is for anything that is **not** Mangasurf and wants to know what a
Mangasurf install contains: another reader, a sync script, a launcher, a shell
one-liner, an AI agent.

The short version: start the server, `GET /local/info`, and follow the
`endpoints` map it returns. Everything under `/local` is read-only.

---

## 1. What this API is for

A second reader should be able to answer questions like

* where are the downloaded files?
* which cover belongs to which series?
* how far through is the user, and when did they last read it?
* which sources does this build support?

…without importing Mangasurf, without parsing its private JSON, and without
guessing at paths that differ per platform.

**It is read only.** No endpoint writes, deletes, downloads or starts a job.
Nothing you do here can damage a library. If you need to *act* on the app,
that is the RPC bridge (`POST /api/<method>`), which is a different and much
sharper tool — see §7.

---

## 2. Starting the server

```bash
python -m mangasurf.server                 # http://<this-pc>:8577
python -m mangasurf.server --port 9000
python -m mangasurf.server --host 127.0.0.1    # this machine only
python -m mangasurf.server --no-auth           # no token, local dev only
```

On start it prints the URL and an access token.

### The token

Every request must carry it, either way:

```bash
curl "http://127.0.0.1:8577/local/info?token=THE_TOKEN"
curl -H "X-Mangasurf-Token: THE_TOKEN" http://127.0.0.1:8577/local/info
```

It is a shared secret over plain HTTP. It stops another user on the same
network poking at your library; it is not authentication and this must never
be port-forwarded to the internet.

### No server, no problem

The same data is available without HTTP:

```bash
python -m mangasurf api info
python -m mangasurf api books
python -m mangasurf api reading
```

and in-process:

```python
from mangasurf import localapi
localapi.info()            # dict
localapi.books()           # list[dict]
localapi.dump("reading")   # JSON string
```

---

## 3. Start here: `GET /local/info`

One call that describes the whole install and **names every other
endpoint**, so you can discover the API from the API rather than from this
file, which can go stale.

```jsonc
{
  "ok": true,
  "app": "Mangasurf",
  "version": "1.0.1",
  "api_version": 1,
  "generated": "2026-08-04T07:12:28",
  "platform": { "system": "Windows", "release": "11", "python": "3.12.4" },
  "paths":  { "...": "see /local/paths" },
  "stats":  { "...": "see /local/stats" },
  "endpoints": {
    "info":     "GET /local/info",
    "paths":    "GET /local/paths",
    "books":    "GET /local/books?chapters=1",
    "reading":  "GET /local/reading",
    "covers":   "GET /local/covers",
    "sources":  "GET /local/sources",
    "shelves":  "GET /local/shelves",
    "stats":    "GET /local/stats",
    "page":     "GET /stream/page?path=<absolute>",
    "book":     "GET /stream/book?path=<absolute>"
  },
  "notes": ["..."]
}
```

`api_version` is bumped **only** when an existing field changes meaning. New
fields may appear at any time — ignore what you do not recognise.

---

## 4. The endpoints

Every response is a JSON **object** with `ok`. List endpoints wrap their list
under a key named after the endpoint, plus a `count`:

```jsonc
{ "ok": true, "books": [ ... ], "count": 12 }
```

A top-level JSON array is deliberately avoided: it cannot gain a field later
without breaking consumers.

### `/local/paths` — where the files are

```jsonc
{
  "ok": true,
  "data_dir": "/home/you/.mangasurf",
  "download_dir": "/home/you/Downloads/Manga",
  "files": {
    "library":   { "path": "/home/you/.mangasurf/library.json",
                   "exists": true, "bytes": 48211,
                   "modified": "2026-08-04T06:55:01" },
    "reading":   { "path": "...", "exists": true,  "...": "..." },
    "shelves":   { "path": "...", "exists": false, "...": "..." },
    "settings":  { "path": "...", "...": "..." },
    "tracking":  { "path": "...", "...": "..." },
    "annotations": { "...": "..." },
    "bookmarks":   { "...": "..." },
    "bookmark_folders": { "...": "..." },
    "lock":        { "...": "..." }
  }
}
```

The stat block lets you tell "not created yet" from "empty" without opening
anything. `download_dir` is `""` when the user has never set one.

### `/local/books` — the library

```jsonc
{ "ok": true, "count": 2, "books": [
  {
    "key": "mangadex.org/title/abc",     // stable id; use this, not the title
    "title": "Dorm Room Sisters",
    "url": "https://mangadex.org/title/abc",
    "source": "mangadex",
    "directory": "/home/you/Downloads/Manga/Dorm Room Sisters",
    "cover": "/home/you/Downloads/Manga/Dorm Room Sisters/cover.jpg",
    "chapter_count": 94,
    "outputs": ["/home/you/.../Dorm Room Sisters/Ch 1-94.cbz"],
    "added": "2026-01-02 11:04:00",
    "last_download": "2026-08-01 22:13:40",
    "shelf": "ongoing"                   // "" when unfiled
  }
] }
```

Add `?chapters=1` for a `chapters` array per series. It is omitted by default
because a 900-chapter series is a lot of JSON for someone who only wanted the
folder path.

`key` is the identity to store. Titles change; a user can relocate a
download and the directory changes with it.

### `/local/reading` — positions

One entry per **file**, newest first, so a 90-chapter series can have 90
entries. Files that no longer exist are dropped.

```jsonc
{ "ok": true, "count": 1, "reading": [
  { "path": "/home/you/.../Ch 12.cbz",
    "page": 8, "pages": 22,
    "fraction": 0.3182, "percent": 32,
    "finished": false,
    "mode": "webtoon",
    "title": "Dorm Room Sisters",
    "at": "2026-08-03 23:41:07" }
] }
```

`fraction` is measured in **pages consumed**, not scroll pixels, so it is
stable while a chapter is still loading. `finished` is `index >= total - 1`.

### `/local/covers`

`{ key, title, cover }` for every series with artwork on disk. Falls back to
a `cover.*` file inside the series folder when the library has no explicit
one. Fetch the bytes with `/stream/page?path=<cover>`.

### `/local/sources`

Every download source this build ships: `id`, `name`, `base_url`,
`adult_only`, `needs_flaresolverr`, `supports_language`.

### `/local/shelves`

The shelf tree, nested via `children`. A locked shelf reports
`"locked": true` and **empty** `books`/`children`, but keeps an honest
`book_count` so you can render "12 hidden".

### `/local/stats`

`series`, `chapters`, `packaged_files`, `in_progress`, `finished`,
`shelves`, `locked_shelves`.

---

## 5. Reading the actual bytes

```
GET /stream/page?path=<absolute path>     # one image
GET /stream/book?path=<absolute path>     # .cbz / .epub / .pdf
```

Both honour `Range`, which is what lets you seek inside a CBZ instead of
downloading 88 MB before the first page appears:

```bash
curl -H "Range: bytes=0-99"  ".../stream/book?path=/books/A.cbz"   # 206
curl -H "Range: bytes=-50"   ".../stream/book?path=/books/A.cbz"   # last 50
```

**Only files the reader has already opted into serving are reachable.** The
route reuses `AssetServer.is_allowed`, which compares real paths, so a
symlink cannot step outside and `/etc/passwd` returns 404. To make a book
reachable, open it once via the RPC bridge (`reader_open`), or read it
straight off disk yourself — these are local files and you have a path.

---

## 6. Rules the API keeps

1. **Read only.** Nothing under `/local` mutates anything.
2. **Absolute paths, always.** You run in a different working directory.
3. **Locked shelves are respected everywhere.** A book on a locked shelf is
   absent from `books`, `covers`, `reading`, `shelves` and `stats`, and
   `/stream` will not serve it. A privacy screen that any local script can
   step around is not one.
4. **No secrets.** No lock salts, no password hashes, no tokens in any
   payload. `paths()` names `lock.json`; reading it is between you and the
   filesystem.
5. **Additive changes.** Fields get added, not silently repurposed.

---

## 7. If you need to *do* something

`POST /api/<method>` reaches the full `mangasurf.gui.Api` — the same object the
desktop app drives. It can download, delete, repackage and rewrite settings.

```bash
curl -X POST "http://127.0.0.1:8577/api/search?token=TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"args": ["solo leveling", {"source": "mangadex"}]}'
```

Shape: `{"args": [...]}` in, `{"result": ...}` out. Methods map 1:1 to
`Api` methods; `python -m mangasurf api info` will not list them because it is
not that kind of surface — read `mangasurf/gui/__init__.py`.

Two things cannot work remotely and say so rather than failing quietly:
`choose_folder`/`choose_file` (a dialog would open on the host's screen) and
`open_folder`/`open_in_reader` (a window on the host).

**Guidance for agents:** prefer `/local`. Reach for `/api` only when the user
has actually asked for something to change, and say which method you are
about to call before you call it.

---

## 8. Worked example

```python
import requests

BASE, TOKEN = "http://127.0.0.1:8577", "..."
s = requests.Session()
s.params = {"token": TOKEN}

info = s.get(f"{BASE}/local/info").json()
print(info["app"], info["version"], "api", info["api_version"])

# what is the user part-way through?
for row in s.get(f"{BASE}/local/reading").json()["reading"]:
    if not row["finished"]:
        print(f'{row["title"]}: page {row["page"]}/{row["pages"]}'
              f' ({row["percent"]}%)')

# pull the first cover
covers = s.get(f"{BASE}/local/covers").json()["covers"]
if covers:
    art = s.get(f"{BASE}/stream/page",
                params={"token": TOKEN, "path": covers[0]["cover"]})
    open("cover.jpg", "wb").write(art.content)
```

Offline equivalent, no server:

```python
from mangasurf import localapi

for row in localapi.reading():
    if not row["finished"]:
        print(row["title"], row["percent"])
```

---

## 9. Errors

| Status | Meaning |
|--------|---------|
| `401`  | Missing or wrong token. Body: `{"ok": false, "error": "..."}` |
| `404`  | Unknown endpoint (the body lists the valid ones), or a path that is not allowed / does not exist |
| `500`  | A bug. The body carries the message; the server log has the traceback |

Every error body is an object with `ok: false` and `error`, so one branch
handles all of them.

---

## 10. Custom Scrapers & `.source` Plugin Specification

Custom scraper plugins can be defined declaratively in `mangasurf/sources/customsources/*.source` files.

- **Folder Location**: `mangasurf/sources/customsources/` (also aliased as `mangasurf/sources/customscources/`)
- **Specification Document**: [`mangasurf/sources/customsources/syntax.source`](../mangasurf/sources/customsources/syntax.source)
- **Syntax Structure**:
  - `[source]`: `id`, `name`, `base_url`, `domains`, `language`, `nsfw`, `needs_flaresolverr`
  - `[headers]`: Custom HTTP request headers & user-agents
  - `[search]`: Endpoints, parameters, HTML/JSON selectors for query results
  - `[browse]`: Discovery feeds, sort options, and genre parameters
  - `[manga_info]`: Metadata extraction (title, cover, synopsis, authors, tags)
  - `[chapters]`: Chapter list extraction, sorting, and number parsing
  - `[images]`: Page image extraction, hotlink referers, and filter rules

---

## 11. Tools for Organizing & Data Architecture Reference

### File & JSON Storage Locations
All user data and configurations persist inside `~/.mangasurf/` (`readerm/paths.py`):

| File Path | Description | Schema / Contents |
|---|---|---|
| `~/.mangasurf/library.json` | Master Library Index | Map of series key -> `{"title", "url", "source", "directory", "outputs": [...], "items": [...], "color", "added", "last_download"}` |
| `~/.mangasurf/config.json` | Application Settings | General settings: `output_dir`, `default_source`, `format`, `theme`, `accent`, `lib_display_mode`, `lib_paginate`, `server_port`, `opds_port`, `server_token` |
| `~/.mangasurf/history.json` | Search History | Search queries list: `[{"query": "...", "source": "...", "timestamp": 123456, "count": 24}, ...]` |
| `~/.mangasurf/positions.json` | Reading Positions | Key of archive path -> `{"index": 12, "fraction": 0.85, "total": 42, "updated": "..."}` |
| `~/.mangasurf/annotations.json`| Bookmarks & Notes | Per-book annotations: `{"bookmarks": [...], "notes": [...]}` |
| `~/.mangasurf/watchlist.json` | Chapter Update Watcher | Monitored series list: `{"url": {"title", "chapter_count", "source", "last_checked"}}` |
| `~/.mangasurf/opds_folders.json`| OPDS Custom Shelves | Virtual OPDS hierarchy: `[{"id": "...", "name": "...", "enabled": true, "filter": {...}}]` |
| `<manga-folder>/manga.json` | Series Metadata | Local metadata beside archives: `{"title", "description", "cover", "authors", "genres", "status", "source"}` |

### Registered Scrapers Registry (32 Sources)

| ID | Name | Primary Domain | Type |
|---|---|---|---|
| `mangadex` | MangaDex | `mangadex.org` | Manga / Manhwa (SFW) |
| `mangakatana` | Mangakatana | `mangakatana.com` | Manga / Manhwa (SFW) |
| `weebcentral` | Weeb Central | `weebcentral.com` | Manga / Manhwa (SFW) |
| `kagane` | Kagane | `kagane.to` | Manga / Manhwa (SFW) |
| `comix` | Comix | `comix.to` | Manga / Manhwa (SFW) |
| `vymanga` | VyManga | `vymanga.co` / `mangavyvy.net` | Manga / Manhwa (SFW) |
| `mangadotnet` | MangaDotNet | `manga.net` | Manga / Manhwa (SFW) |
| `mangadistrict` | MangaDistrict | `mangadistrict.com` | Manhwa / Webtoons (SFW) |
| `hitomi` | Hitomi.la | `hitomi.la` / `gold-usergeneratedcontent.net` | Hentai / Doujinshi (18+) |
| `simplyhentai` | Simply-Hentai | `simply-hentai.com` | Hentai / Doujinshi (18+) |
| `natomanga` | Natomanga | `natomanga.com` | Manga / Manhwa (SFW) |
| `asurascans` | Asura Scans | `asuracomic.net` | Manhwa / Action (SFW) |
| `flamecomics` | Flame Comics | `flamecomics.me` | Manhwa / Action (SFW) |
| `demonicscans` | Demonic Scans | `demonicscans.org` | Manhwa / Action (SFW) |
| `madarascans` | Madara Scans | `madarascans.com` | Manhwa / Webtoons (SFW) |
| `omegascans` | Omega Scans | `omegascans.org` | Manhwa / Webtoons (SFW) |
| `manhwaread` | ManhwaRead | `manhwaread.com` | Manhwa / Webtoons (SFW) |
| `madaranet` | Madara Network | Aggregate | Manhwa / Webtoons (SFW) |
| `witchscans` | Witchtoons | `witchtoons.net` | Manhua / Webtoons (SFW) |
| `writerscans` | WriterScans | `writerscans.com` | Manhwa / Action (SFW) |
| `webtoons` | Webtoons | `webtoons.com` | Webtoons (SFW) |
| `mangadass` | Mangadass | `mangadass.com` | Manga / Manhwa (SFW) |
| `manhwa18` | Manhwa18 | `manhwa18.com` | Adult Manhwa (18+) |
| `manga18club` | Manga18Club | `manga18.club` | Adult Manhwa (18+) |
| `hentaiakane` | HentaiAkane | `hentaiakane.com` | Hentai / Doujinshi (18+) |
| `nhentai` | nhentai | `nhentai.to` | Hentai / Doujinshi (18+) |
| `chikari` | Chikari | `chikari.moe` | Manhwa / SFW + 18+ |
| `kuramanga` | KuraManga | `kuramanga.com` | Manhwa / Webtoons (SFW) |
| `kurahentai` | KuraHentai | `kurahentai.com` | Hentai / Doujinshi (18+) |
| `hiperdex` | Hiperdex | `hiperdex.com` | Adult Manhwa (18+) |
| `madaradex` | MadaraDex | `madaradex.org` | Adult Manhwa (18+) |
| `mangak` | MangaK | `mangak.io` | Manhwa / Webtoons (SFW) |

### Library Organizing & Maintenance Tools

1. **Recheck & Index Folders (`scan_library_folders`)**:
   - Scans output directory and additional monitored library paths for loose CBZ, EPUB, PDF, and ZIP archives.
   - Automatically assigns series titles, resolves covers, and links volumes.
2. **Metadata Sync & Generation (`rebuild_library_metadata`)**:
   - CLI: `mangasurf library metadata`
   - Generates or syncs `<manga-folder>/manga.json` (chapters, paths, reading progress) and `<manga-folder>/ComicInfo.xml` (ComicRack / OPDS standard) for every downloaded series with title, description, cover, authors, and genres.
3. **Smart Cover Organizer & Auto-Extractor (`organise_covers`, `existing_cover`)**:
   - Auto-extracts Page 1 from CBZ archives into `cover.jpg` when no loose image is present.
   - Searches top sources for high-resolution replacement cover candidates.
4. **Relocation & Directory Reorganization (`relocate_entry`, `find_moved_entries`)**:
   - Detects folders moved across disks or drives and updates `library.json` and reading bookmarks without losing progress.
5. **Duplicate Scanner & Orphan Cleanup (`scan_duplicates`, `find_orphans`)**:
   - Scans library directories for duplicate downloads or unreferenced temporary files.
6. **Snapshot & Backup System (`snapshot`, `restore_snapshot`)**:
   - Creates timestamped restore points of `library.json`, `config.json`, and positions.

---

## 12. CLI Command Syntax for AI Agents & Automated Scripts

AI agents and automated tools can drive the complete Mangasurf engine directly from the command line interface (CLI):

### 🔍 1. Search & Discovery
```bash
# Search across all 32 sources
mangasurf search "solo leveling"

# Search specific source directly with @source prefix or -s flag
mangasurf search "@chikari sword"
mangasurf search "berserk" -s mangadex

# Genre filtered discovery
mangasurf search "rebirth" -g Manhwa -n 10

# Trending browse
mangasurf trending Action

# List all available genres and 32 sources
mangasurf genres
mangasurf sources
```

### 📖 2. Retrieve Series Metadata, Chapters & Descriptions
```bash
# Fetch complete series metadata, synopsis, author, and all chapter links/numbers
mangasurf info "https://mangadex.org/title/32d76d19-8a05-4db0-9fc2-e0b0648fe9d0"
mangasurf info "https://chikari.moe/series/the-bastard-of-swordborne"
mangasurf info "https://hiperdex.com/manga/secret-class"

# Extract cover art or rebuild missing covers
mangasurf covers --dry-run
mangasurf covers -o ~/Manga
```

### ⚡ 3. Download Chapters & Curated Lists
```bash
# Download entire series (auto-detects source from URL)
mangasurf "https://mangadex.org/title/32d76d19-8a05-4db0-9fc2-e0b0648fe9d0"

# Download chapter range (e.g. chapters 1-20)
mangasurf "https://chikari.moe/series/the-bastard-of-swordborne" -c 1-20

# Download newest/latest chapter only
mangasurf "https://chikari.moe/series/the-bastard-of-swordborne" -c latest

# Custom format & bundling (one CBZ per 10 chapters, or PDF / EPUB)
mangasurf <url> --per 10 -f cbz
mangasurf <url> -c 1-50 -f pdf -o ~/Manga

# Bulk Curated List Download (downloads all series in list)
mangasurf "https://chikari.moe/lists/461-my-manhwa-list"
```

### 📊 4. Library Status, Reading Progress & Maintenance
```bash
# Verify library files and missing paths
mangasurf library verify

# Rescan and index external folders
mangasurf library scan ~/Manga

# Generate/Rebuild ComicInfo.xml and manga.json metadata
mangasurf library metadata

# View global download & reading statistics
mangasurf stats
mangasurf disk
```

### 🌐 5. Programmatic REST API & JSON Execution
```bash
# Inspect local API without starting a background server
python -m mangasurf api info
python -m mangasurf api books
python -m mangasurf api reading
python -m mangasurf api stats

# Run headless LAN server with REST API endpoint on :8577
python -m mangasurf server --port 8577 --no-auth

# Run OPDS 1.2 catalog on :8578
python -m mangasurf opds --port 8578
```


