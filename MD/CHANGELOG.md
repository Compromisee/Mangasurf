# Changelog

All notable changes to **Mangasurf**, newest first.

---

## [Unreleased] — Efficiency & Motion

### Fixed: onefile EXE crashing with "No module named 'curl_cffi'"
- `curl_cffi` is Mangasurf's only HTTP layer (requests was removed), but the
  PyInstaller spec didn't list it as a hidden import. If the build environment
  lacked it, PyInstaller silently skipped it and shipped an exe that died at
  runtime in the phone-server / opds / gui children with
  `ModuleNotFoundError: No module named 'curl_cffi'`. The spec now explicitly
  bundles `curl_cffi`, its `_wrapper.abi3` extension, and `cffi`/`_cffi_backend`,
  and **fails the build with a clear message** if they aren't importable —
  so a broken exe can never be produced again. (Rebuild your onefile after
  `pip install curl_cffi`.)

### TUI now matches the docs screenshots
- Restyled `mangasurf/tui.py` to the docs' visual identity: a traffic-light
  window chrome with a centred cyan title, letter-spaced uppercase panel
  headings, bordered panels on a deep-navy canvas, numbered `[01]` search
  rows with coloured source badges and a live ANSI cover preview, a chapter
  list with two-column rows, download telemetry cards with ASCII progress
  bars and a session-history log, and a two-column settings view with a
  scraper matrix. All existing features, bindings and widget IDs are intact.

### No more thread churn on every search
- `search_all`, `browse_all` and the genre fan-out no longer create and tear
  down a fresh `ThreadPoolExecutor` on every call. They now fan out through
  one shared, lazily-grown, capped pool. Previously every search keystroke
  spawned ~14 worker threads and joined them, which — on a fast machine —
  was its own source of lag.

### Lazy image pool in the download engine
- The 16-thread image pool is only constructed when the thread-per-image
  fallback actually runs. The default async engine (one libcurl multi
  handle) streamed images itself while 16 idle threads sat around; those are
  gone.

### HentaiAkane → Mewhen18
- `hentaiakane` has been replaced by `mewhen18` (`https://mewhen18.com`),
  the same catalogue re-hosted, since `hentaiakane.com` was taken over by an
  unrelated blog.

### Extra GPU-friendly motion (no features removed)
- Staggered card entrance, press feedback, a cover-load shimmer, and
  compositor-only `transform`/`opacity` hints so animations ride the GPU and
  never cause layout/paint thrash. A `prefers-reduced-motion` guard disables
  them for users who ask for it.

---

## [1.7.3] — Mangasurf v1.7.3: Per-Chapter Downloaded Counts, Four New Verified Sources, Docs Hub & UI Polish

### Search results now show the real downloaded chapter count
- **Fixed the "1 chapter downloaded" badge.** Search result cards used to count
  *files*, so a single bundled CBZ (which holds many chapters) showed "1
  Downloaded" even though the manga detail view correctly showed the full
  count. The card badge is now corrected against the same authoritative
  `downloaded_status` the detail view uses (read from each series'
  `manga.json`), and `getDownloadedMeta` prefers the larger of file count /
  chapter count. The card and detail view always agree now.

### New sources (38 total)
- **Added `manhwa68`** (Madara engine) — verified search / browse / genres /
  chapters / CDN pages.
- **Added `manhwabuddy`** — verified search / series / chapters / page CDN.
- **Added `hentai18`** — verified NSFW search / series / chapters / page CDN.
- **Added `comicland`** — verified REST-API source (search / browse / detail /
  `pages_by_index`), Referer-protected.
- **Added `yurivan`** — best-effort; Yurivan gates every page behind a
  client-side age gate, so this source degrades gracefully and is marked
  unverified. Prefer the other adult sources.
- Removed the fake `kings` and `kamiya` sources (already removed in 1.7.2).

### curl_cffi HTTP layer (carried forward and hardened)
- 100% curl_cffi; `requests` fully removed. `mangasurf/http.py` is the single
  network layer with browser TLS/JA3+JA4 impersonation and a fast async
  batch engine (`fetch_many` / `download_many`) used by the downloader.

### Documentation Hub & website
- Added a **Documentation hub** to the landing page linking to self-contained
  doc pages: getting-started, sources, http-engine, downloading, roadmap,
  troubleshooting.
- Regenerated the README source table and landing-page source directory from
  the live registry (rows can no longer drift).
- Updated CHANGELOG, ROADMAP, TODO and FEATURES.

### UI & fixes
- Targeted padding/responsiveness polish in the reader shell and source grid.
- **Custom horizontal + vertical scrollbars** site-wide — a thin accent-gradient
  thumb on a dark track (Chromium/Safari `::-webkit-scrollbar` + Firefox
  `scrollbar-width`), so wide code blocks, cards and tables scroll cleanly.
- **Expandable docs sidebar tree** — every documentation page now carries a
  sticky, collapsible tree sidebar (like most docs sites) listing all six doc
  pages and their on-page sections. The current page's branch is expanded and
  highlighted; the others deep-link into their anchors. On narrow screens the
  tree collapses behind a "Documentation contents" drawer toggle.
- Version bumped to **1.7.3**; `requires-python >=3.11`.

#### Scraper fixes (this batch)
- **Fixed `mangadotnet`** — the `/api/search` and `/api/manga` endpoints return
  a `manga_list` array (not `data`/`results`), which the old parser ignored, so
  search/browse always returned 0 results. Now reads `manga_list`.
- **Fixed `witchscans` (witchtoons) result titles** — the search page is a
  Next.js SPA returning HTML (never JSON), and the fallback parser read the
  whole card's text, so every result was titled the type badge ("MANHWA") or a
  chapter label. Titles now come from the cover `img[alt]` (with anchor/@title
  fallback), chapter links are skipped, and Next.js `/_next/image` proxy cover
  URLs are decoded to the real CDN URL.
- **Fixed `hentai18` result titles** — the series cards carry *absolute* URLs
  (`https://hentai18.net/read-hentai/<slug>`) that a relative-path-only regex
  rejected, so only the sidebar "Oneshot"/"Chapter N" rows survived. The path
  regex now accepts both, and titles come from the cover `img[alt]`.
- **Fixed missing covers on `manhwa68`, `hentai18`, `yurivan`** — their cover
  CDNs 403 a cross-origin browser request (a wrong Referer), so the thumbnails
  never rendered. All three hosts are now routed through the `proxy_cover`
  path, which fetches with the source's own Referer.
- **Fixed one-page "No More Results" bugs** — several sources ignored the
  `page` argument and always returned the first page:
  - `comicland` — API pages on a row index, not `?page=`; paginates by
    `offset` now, and the static `/comics/popular` list falls back to the
    paginated `/comics` feed.
  - `mangatitan` — pages ≥2 use a blog-archive layout (`.entry-archive`)
    instead of the `.series-card` grid; both are parsed now, and per-chapter
    posts are deduped to unique series.
  - `yurivan` — browse/search sliced `[:limit]` so every page repeated page 1;
    now slices by page (and search pages by offset).
  - `mangak` — search already paginated; trending browse is a static top-50
    list by design (no server paging).
- **Cloudflare-only sites (`kagane`, `comix`)** remain behind a real browser
  JS challenge that TLS impersonation alone cannot pass — they require the
  FlareSolverr fallback. `mangadotnet` and `natomanga` now work regardless;
  `hentaiakane.com` was taken over by an unrelated blog, so the `hentaiakane`
  source has been replaced by `mewhen18` (`https://mewhen18.com`), the same
  catalogue re-hosted — same theme, same `img.hentai1.io` image CDN.

---

## [1.7.2] — Mangasurf v1.7.2: 100% curl_cffi (no `requests`), Fast Async Engine, Removed Fake Sites, New Verified Source

### HTTP layer: all-in on curl_cffi, `requests` fully removed
- **`requests` is gone from the dependency graph.** `requirements.txt`,
  `pyproject.toml` and every file that imported it have been migrated to
  **curl_cffi**. TCP/HTTP in Mangasurf is now handled entirely by
  `mangasurf/http.py`.
- **New `mangasurf/http.py` module** — the single place Mangasurf talks to the
  network:
  - `Session` — a `requests`-compatible synchronous session with **real
    browser TLS/JA3+JA4 fingerprinting** (`impersonate="chrome"`) by default,
    so Cloudflare / Akamai bot checks that blocked plain `requests` clients are
    passed automatically. The dozens of source plugins keep calling
    `session.get(...).json()` with zero changes.
  - `AsyncEngine` + `fetch_many()` / `download_many()` — a **fast async engine**
    that drives one libcurl multi handle to fetch/download dozens of urls
    concurrently. `MANGASURF_IMPERSONATE=safari` switches the fingerprint.
- **Chapter downloads use the async engine.** The downloader streams every page
  of a chapter across the shared async handle (`Source.download_many` /
  `http.download_many`), returning a full chapter of 30 pages in roughly one
  page's latency. Atomic `.part` → `os.replace` writes and magic-byte image
  validation are preserved.
- **Backwards-compatible exception aliases** (`exceptions.RequestException`,
  `ConnectionError`, `Timeout`, `HTTPError`, ...) so existing error-handling
  code keeps working verbatim, and `requests` is re-exported as an alias for
  curl_cffi for any plugin that still references it.
- Removed the old urllib3 `HTTPAdapter` pool-sizing shim (curl_cffi owns its own
  connection pool).
- Migrated `flaresolverr.py`, `metadata.py`, `gui/__init__.py` and `chikari.py`
  to curl_cffi (Cloudflare fallback, cover enrichment, cover proxies and tag
  lookups all still work).

### Sources
- **Removed `kings` (Kings Manga) and `kamiya` (Kamiya Scans)** — both pointed
  at fake / dead domains; they were unreliable and are no longer registered.
- **Added `mangatitan` (MangaTitan, mangatitan.com)** — a verified new scan
  site with real browser-impersonation scraping: search, series info, chapter
  list (oldest-first) and the lazy-loaded CDN page list all work end-to-end.
- Source count is now **30+ (33 registered)** — the README source table is
  regenerated from the live registry so it can't drift.

### Packaging, compatibility & fixes
- **Version bumped to 1.7.2**; `requires-python = ">=3.11"` (curl_cffi supports
  3.8+, but Mangasurf now targets 3.11+). Verified the import/test matrix on
  Python 3.13; code avoids 3.12+ only features so it runs cleanly on 3.11.
- README rewritten with **curl_cffi install & troubleshooting** notes (wheel
  install, libcurl deps, `MANGASURF_IMPERSONATE`, proxy handling, sanity check).
- Fixed the new failures caught by the migration: connection-pool test now
  asserts the curl_cffi session, source-genre/registry tests updated, the
  bare-file relative-import guard test updated to the absolute imports, and the
  live Witchtoons integration test is gated behind `READERM_NETWORK_TESTS=1`
  (that reader now renders pages client-side).

---

## [1.7.1] — Mangasurf v1.7.1: Internal Chapter Grouping & TOC Resolution, Sibling Chapter Archive Discovery & Exact Download Sync

### Highlights & Fixes
- **Internal Chapter Grouping & TOC Resolution for Multi-Chapter CBZ Bundles**:
  - Rebuilt `mangasurf/reader/foliate/comic-book.js` to automatically parse internal chapter folder structures (e.g. `0001 - Chapter 1/001.jpg`, `0002 - Chapter 2/001.jpg`, etc.) and `ComicInfo.xml` bookmarks into structured Table of Contents (`book.toc`) with chapter section headers.
  - Resolved the bug where all pages in a bundled volume were reported as coming from chapter one; each page is now tagged with its distinct chapter grouping (`Chapter 1 • 001`, `Chapter 2 • 001`) matching Readest behavior.
- **In-Reader Sibling Chapter Discovery (`reader_chapters`)**:
  - Enhanced `reader_chapters` in `mangasurf/reader/api.py` to discover both chapter subfolders AND all sibling chapter archive files (`.cbz`, `.epub`, `.pdf`, `.zip`), populating `#chap-items` and allowing direct chapter switching in the reader drawer.
- **Exact Downloaded Chapter Matching & Single Source of Truth**:
  - Fixed `isChapterDownloaded()` to match exact floating/integer chapter numbers and exact normalized names, completely preventing date numbers (`2026-08-16`) or substrings from over-matching all chapters.
  - Synchronized left metadata tag (`5 Downloaded`) and right chapter filter bar (`5 Downloaded`) to use identical matching logic (`getMatchingDownloadedCount()`).
- **Clean Background Highlighting ONLY**:
  - Downloaded chapter rows use clean emerald background highlighting (`rgba(16, 185, 129, 0.12)`) and green checkmarks with side indicator lines removed.
- **34 Sources, Kings Manga & Kamiya Scans**:
  - Registered `KingsSource` and `KamiyaSource`.
- **Modular Plugin Architecture**:
  - Dynamic discovery and hot-reloading from `~/.mangasurf/sources/*.py` with **Reload Plugins & Sources** button in Settings.
- **Sub-Millisecond `curl_cffi` TLS Impersonation**:
  - Added native Chrome 124 JA3/JA4 TLS impersonation with ping test and auto-fallback to FlareSolverr.
- **Complete User Data Backup & Restoration**:
  - Added Export, Import, and Selective Deletion tools in Settings for search history, suggestions cache, library paths, and reading telemetry.

---

## [1.7.0] — Mangasurf v1.7.0: Custom Vector Wave Icon, Multi-Platform GitHub Actions Suite & OneFile Release Pipeline

### Highlights & Major Additions
- **Instant Online Reading Without Downloading Across All 32 Sources**:
  - Unlocked instant streaming reading for any chapter directly from online sources without needing to download a single file to disk.
  - The **Read** button (`#d-read`) on the series page is now always visible and dynamically switches between `<span class="mi">menu_book</span>Read (Offline / Local)` and `<span class="mi">auto_stories</span>Read Online (Instant Stream)`.
  - Added dedicated `<button class="ch-read-online-btn">` on every chapter row in `#d-chapters` for 1-click online chapter streaming.
  - `reader_open` seamlessly resolves online chapter image URLs and renders them directly inside Foliate paged / webtoon continuous scroll mode.
- **Downloaded Chapter Clean Background Highlighting**:
  - Downloaded chapters are styled with a clean emerald background highlight (`rgba(16, 185, 129, 0.12)`) and green checkmark icon, with the side indicator line removed.
- **Universal Metadata Providers (MAL, PornhwaDB, MangaBaka) & Cross-Source Matching**:
  - Integrated **MyAnimeList (MAL / Jikan REST API)** for official titles, English/Japanese synonyms, score, and synopsis.
  - Integrated **PornhwaDB (`pornhwadb.com`)** for adult manhwa tags, characters, and alternative titles.
  - Integrated **MangaBaka** for cross-source title cross-referencing and alternative synonyms.
  - **Universal Download Matching Across Sources**: Downloading a series from one source (e.g. MangaDex) now automatically flags it as **DOWNLOADED** when searching or browsing on other sources (e.g. Asura, Chikari, Flame Comics, KuraManga).
- **Dual Metadata Architecture: ComicInfo.xml & manga.json**:
  - Rebuilding and packaging now writes **both** `manga.json` (chapters, local paths, pages, reading progress) and standard `ComicInfo.xml` (Title, Series, Summary, Writer, Penciller, Genre, Tags, Rating, Year, Source) in every series folder and CBZ archive.
- **Library Maintenance Tools in Settings**:
  - Added **Rescan All Books**, **Fix Missing Covers**, **Rebuild XML & JSON Metadata**, and **Clean Cache** tools directly inside Settings → Library & Folders.
- **Title Decluttering in File Explorer & OPDS Server**:
  - Added setting to declutter messy release tags, brackets, and resolution stamps (`[Official]`, `[1080p]`, `(Uncensored)`, `[Complete]`) for clean titles in File Explorer, OPDS reader apps, and LAN web reader.
- **Clean Workspace Architecture**:
  - Standardized core package name to `mangasurf` with backward-compatible `mangasurf` alias.
- **Downloaded Cover Hover Darken & Fraction Badge**:
  - Automatically identifies downloaded manga in search and browse results by cross-referencing `libraryCache`.
  - Added floating status badge (`XX / XX Ch.`) on the top-left of cover thumbnails.
  - On card hover, smoothly darkens the cover with a translucent blur overlay (`.thumb-hover-overlay`), revealing a green verification checkmark, `DOWNLOADED` label, exact downloaded vs. total chapter fraction (e.g. `28 / 42 Ch.`), and a glowing progress indicator bar.
- **Instant "Add to Queue" Button on Search Result Covers**:
  - Embedded an interactive floating glassmorphic button (`.card-queue-btn`) on the top-right of every search and browse cover thumbnail.
  - Clicking the button enqueues all chapters of that manga for download with instant visual feedback, animated spin loader, green checkmark transition (`.added`), and toast notification without opening the details modal.
- **Brand-New Custom Vector SVG Icon**:
  - Replaced legacy generic book icons with a custom, sleek modern **MangaSurf** brand icon (`docs/icon.svg`, `docs/icon.png`, `docs/icon.ico`, `docs/icon-1024.png`).
  - Features a cosmic obsidian squircle container, ambient neon rim lighting, floating translucent manga action frames, sweeping fluid surf wave with electric cyan-to-magenta gradients, breaking anime foam claws, aerodynamic surfboard with racing chevrons, 4-point comic star sparkles, and specular glass gloss reflection.
  - Exported multi-size Windows ICO (`icon.ico`), PNG masters (`icon-1024.png`, `icon.png`), and web favicons (`favicon.png`, `favicon.ico`).
- **Complete Suite of 8 Production GitHub Actions Workflows**:
  - **`release.yml`**: Multi-platform PyInstaller onefile builds for **Windows x64** (`.exe`), **Linux x86_64** (ELF binary & tarball), **macOS ARM64** (Apple Silicon M1/M2/M3/M4), and **macOS Intel** (`x86_64`), automatic release notes generation from changelog, SHA256 checksums generation (`SHA256SUMS.txt`), and automated GitHub release publishing.
  - **`ci.yml`**: Multi-OS & Multi-Python test matrix across Ubuntu, Windows, macOS on Python 3.10, 3.11, 3.12, and 3.13 with pytest, flake8 linting, and web asset syntax validation.
  - **`nightly.yml`**: Daily automated bleeding-edge onefile builds and continuous `nightly` pre-release deployment.
  - **`source-health.yml`**: Scheduled 6-hour radar testing and uptime monitoring for all 32 scraper sources.
  - **`pages.yml`**: Automated zero-config deployment of the animated landing page (`docs/`) to GitHub Pages.
  - **`docker.yml`**: Multi-arch container image builder (`linux/amd64`, `linux/arm64`) publishing headless server and OPDS catalog to GitHub Container Registry (`ghcr.io/compromisee/mangasurf`).
  - **`security.yml`**: GitHub CodeQL static code analysis, Bandit Python AST security scanner, and dependency vulnerability audits.
  - **`pypi.yml`**: Python package build (`sdist` & `bdist_wheel`) and twine validation pipeline.
- **High-Definition Screenshot Suite**:
  - Rendered crisp 2560x1640 PNGs for all 11 GUI interfaces (`gui-library.png`, `gui-light.png`, `gui-search.png`, `gui-queue.png`, `gui-settings.png`, `gui-sources.png`, `gui-stats.png`, `gui-manga.png`, `gui-reader-chapters.png`, `gui-insights.png`, `gui-tools.png`), master promotional hero (`hero-bento.png`), and four 1920x1080 Textual TUI screens (`tui-search.png`, `tui-manga.png`, `tui-downloads.png`, `tui-settings.png`).
- **Infinite Multi-Page Discovery & Scraper Pagination**:
  - **Hiperdex (`hiperdex.py`)**: Fixed tRPC query parameter schema: converted `{"query": query, "page": page}` to `{q: query, limit: limit, offset: (page-1)*limit, sort: "popular"}` with automatic 401 session recovery, fixing the issue where only 2 pages were loading due to offset remaining 0. Added bare chapter URL resolution (`/manga/slug/chapter/num` without `cid`), restoring full multi-page chapter images for direct URL inputs.
  - **KuraManga (`kuramanga.py`)**: Implemented ID list batching (`/search?ajax=1&ids=1&keyword=`) and batch slicing (`/search?ajax=1&pick=...`), unlocking infinite pagination past 2 loadmores across 3,900+ search and browse results.
  - **KuraHentai (`kurahentai.py`)**: Connected to Supabase REST API (`/rest/v1/hentai`) with offset-limit pagination (`order=id.desc&offset=...`), supporting endless gallery search and browsing across thousands of titles.
- **Universal CDN Cover Proxying (KuraManga, Hiperdex, MangaK, KuraHentai)**:
  - Registered all CDN domains (`shadowabyss.com`, `r2d2storage.com`, `resmk.org`, `qvzre.org`) into the scraper domain registry and added session `Referer` fallbacks in `proxy_cover()`.
- **Root Directory Deletion Protection**:
  - Protected roots registry (`output_dir`, `library_folders`, `~`, `/`); deleting a library entry now strictly removes only specific series archive files, completely protecting master directories and parent folders.
- **Witchtoons Accurate Series Routing**:
  - Rebuilt `witchscans.py` metadata parser to extract series metadata directly from HTML JSON-LD and RSS feeds, ensuring every series routes to its exact individual page with accurate titles, descriptions, and chapters.
- **Mobile Carousel Memory & Crash Fix**:
  - Optimized carousel track to only render visible perspective cards ($\pm 3$ cards), reducing DOM nodes from 200+ heavy 3D elements to 7 cards.
  - Added responsive mobile styles (`@media (max-width: 640px)`) preventing WebKit GPU memory tab crashes on phone servers.
- **Interactive Click-to-Read & All-Around Card Glow**:
  - Clicking the centered active cover card in the carousel immediately opens the reader to start reading (`openPath()`).
  - Added 360-degree luminous drop-shadow aura around the active card with spring physics (`cubic-bezier(0.34, 1.45, 0.64, 1)`).
- **Comprehensive Organizing Documentation in `MD/AGENT.md`**:
  - Added Section 11 documenting file & JSON storage paths (`library.json`, `config.json`, `history.json`, `positions.json`, `annotations.json`, `manga.json`), the 32-source scraper registry, and maintenance tools.
- **Updated High-Resolution Screenshots Suite**:
  - Rendered updated 2560x1640 PNG screenshots across all GUI interfaces (`gui-library.png`, `gui-search.png`, `gui-queue.png`, `gui-settings.png`, `gui-stats.png`, `gui-sources.png`).

---

## [1.6.9] — Mangasurf v1.6.9: Curated List Bulk Downloading, Chikari List Parsing & 100-Test Milestone

### Highlights & Additions
- **Chikari.moe Curated List Bulk Downloading**:
  - Full support for downloading entire curated user lists (e.g. `https://chikari.moe/lists/461-my-manhwa-list`).
  - Pasting any list URL into the omnibar parses the list via `/api/lists/{id}` and prompts for one-click bulk download across every series in the list.
  - Automatically enqueues all chapters from every manga in the list into the concurrent queue (`Api.download_list()`).
- **Comprehensive Scraper & UI Suite**:
  - Passed 100/100 automated unit tests across 14 test suites verifying scrapers, security boundaries, and desktop reader interfaces.

---

## [1.6.8] — Mangasurf v1.6.8: Root Directory Deletion Protection, Witchtoons Dynamic Routing, Mobile Carousel Optimization & Staggered Animations

### Highlights & Fixes
- **Root Directory Deletion Protection**:
  - Fixed safety vulnerability where deleting a series file inside a root/shared folder previously called `rmtree` on the parent directory.
  - Added protected roots registry (`output_dir`, `library_folders`, `~`, `/`); deleting a file now strictly deletes only the specific archive files (`.cbz`, `.epub`, `.pdf`, `.zip`), completely protecting the master library and parent folders.
- **Witchtoons Accurate Series Routing**:
  - Rebuilt `witchscans.py` metadata parser to extract series titles directly from HTML JSON-LD and RSS feeds, ensuring every series routes to its exact individual page rather than defaulting to The Assassin Son-in-Law.
- **Mobile Carousel Memory & Crash Fix**:
  - Optimized carousel track to only render visible perspective cards ($\pm 3$ cards), reducing DOM nodes from 200+ heavy 3D elements to 7 cards.
  - Added responsive mobile styles (`@media (max-width: 640px)`) preventing WebKit GPU memory tab crashes on phone servers.
- **Staggered Library Card Animations**:
  - Added smooth card entrance physics (`@keyframes cardFadeIn`) and fluid hover lift with depth shadow across all library grid cards.
- **Universal CDN Cover Proxying**:
  - Configured `HOTLINK_PROTECTED` and fallback referer headers so KuraManga (`shadowabyss.com`), Hiperdex (`r2d2storage.com`), and MangaK (`resmk.org`) covers load instantly in the GUI.

---

## [1.6.7] — Mangasurf v1.6.7: Infinite Scraper Pagination, All-Around Card Glow, Click-to-Read & Full Hotlink Resolution

### Highlights & Fixes
- **Infinite Multi-Page Discovery across Scrapers**:
  - **KuraManga (`kuramanga.py`)**: Integrated ID list batching (`/search?ajax=1&ids=1&keyword=`) and chunk slicing (`/search?ajax=1&pick=`), enabling infinite continuous pagination past 2 loadmores across thousands of results.
  - **KuraHentai (`kurahentai.py`)**: Rebuilt on Supabase REST API (`/rest/v1/hentai`) with offset-limit pagination (`order=id.desc&offset=...`), supporting endless gallery search and browsing.
  - **Hiperdex (`hiperdex.py`)**: Enabled tRPC `search.query` pagination across all search and browse pages.
- **Full Hotlink CDN Cover Resolution in GUI**:
  - Added `shadowabyss.com`, `r2d2storage.com`, `resmk.org`, and `qvzre.org` to frontend `HOTLINK_PROTECTED` regex in `app.js`.
  - Added session headers and fallback proxying in `proxy_cover()`, converting all protected cover art into instant data URIs across search, browse, library, and the carousel.
- **Carousel 360-Degree Aura Glow & Card-to-Card Physics**:
  - Added full 360-degree luminous drop-shadow aura around the active card with smooth spring physics (`cubic-bezier(0.34, 1.45, 0.64, 1)`).
  - Hovering adds an amplified glow and floating lift (`translateY(-6px)`).
  - Cleaned up vertical headroom and footroom to eliminate any clipping above the counter pill.
- **Interactive Click-to-Read**:
  - Clicking on the active centered cover card now **immediately opens the reader to start reading the series** (`openPath()`).
  - Clicking on any side card smoothly slides and animates to that card.
- **Fullscreen / Immersive Split Theatre Mode**:
  - Restructured `.carousel-split-layout` into 2 balanced columns: left column contains the active series details, dynamic progress bar, chapter range, metadata tags, editable description, and action buttons; right column houses the 3D cover carousel viewport, navigation arrows, and counter pill.

---

## [1.6.6] — Mangasurf v1.6.6: Card-to-Card 3D Spring Transitions, All-Around Luminous Glow, Click-to-Read & Split Theatre Layout

### Highlights & Fixes
- **Interactive Click-to-Read Carousel Cards**:
  - Clicking on the active centered cover card now **immediately opens the reader to read the series** (`openPath()`).
  - Clicking on any side card smoothly slides and animates to that card.
- **All-Around Luminous 3D Card Glow & Zero Clipping**:
  - Rebuilt active card aura with 360-degree luminous drop-shadow (`box-shadow: 0 0 36px color-mix(in srgb, var(--accent) 60%, transparent), 0 0 16px var(--accent)`).
  - Hovering on any card adds a floating elevation and amplified glow (`translateY(-6px)`).
  - Increased spacing above the details panel and between the counter pill, eliminating all bottom clipping.
- **Card-to-Card 3D Spring Physics**:
  - Configured fluid card-to-card animation transitions with spring easing curve (`cubic-bezier(0.34, 1.45, 0.64, 1)`), cleanly disabled when animation settings are toggled off.
- **Fixed Fullscreen / Immersive Split Theatre Mode**:
  - Re-architected `.carousel-split-layout` into 2 balanced columns: left column contains the active series details, progress meter, and action buttons; right column houses the 3D cover carousel viewport and navigation arrows.

---

## [1.6.5] — Mangasurf v1.6.5: Carousel Zero-Clipping, Universal CDN Proxy, Infinite Multi-Page Discovery & Folder Indexing

### Highlights & Fixes
- **Carousel Bottom Overflow & Card Outline Spacing**:
  - Eliminated bottom clipping above the counter pill by moving the details panel down with `margin-top: 24px` and padding the viewport `350px`.
  - Added "Carousel Only (Immersive Mode)" option in Settings › Library Layout to allow using pure carousel view.
  - Enabled infinite looping when navigating past the edges.
- **Universal CDN Cover Proxying (KuraManga, KuraHentai, Hiperdex, MangaK)**:
  - Registered all CDN domains (`shadowabyss.com`, `r2d2storage.com`, `resmk.org`, `qvzre.org`) into the scraper domain registry and added intelligent `Referer` fallbacks in `proxy_cover()`, fixing blank covers across search, browse, and carousel.
- **Multi-Page Pagination across Scrapers**:
  - Enabled multi-page pagination on `Hiperdex` (`search.query`), `KuraManga` (`/search?ajax=1&page=`), and `KuraHentai` (`/?page=` and `/tag/{slug}/?page=`).
- **External Folder Scanning Fix**:
  - Upgraded `scan_library_folders()` in `mangasurf/library.py` to index both parent directories and individual series folders with multiple CBZ/ZIP chapter archives.
- **Chikari.moe Custom Tags & NSFW Unblock**:
  - Integrated `/api/tags` resolution for over 1,900 custom tags and enabled `adult=true` querying so all adult/NSFW titles are returned when Safe Mode is off.
- **Live Server Traffic & Activity Console Streaming**:
  - Added global server log channels in `server.py` and `opdsserve.py` capturing every HTTP stream request and OPDS feed call with formatted level badges (`INFO`, `CALL`, `WARN`, `ERROR`), timestamps, and autoscroll.

---

## [1.6.4] — Mangasurf v1.6.4: Immersive Split Theatre Carousel, Multi-Source Pagination, Scraper Referer Proxying & Data Architecture Reference

### Highlights & New Additions
- **Carousel Zero-Overflow & 7-Card Overlapping Cascade**:
  - Eliminated bottom cut-off and vertical clipping on carousel cover cards. Configured viewport height (`350px`) with 210×305px cards and generous padding.
  - Multi-card overlapping 3D cascade (`prev-3`, `prev-2`, `prev-1`, `active`, `next-1`, `next-2`, `next-3`) with center elevation on top (`z-index: 20`, `translateZ(130px)`), realistic depth shadows, and smooth hover lift animations.
- **Carousel Immersive Split Theatre Mode**:
  - Added dedicated toggle button (`#carousel-immersive-toggle`) to activate 50/50 split theatre view: left side shows prominent title, dynamic progress bar, chapter range, metadata tags, editable description, and action buttons; right side displays the 3D cover carousel.
- **Carousel Multi-Criteria Sorting Engine**:
  - Added sorting dropdown (`#carousel-sort`) to sort library carousel by **Recent Downloads**, **Reading Progress**, **Chapter Count / Size**, **Source Provider**, and **Alphanumeric (A-Z)**.
- **Library Pagination Engine**:
  - Added Library Pagination settings (`#set-lib-paginate`, `#set-lib-page-size`: 12, 24, 36, 48 items/page) and interactive pagination bar (`#lib-pagination`).
- **Scraper Referer & Image Proxy Fixes**:
  - **MangaK (`mangak.py`)**: Added `cover_needs_referer = True` for `rx.resmk.org` and `rx.qvzre.org` image proxying.
  - **Hiperdex (`hiperdex.py`)**: Fixed `cover_needs_referer = True` and added infinite multi-page browsing via tRPC.
  - **KuraManga & KuraHentai (`kuramanga.py`, `kurahentai.py`)**: Fixed `shadowabyss.com` cover proxying and enabled multi-page search and browse pagination.
  - **Chikari (`chikari.py`)**: Integrated custom tags resolution via `/api/tags` mapping and unblocked adult/NSFW results.
- **Comprehensive Organizing Documentation in `MD/AGENT.md`**:
  - Added complete Section 11 documenting file & JSON storage paths (`library.json`, `config.json`, `history.json`, `positions.json`, `annotations.json`, `manga.json`), the 32-source scraper registry, and maintenance tools.

---

## [1.6.3] — Mangasurf v1.6.3: Scraper Fixes, Chikari NSFW Unblock, Hiperdex Multi-Page & Title Sanitization

### Highlights & Fixes
- **KuraManga & Hiperdex Cover Proxying**: Set `cover_needs_referer = True` and injected proper `Referer` and session headers so `shadowabyss.com` and `r2d2storage.com` covers load smoothly without 403 Forbidden errors.
- **Chikari.moe Adult / NSFW Results Unblocked**: Added `adult=true` search and browse parameter merging on `chikari.moe` API so all NSFW and 18+ titles are returned when Safe Mode is disabled.
- **Hiperdex Multi-Page Chapter Image Extraction**: Fixed slug extraction bug in `reader.chapterPages` on `hiperdex.py` that truncated series slugs, restoring full multi-page chapter extraction (10-150+ pages per chapter).
- **MadaraDex Title Sanitization**: Cleaned up title parsing in `madaradex.py` to strip out `18+` and `Uncensored` badges from card titles, correctly extracting real series titles.
- **MangaK Full Operational Pipeline**: Fixed `mangak.io` browse and chapter extraction by mapping Next.js SSR props (`items`, `ssrItems`, `trendingItems`, `popularItems`) and correctly sorting chapters in oldest-first order.

---

## [1.6.2] — Mangasurf v1.6.2: Carousel 3D Cascade, Reading Progress Engine, FlareSolverr Manager & Zero Overflow

### Highlights & Fixes
- **Carousel 3D Depth Overlapping Cascade & Zero Overflow**:
  - Redesigned 3D Library Carousel with 7 visible overlapping cascading cards (`prev-3`, `prev-2`, `prev-1`, `active`, `next-1`, `next-2`, `next-3`).
  - Active card is prominently elevated on top (`z-index: 20`, `scale(1.16)`, `translateZ(140px)`), with side cards stepping down in scale, depth, and z-index.
  - Eliminated vertical overflow: cards fit comfortably inside a 320px viewport with generous 28px padding.
  - Fixed blank/white carousel covers by piping cover art through `coverAttrs()` and `hydrateCovers()`.
- **Dynamic Reading Progress Bar**:
  - Carousel info panel dynamically computes actual reading progress across all chapters (`readCount / totalChapters * 100%`) from reader positions and mark logs, displaying reading status (`Reading (Ch 12/45)` vs `Completed`).
- **Default Descriptions from Source Website / manga.json**:
  - Enhanced `mangasurf/reader/books.py` to pull series descriptions from `manga.json` / site metadata so every downloaded series has its real description.
- **Removed Servers Button from Sidebar**:
  - Removed duplicate Servers rail button from sidebar, consolidating all controls in `Settings › Servers & OPDS Hub`.
- **FlareSolverr Service Manager in Settings**:
  - Added FlareSolverr status widget in `Settings › Sources & FlareSolverr` with real-time test connection ping and URL configuration.
- **Fail-Safe Server & OPDS Stop Logic**:
  - Enhanced `stop_server` and `stop_opds` in Gui Api with robust socket shutdowns and thread cleanup so servers never get stuck.
  - Added Access Token / Password reveal eye button and copy button in Settings.
- **QR Code Modal Interface Switcher (Wi-Fi vs Tailscale)**:
  - Added tabbed interface in `#srv-qr-modal` allowing instant switching between Local Wi-Fi (LAN) and Tailscale VPN URLs with real-time SVG QR code re-rendering.
- **Archive Cover Auto-Extraction**:
  - `existing_cover()` in `mangasurf/covers.py` automatically extracts page 1 from `.cbz` / `.zip` archives into `cover.jpg` when no loose cover exists.

---

## [1.6.1] — Mangasurf v1.6.1: Immersive 3D Carousel, Full-Width Search, Bottom Shelves, QR Switcher & Referer Proxy

### Highlights & Fixes
- **Search Bar Full-Width Input Layout**: Fixed search input failing to expand and leaving empty space. Configured `.search-wrap` and `input[type="search"]` with `width: 100% !important; flex: 1;` so the search box stretches across the entire container with 40px icon padding.
- **Horizontal Shelves Bar at Bottom of Library**: Replaced vertical shelf tree sidebar with an animated, horizontal scrollable shelf pill bar (`#horizontal-shelves-bar`) at the bottom of the library, showing shelf counts, custom colors, lock states, and "New Shelf" creation.
- **Removed Stats Bar from Top of Library**: Cleaned up the top of the Library view by removing `#stats-strip`. Moved and enriched all statistics into the Stats page.
- **Immersive Full-Width 3D Carousel**: Expanded the 3D Depth Library Carousel to span the entire screen width with 380px viewport height, 220x330px cover cards, 3D perspective depth scaling, glowing active cards, smooth animations, progress bar, chapter range, and inline editable series description.
- **Rail Active Button Highlighting Fix**: Fixed both Settings and Servers buttons highlighting simultaneously when clicking the Servers rail button. `showView("servers")` now activates only `#rail-server-btn`.
- **QR Code Modal Interface Switcher (Wi-Fi vs. Tailscale)**: Added tabbed interface in `#srv-qr-modal` allowing instant switching between Local Wi-Fi (LAN) and Tailscale VPN URLs with real-time SVG QR code re-rendering.
- **Vibrant Stats Sources Tab**: Redesigned the Stats Sources tab with multi-colored gradient progress bars, provider badges, percentage breakdown, and active provider KPI ribbon.
- **KuraManga & KuraHentai Cover Referer Proxy**: Added `cover_needs_referer = True` to `KuraMangaSource` and `KuraHentaiSource` so `shadowabyss.com` CDN images are proxied with proper `Referer` headers, fixing blank covers in search.
- **Archive Cover Auto-Extraction**: Enhanced `existing_cover()` in `mangasurf/covers.py` to extract page 1 from `.cbz` / `.zip` archives into `cover.jpg` when no loose cover exists, guaranteeing 100% cover visibility in library.

---

## [1.6.0] — Mangasurf v1.6.0: 32 Scrapers, 3D Library Carousel, Cart Bulk Downloading, Offline Database & Suggestions

### Highlights & New Additions
- **6 New Integrated Scrapers (32 Registered Sources Total)**:
  - **Chikari (`chikari.py`)**: SvelteKit REST API scraper with structured JSON search (`/api/search`), full metadata (`/api/series/{slug}`), chapter listings, and direct CDN image extraction (`cdn.chikari.moe`).
  - **KuraManga (`kuramanga.py`)**: AJAX JSON search engine (`/search?ajax=1&keyword=`), natural chapter extraction, and high-speed `shadowabyss.com` image downloads.
  - **KuraHentai (`kurahentai.py`)**: Gallery scraper for Hentai Manga & Doujinshi with full-resolution page image streaming from `hentai.shadowabyss.com`.
  - **Hiperdex (`hiperdex.py`)**: tRPC API integration (`/api/trpc/`) with session tokens and `x-cfg-auth` signing, high-speed chapter parsing, and `r2d2storage.com` CDN image downloads.
  - **MadaraDex (`madaradex.py`)**: Madara theme scraper with `https://madaradex.org/title/<slug>/`, AJAX chapter pagination, and `cdn.madaradex.org` images.
  - **MangaK (`mangak.py`)**: Next.js SSR scraper (`mangak.io`) with structured `__NEXT_DATA__` props, instant search results (`ssrItems`), and direct CDN pages (`rx.qvzre.org`).
- **3D Depth Cover Carousel for Library**:
  - Prominent interactive 3D cover carousel at the top of the Library view with realistic perspective scaling, depth shadow, and active card prominence.
  - Navigation via forward/backward buttons, clickable dots / counter pill (`XX / XX`), keyboard left/right arrow keys, and touch swipe.
  - Underneath information panel: Prominent Title, reading progress bar and percentage (`85% Completed`), chapter range (`Chapters 01 - 50`), series status badge, genres tags, editable/customizable description with instant save, and action buttons ("Read Now", "Details", "Show in Folder").
  - Privacy and folder lock integration: Locked folder items are automatically filtered from the carousel unless unlocked.
  - Configurable Library Display Mode in Settings (`3D Carousel + Grid`, `Grid Only`, `List Rows`).
- **Bulk Downloading & Cart System**:
  - Added dedicated **Add to Cart** (`#d-cart-btn`) button next to Download in the series detail page.
  - Added **Bulk Download Cart Bar** in the Queue view with live item counter and one-click "Download All Cart Items" button to start multi-series downloads concurrently.
- **URL Support in Search Bar**:
  - Pasting any series URL from all 32 sources (or arbitrary webtoon domains) into the search bar auto-detects the source and opens the manga detail page directly.
- **Intelligent Real-Time Search Suggestions**:
  - Live floating suggestions dropdown under the omnibar as the user types, surfacing matching series titles, source prefixes (`@chikari`, `@mangadex`, `@kuramanga`), and genre tags (`#action`, `#romance`, `#isekai`).
- **Offline Manga & Hentai Database Integration**:
  - Built-in indexed local database for thousands of SFW and Hentai/NSFW manga/manhwa titles, providing instant offline search and autocomplete suggestions.
  - Configurable toggles in Settings to enable/disable database integration, SFW index, and NSFW/Hentai index.
- **Floating Live Download Notification Card**:
  - Luminous floating toast card displaying the manga cover thumbnail, chapter name, title, and animated status pill whenever a download begins or progresses.

---

## [1.5.1] — Mangasurf v1.5.1: Complete Fix Suite, Witchtoons JSON API, Tray Stability & Concurrency Guard

### Completed Fixes & Enhancements
- **Tray Restore Crash Resolved**: Fixed cross-thread UI exceptions when unhiding or restoring the desktop window from system tray by safeguarding `window.show()` and `window.restore()` calls with platform checks and state validation.
- **Search FlareSolverr Concurrency Extended**: Increased search concurrency timeout from 12s to 30s (`search_timeout` configurable), granting FlareSolverr sufficient time to solve Cloudflare Turnstile challenges across protected scrapers.
- **Witchtoons Live Scraper Architecture**: Rewritten `mangasurf/sources/witchscans.py` to target live `witchtoons.net` infrastructure. Integrated direct JSON search (`/api/search?q=`), JSON browsing (`/api/series?`), RSS feed chapter parsing (`/series/comic/<slug>/feed.xml`), and high-resolution signed WebP image extraction (`/uploads/comic-pages/<slug>/<ch>/page-<n>.webp?sig=...`).
- **Double Download Duplicate Prevention**: Added double-click locking and in-flight request debouncing in the manga detail UI (`#d-download`, `#d-queue`), paired with duplicate checks in `start_download()` and `add_to_cart()` to prevent duplicate jobs for the same series.
- **Delete All (Folder and Files) Permanent Removal**: Fixed card metadata mapping (`data-key`, `data-directory`, `data-manga`, `data-open`) in library grid so right-click context menu permanently removes the entire series directory and all archive files from disk with `shutil.rmtree()`, removes metadata from `library.json`, and cleans up the UI.
- **Search Bar Layout & Icon Buttons**: Refined search tools box padding with dedicated icon-only Search (`#search-go`) and Refine (`#search-more`) action buttons and 36px left icon padding on search inputs.
- **Search Results Sequencing & Load More**: Sequenced search requests (`activeSearchSeq`) and deduplicated URLs (`loadedSearchUrls`) ensuring instant refresh on empty/non-empty queries and infinite pagination.
- **Uncollapsed Live Queue Cards**: Live network throughput sparkline graphs, active downloading chapter indicators, real-time speed meters (`MB/s`), ETA timers, and downloaded byte sizes.
- **Queue Cleanup**: Automatically clears completed jobs from active queue rendering upon completion.

---

## [1.5.0] — Mangasurf v1.5.0: 26 Scrapers, Live Queue Overhaul, 3D Wave Visualizer & Metadata Sync

### Highlights & Fixes
- **GUI Server & OPDS Control Hub (Live Status & Device Tracking)**:
  - **Start/Stop/Restart from GUI**: One-click controls in the GUI settings and navigation rail to start, stop, or restart the LAN Web Server and OPDS 1.2 Catalog without restarting the desktop application.
  - **Live Server Status Updates**: Real-time pulsing online/offline indicators, uptime counters, active connections, and dynamic local LAN / localhost / Tailscale VPN URL resolvers with 1-click clipboard copy and browser launcher.
  - **Connected Devices & Active Sessions Monitor**: Real-time tracking of all phones, tablets, e-readers, and desktop clients accessing Mangasurf. Identifies device models (Apple iPhone, iPad, Google Pixel, etc.), OS, browser/app (Readest, Panels, Aldiko, Safari, Chrome), IP addresses, connection type (LAN vs. Tailscale), request counts, transferred data sizes, and last active endpoints.
  - **Instant Phone Pairing via QR Code**: Built-in zero-dependency SVG QR Code generator modal allowing phone cameras to scan and connect to the web reader or OPDS catalog immediately.
  - **Live Traffic & Activity Console**: Embedded terminal viewer in GUI settings streaming live HTTP calls, chapter stream requests, and security challenges with filtering.
  - **Autostart Controls**: Independent options to autostart the LAN Web Server and/or OPDS Catalog on Mangasurf launch.
- **26 Integrated High-Speed Scrapers**:
  - **SimplyHentai (`simplyhentai.py`)**: Added support for Simply-Hentai Next.js API, multi-tag combinations (`/tag/<tag1>/tag-1-<tag2>`), and full-resolution images.
  - **Witchtoons (`witchscans.py`)**: Updated Witchscans scraper to official Witchtoons architecture (`witchtoons.com` / `witchscans.com`).
  - **Hitomi.la (`hitomi.py`)**: Implemented Nozomi binary uint32 index streaming and modern `gg.js` dynamic math for high-speed AVIF/WebP image rendering.
  - **MangaDistrict (`mangadistrict.py`)**: Full Madara search, browse, AJAX chapter loading, and image parsing.
  - **Nhentai (`nhentai.py`)**: Upgraded to `SongOfTheFallen` architecture with direct tag routing, multi-category tag container parsing, and endless 25-gallery pagination.
  - **VyManga (`vymanga.py`)**: Fixed browse and search endpoints across live mirrors (`mangavyvy.net`, `mangavyvy.com`, `vymanga.net`).
- **Live Queue Overhaul (Uncollapsed)**:
  - Fixed background downloads not appearing in queue by mapping active concurrent jobs (`self._jobs`) and cart items (`self._cart`) to `get_queue()`.
  - Added `window.onEngineEvents` for real-time progress updates across GUI and LAN server.
  - Uncollapsed queue item cards displaying live speed meters, ETA timers, downloaded byte sizes, active chapter labels, and SVG network throughput sparkline graphs.
  - Automatic removal of completed jobs after finish.
- **Visuals & Search Upgrades**:
  - **3D Fullscreen Perspective Wave Canvas**: Dynamic undulating 3D perspective grid wave in centered search hero that smoothly fades out on query input.
  - **Search Layout Toggle**: One-click Grid $\leftrightarrow$ List view toggle button in search bar tools box.
  - **Centered Icon Search Buttons**: Clean, compact icon-only Search (`#search-go`) and Refine (`#search-more`) buttons.
  - **Mathematical Wave Search Loader**: Centered harmonic frequency visualizer with pulsing core orb, radar rings, and mathematical formula pill.
- **Library & Metadata Enhancements**:
  - **Automatic `manga.json` Metadata**: Writes rich series metadata on download and reads it on disk scan so no series displays as "local".
  - **Metadata Sync Tool**: CLI command `mangasurf library metadata` and context menu action to generate/sync `manga.json` for all folders.
  - **Custom Context Menu**: Right-click menu for Library and Marks cards (Read, Details, Folder, 7 Color Tags, Sync Metadata, Delete Metadata Only, Delete Everything with Files).
  - **Circular Progress Ring in Continue Reading**: Clean series title on bold first line, chapter range on sub-line, and SVG radial percentage meter.
  - **Customizable Layout Padding & Margins**: Added dropdowns in Settings for screen padding (Compact, Normal, Spacious, Wide) and card density.
- **Windows & Server Reliability**:
  - **Windows Log Rotation Fix**: Implemented `SafeRotatingFileHandler` to catch `PermissionError: [WinError 32]` lock contention on Windows without crashing logging.
  - **Server Streaming Auth Fix**: Added `mangasurf_token` session cookies and query parameter tokens so local covers and page streams never return 401 Unauthorized on mobile/LAN clients.

---

## [1.2.0] — Mangasurf Unified Release: High-Speed Multi-Source Scrapers, Omnibar & Verified Engine

### Highlights & Architecture
- **Unified Application Core**: Multi-source scraping engine with thread pooling, atomic `.part` streaming writes, connection pooling, and circuit breaker resilience.
- **Smart Search Omnibar**:
  - Direct URL auto-detection: paste any series or chapter URL to jump straight into the reader / details view.
  - Source prefix targeting: `@mangakatana query`, `@kagane query`, `weebcentral: query`, `comix: query`, `vymanga: query`, `mangadotnet: query`.
  - Tag filtering: `#action #isekai` to immediately filter by specific genres.
  - Live query autocomplete & suggestions for sources, genre tags, and search history.
- **Source Management & Toggling**:
  - Independent enable/disable switches for each source in Settings.
  - Per-source search and browse toggles.
  - Priority ranking with drag-and-drop ordering.
  - Rate limiting, politeness delays, retry counters, and custom results limit per source.
- **Advanced Genre Discovery**:
  - Unified multi-source genre union aggregation with fast 6s deadline and offline fallbacks.
  - Multi-select interactive chip picker.
  - Match mode options: *Match All (AND)* vs *Match Any (OR)*.
- **Overwritten and Integrated Scrapers**:
  - **WeebCentral** (`weebcentral_downloader`): long strip image scraping, exponential backoff, FlareSolverr integration, rate-limit tracking, natural sort ordering.
  - **MangaKatana** (`mangakatana_downloader`): full numeric genre map, `var thzq` JS array parser, search by name/author, polite request pacing.
  - **Kagane** (`kagane_downloader`): REST API integration (`yuzuki.kagane.to/api/v2`), UUID series handling, book pagination, dynamic CDN extraction.
  - **Comix / Comick** (`comix_downloader`): `comix.to` API integration, slug code parsing, chapter pagination, rich metadata mapping.
  - **VyManga** (`vymanga_downloader`): adult warning bypass, chapter list parsing, vertical reader image extraction.
  - **MangaDotNet** (`mangadotnet_downloader`): Nuxt-style packed API search unpacker, chapter list parser, direct CDN extraction.
  - **Plus 18 additional sources**: MangaDex, AsuraScans, FlameComics, DemonicScans, MadaraScans, OmegaScans, ManhwaRead, MadaraNet, Natomanga, WitchScans, WriterScans, Webtoons, Mangadass, Manhwa18, Manga18Club, HentaiAkane, Nhentai.
- **Search Relevance Engine (`filter_and_rank_query`)**:
  - Eliminates un-filtered catalog dumps from scrapers when searching.
  - Scored ranking (exact matches > prefix matches > token matches).

---

## [1.1.0] — Phone LAN Server, Local API & Keymap Configuration
- LAN server reading support via `/stream/page` and `/stream/book` with HTTP `Range` requests for instant CBZ streaming.
- Local JSON API endpoints (`/local/info`, `paths`, `books`, `reading`, `covers`, `sources`, `shelves`, `stats`).
- Custom rebindable keymaps with preset management.
- Multi-tier shelf locking and passcode privacy.

---

## [1.0.0] — Initial Foundation
- High performance desktop GUI with local JSON API bridge.
- Foliate-js reader integration for smooth scrolling and page turning.
- Multi-format exporter supporting CBZ, PDF, EPUB, and Raw Images.
- Background OPDS v1.2 catalog server.
