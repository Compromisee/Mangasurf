<div align="center">

<img src="docs/icon.svg" alt="Mangasurf Logo" width="120" height="120" style="margin-bottom: 12px;" />

# Mangasurf

**Download manga, manhwa and manhua from 30+ sites — and read them, in a desktop manga reader with 3D Depth Carousel, Foliate-js engine, full-screen TUI, phone server and OPDS catalog.**

**[Command syntax reference -> SYNTAX.md](MD/SYNTAX.md)

[![Release](https://img.shields.io/github/v/release/Compromisee/mangasurf?style=for-the-badge&color=00f5ff&logo=github)](https://github.com/Compromisee/mangasurf/releases)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PyQt / pywebview](https://img.shields.io/badge/GUI-PyQt%20%7C%20pywebview-2962FF?style=for-the-badge)](https://pywebview.flowrl.com)
[![License](https://img.shields.io/badge/License-MIT-00875A?style=for-the-badge)](LICENSE)

<br>

![Mangasurf Hero Showcase](docs/hero-bento.png)

</div>

---

## Highlights & Features

### Smart Omnibar & Fast Search
- **Instant URL Detection**: Paste any chapter or series link from supported sites to immediately load chapters and metadata.
- **Source Direct Routing**: Target a specific source directly with `@source query` or `source: query` (e.g. `@kagane solo leveling`, `@weebcentral bleach`, `mangakatana: naruto`).
- **Tag Prefix Filtering**: Search by genre tags using `#action #isekai` syntax directly inside the search bar.
- **Fast Concurrent Multi-Source Engine**: High-speed parallel searching across all enabled sources using an optimized worker thread pool.
- **Result Deduplication & Interleaving**: Merge identical titles across sources and round-robin browse results.

### Source Toggling & Management
- **Enable / Disable Switches**: Easily toggle individual manga sources on or off in Settings or the Search Header.
- **Granular Controls**: Turn off discovery browsing for specific sources while keeping direct search enabled, or vice versa.
- **Priority Reordering**: Drag-and-drop or ranking adjustments so your favorite sources always appear first in merged results.
- **Politeness & Rate Limit Controls**: Configure per-source request delays, retries, and result limits.
- **Safe Mode**: Toggle adult-exclusive sources on or off with one switch.

### Advanced Genre Search & Discovery
- **Multi-Source Genre Aggregation**: Automatically aggregates and normalizes genres from all active sources.
- **Multi-Select Chip Filter**: Select multiple genres simultaneously.
- **Match Modes**: Filter by *Match All (AND)* to find titles matching every selected genre, or *Match Any (OR)*.
- **Flexible Sorting**: Sort discovery feeds by *Trending*, *Popularity*, *Latest Updates*, *Top Rated*, or *Alphabetical*.

### Optimized High-Speed Downloader
- **Multi-Threaded Architecture**: Independent chapter workers and image download threads for blazing fast downloads.
- **Atomic File Writing**: Streams to temporary `.part` files and renames upon full validation to prevent corruption.
- **Multiple Export Formats**: CBZ, PDF, EPUB, or raw image folders with customizable naming schemes.
- **Hotlink & CDN Support**: Automated referer routing, magic-byte image validation, and Cloudflare challenge fallback via FlareSolverr.

### Built-in Foliate Reader
- **Smooth Page Scrolling & Webtoon View**: Full vertical strip, single-page, double-page spread, and continuous reading modes.
- **Reading Progress Tracking**: Automatic bookmarking, reading history, streaks, and reading time statistics.
- **Customizable Themes**: Midnight, Dark, Light, Mocha, OLED Black, and Slate with accent color pickers.
- **Passcode-Protected Shelves**: Organize titles into folders and optionally lock private shelves with passcodes.

### Custom Scrapers & `.source` Plugin Engine
- Declarative `.source` plugin architecture in `mangasurf/sources/customsources/`.
- Full specification documented in [`mangasurf/sources/customsources/syntax.source`](mangasurf/sources/customsources/syntax.source).
- Define custom scraper endpoints, CSS/JSON selectors, page extractors, headers, and rate limits without touching core code.

---

## Supported Sources

| Source | Site | Notes |
| :--- | :--- | :--- |
| `mangadex` | `https://mangadex.org` | MangaDex |
| `mangakatana` | `https://mangakatana.com` | Mangakatana |
| `weebcentral` | `https://weebcentral.com` | Weeb Central |
| `kagane` | `https://kagane.to` | Kagane |
| `comix` | `https://comix.to` | Comix |
| `vymanga` | `https://mangavyvy.net` | VyManga |
| `mangadotnet` | `https://mangadot.net` | MangaDotNet |
| `mangadistrict` | `https://mangadistrict.com` | MangaDistrict |
| `hitomi` | `https://hitomi.la` | Hitomi.la ⚠️ 18+ |
| `simplyhentai` | `https://www.simply-hentai.com` | SimplyHentai ⚠️ 18+ |
| `natomanga` | `https://www.natomanga.com` | Natomanga |
| `asurascans` | `https://asuracomic.net` | Asura Scans |
| `flamecomics` | `https://flamecomics.xyz` | Flame Comics |
| `demonicscans` | `https://demonicscans.org` | Demonic Scans |
| `madarascans` | `https://madarascans.org` | Madara Scans |
| `omegascans` | `https://omegascans.org` | Omega Scans |
| `manhwaread` | `https://manhwaread.com` | ManhwaRead |
| `madaranet` | `https://mangabooth.com` | Madara Sites |
| `witchscans` | `https://witchtoons.net` | Witchtoons |
| `writerscans` | `https://writerscans.com` | Writers' Scans |
| `webtoons` | `https://www.webtoons.com` | Webtoons |
| `mangadass` | `https://mangadass.com` | Mangadass ⚠️ 18+ |
| `manhwa18` | `https://manhwa18.cc` | Manhwa18 ⚠️ 18+ |
| `manga18club` | `https://manga18.club` | Manga18.club ⚠️ 18+ |
| `mewhen18` | `https://mewhen18.com` | Mewhen18 (successor to HentaiAkane) ⚠️ 18+ |
| `nhentai` | `https://nhentai.to` | nhentai ⚠️ 18+ |
| `chikari` | `https://chikari.moe` | Chikari |
| `kuramanga` | `https://kuramanga.com` | KuraManga |
| `kurahentai` | `https://kurahentai.com` | KuraHentai |
| `hiperdex` | `https://hiperdex.com` | Hiperdex |
| `madaradex` | `https://madaradex.org` | MadaraDex |
| `mangak` | `https://mangak.io` | MangaK |
| `mangatitan` | `https://www.mangatitan.com` | MangaTitan |
| `manhwa68` | `https://manhwa68.com` | Manhwa68 |
| `manhwabuddy` | `https://manhwabuddy.com` | ManhwaBuddy |
| `hentai18` | `https://hentai18.net` | Hentai18 ⚠️ 18+ |
| `comicland` | `https://comicland.org` | ComicLand |
| `yurivan` | `https://www.yurivan.com` | Yurivan ⚠️ 18+ |

---

## Installation & Quick Start

### 1. Prerequisites
- Python 3.11 or higher (curl_cffi and Mangasurf require 3.11+)

### 2. Install the curl_cffi HTTP engine (required)

**Mangasurf 1.7.2 is 100% curl_cffi.** The `requests` package has been completely
removed — every page fetch, image download and batch request now goes through
[`curl_cffi`](https://github.com/lexiforest/curl_cffi), a thin, native C
binding over libcurl. Why this matters:

- **Real browser fingerprinting** — `impersonate="chrome"` sends a genuine
  TLS/JA3+JA4 fingerprint, so Cloudflare / Akamai bot checks that block plain
  `requests`-style clients are passed automatically. No more `403 / Just a
  moment...` wall.
- **Faster** — libcurl reuses connections and is far quicker per request than
  urllib3 (the engine behind `requests`).
- **Async engine** — the chapter downloader sprays every page across a single
  libcurl multi handle (`mangasurf.http.download_many`), so a chapter of 30
  pages arrives in roughly one page's latency instead of thirty round trips.

Install the native binding (this also installs libcurl under the hood):

```bash
pip install curl_cffi
```

Then install the rest of the project:

```bash
git clone https://github.com/your-repo/Mangasurf.git
cd Mangasurf
pip install -r requirements.txt
```

> **Troubleshooting curl_cffi**
> - **The wheels are prebuilt** — `pip install curl_cffi` ships wheels for
>   CPython 3.8–3.13 on Linux/macOS/Windows, so there is normally **no compiler
>   needed**. If your platform has no wheel (rare), install `libcurl4-openssl-dev`
>   + `python3-dev` and build from source: `pip install --no-binary curl_cffi curl_cffi`.
> - **Missing libcurl** on Linux → `sudo apt install libcurl4-openssl-dev` (Debian/Ubuntu)
>   or `sudo dnf install libcurl-devel` (Fedora).
> - **The default fingerprint** is `impersonate="chrome"`. To use a different
>   profile (e.g. Safari) set the environment variable
>   `MANGASURF_IMPERSONATE=safari` before launching.
> - **Behind a proxy** → curl_cffi respects `HTTP_PROXY` / `HTTPS_PROXY`.
> - **Sanity check** — run `python -c "from mangasurf import http; print(http.get('https://cloudflare.com', timeout=10).status_code)"`
>   (expect `200`; this works even on Cloudflare-fronted pages because of TLS fingerprinting).

### 3. Launch Mangasurf GUI

### 3. Launch Mangasurf GUI
```bash
# Launch desktop GUI
python gui.py

# Or launcher window (see landing.py)
python launcher.py

# Start mobile LAN server (see server.py)
python server.py

# Start OPDS catalog server (see opdsserve.py)
python opdsserve.py
```

---

## Interface Gallery

| View | Screenshot |
| :--- | :--- |
| **Library Grid** | ![Library](docs/gui-library.png) |
| **Search & Discovery** | ![Search](docs/gui-search.png) |
| **Reader View** | ![Reader](docs/gui-reader-chapters.png) |
| **Light Theme** | ![Light](docs/gui-light.png) |
| **Download Queue** | ![Queue](docs/gui-queue.png) |
| **Reading Insights** | ![Insights](docs/gui-insights.png) |
| **Reading Stats** | ![Stats](docs/gui-stats.png) |
| **Source Manager** | ![Sources](docs/gui-sources.png) |
| **Settings Panel** | ![Settings](docs/gui-settings.png) |
| **Library Tools** | ![Tools](docs/gui-tools.png) |
| **TUI Search** | ![TUI Search](docs/tui-search.png) |
| **TUI Manga** | ![TUI Manga](docs/tui-manga.png) |
| **TUI Downloads** | ![TUI Downloads](docs/tui-downloads.png) |
| **TUI Settings** | ![TUI Settings](docs/tui-settings.png) |

---

## License
This project is licensed under the [MIT License](LICENSE).
