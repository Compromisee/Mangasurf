# Mangasurf Development Todo List (v1.7.0+)

Prioritized roadmap, task breakdown, and technical backlog for **Mangasurf**.

---

## 🎯 High Priority (Current Release v1.7.0)

- [x] **Universal Scraper Pagination**: Fixed KuraManga batch slicing and Hiperdex tRPC offset query schema (`offset = (page-1)*limit`).
- [x] **Accurate Chapter Count Tracking**: Dynamic resolution of `.cbz`/`.epub`/`.pdf` archives on disk (`ch_count = max(len(entry["chapters"]), len(items))`).
- [x] **Exact Chapter Highlight Synchronization**: Fixed `isChapterDownloaded()` to match exact numeric values and names, eliminating over-matching.
- [x] **Clean Highlight Style**: Pure emerald green background highlight (`rgba(16, 185, 129, 0.12)`) without side indicator lines.
- [x] **Instant Online Streaming Reader**: Read any chapter from all 34 sources without downloading a single file.
- [x] **Metadata & Database Integrations**: Integrated MyAnimeList (MAL / Jikan), PornhwaDB (18+), and MangaBaka for cross-source title recognition.
- [x] **Dual Metadata Architecture**: Generates both `manga.json` (chapters, local paths, pages, reading progress) and `ComicInfo.xml` (Title, Series, Writer, Genre, Rating, Year) in every folder.
- [x] **Library Maintenance Suite**: Settings tools to Rescan All Books, Fix Missing Covers, Rebuild XML & JSON, and Clean Cache.
- [x] **Title Decluttering**: Automated stripping of scanlator tags, brackets, and resolution stamps in File Explorer & OPDS.
- [x] **Removed fake sources**: Kings Manga and Kamiya Scans removed from the registry.
- [x] **Modular Plugin Architecture**: Hot-reloading of custom Python `.py` and `.source` plugins from `~/.mangasurf/sources/`.
- [x] **High-Speed `curl_cffi` Solver**: Sub-millisecond TLS JA3/JA4 Chrome 124 impersonation with automatic fallback to FlareSolverr.
- [x] **Dual Page Spread Reader**: 2-page side-by-side reading mode for desktop screens and tablets.
- [x] **Per-Chapter Downloaded Counts**: Search badges now match the detail view for bundled CBZs (fixed "1 chapter downloaded").
- [x] **Four new verified sources**: Manhwa68, ManhwaBuddy, Hentai18, ComicLand.
- [x] **Best-effort Yurivan source**: degrades gracefully behind its age gate.
- [x] **Documentation Hub**: standalone HTML doc pages linked from the landing page.
- [ ] **Verify Yurivan end-to-end** once its age gate can be passed.
- [ ] **AniList / MyAnimeList read-write sync** (v1.8.0).
- [ ] **AI OCR translation overlay** (v1.8.0).
- [ ] **E-ink-optimized reading mode** (v1.8.0).
- [x] **Complete Data Backup Hub**: Export, import, and selective deletion of search history, suggestions, and reading stats.

---

## 🚀 Medium Priority (Next Release v1.8.0)

- [ ] **AI-Assisted OCR Translation Overlay**:
  - Offline Manga-OCR / Tesseract integration to translate raw Japanese, Korean, and Chinese speech bubbles into English in real-time.
- [ ] **Cloud Sync & Tracking**:
  - Two-way progress synchronization with AniList, MyAnimeList (MAL), and Kitsu accounts.
- [ ] **PWA & Mobile Push Notifications**:
  - Web Push API support on the LAN Phone Web Server (:8577) to notify mobile users when a tracked manga releases a new chapter.
- [ ] **Multi-Threaded Hardware Image Decoding**:
  - WebAssembly (WASM) / Web Workers image resizing and decoding for instant rendering of 4K webtoon strips.

---

## 💡 Suggestions & Community Ideas

1. **Smart Audio Companion**: Ambient manga background music / sound effects generator while scrolling through action scenes.
2. **E-Ink High-Contrast Reader Profile**: Monochrome ultra-high-contrast theme with zero animations tailored for Boox, Kindle, and Kobo e-readers.
3. **Calibre & Kavita Direct Export**: One-click sync from Mangasurf into home Calibre / Kavita manga media servers.
