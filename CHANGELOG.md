# Changelog

All notable changes to **Mangasurf**, newest first.

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
