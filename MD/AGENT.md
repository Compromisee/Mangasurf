# AGENT.md — reading a ReaderM install from another program

This file is for anything that is **not** ReaderM and wants to know what a
ReaderM install contains: another reader, a sync script, a launcher, a shell
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

…without importing ReaderM, without parsing its private JSON, and without
guessing at paths that differ per platform.

**It is read only.** No endpoint writes, deletes, downloads or starts a job.
Nothing you do here can damage a library. If you need to *act* on the app,
that is the RPC bridge (`POST /api/<method>`), which is a different and much
sharper tool — see §7.

---

## 2. Starting the server

```bash
python -m readerm.server                 # http://<this-pc>:8577
python -m readerm.server --port 9000
python -m readerm.server --host 127.0.0.1    # this machine only
python -m readerm.server --no-auth           # no token, local dev only
```

On start it prints the URL and an access token.

### The token

Every request must carry it, either way:

```bash
curl "http://127.0.0.1:8577/local/info?token=THE_TOKEN"
curl -H "X-ReaderM-Token: THE_TOKEN" http://127.0.0.1:8577/local/info
```

It is a shared secret over plain HTTP. It stops another user on the same
network poking at your library; it is not authentication and this must never
be port-forwarded to the internet.

### No server, no problem

The same data is available without HTTP:

```bash
python -m readerm api info
python -m readerm api books
python -m readerm api reading
```

and in-process:

```python
from readerm import localapi
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
  "app": "ReaderM",
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
  "data_dir": "/home/you/.readerm",
  "download_dir": "/home/you/Downloads/Manga",
  "files": {
    "library":   { "path": "/home/you/.readerm/library.json",
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

`POST /api/<method>` reaches the full `readerm.gui.Api` — the same object the
desktop app drives. It can download, delete, repackage and rewrite settings.

```bash
curl -X POST "http://127.0.0.1:8577/api/search?token=TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"args": ["solo leveling", {"source": "mangadex"}]}'
```

Shape: `{"args": [...]}` in, `{"result": ...}` out. Methods map 1:1 to
`Api` methods; `python -m readerm api info` will not list them because it is
not that kind of surface — read `readerm/gui/__init__.py`.

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
from readerm import localapi

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
