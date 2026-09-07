# 🗺️ Mangasurf Long-Term Architecture & Product Roadmap

Vision, milestones, and technical architecture evolution for **Mangasurf**.

---

## 📍 Release Roadmap

```
v1.8.0 (Current "Arctica") ─> v2.0.0 (Q4 2026) ─> v3.0.0 (2027)
- OPDS one-tap reader link  - Full WebAssembly      - Peer-to-Peer
- Read-state chapter list   - Native macOS .dmg     - Distributed Mesh
- First-chapter Read button - Multi-GPU WebGL       - Auto-Dubbing TTS
- Online chapters in reader - PWA Installable       - Smart Panel Crop
- Arctica branding + site   - Streaming reader       - P2P chapter mesh
```

---

## 🏛️ Architectural Pillars

### 1. High-Performance Modular Engine
* **Dynamic Scraper Plugins**: Complete isolation of scraper modules. Any developer or user can drop `mysite.py` into `~/.mangasurf/sources/` to instantly support a new website.
* **Dual Networking Layers**: Native `curl_cffi` C-bindings for sub-millisecond TLS JA3 fingerprint impersonation with silent FlareSolverr Docker bridge fallback.

### 2. Universal Library & Metadata Interoperability
* **Dual Format Standards**: Every downloaded series folder automatically maintains both `manga.json` (for Mangasurf internal telemetry & positions) and `ComicInfo.xml` (for ComicRack, Kavita, Komga, and Calibre compatibility).
* **Cross-Source Fuzzy Matching**: Global synonym matching so downloading a manga from one source reflects immediately across all other 33 sources.

### 3. Native Reading Experience
* **Foliate-js Custom Engine**: Continuous vertical webtoon reading with zero gaps, Dual Page (Spread) book layout, right-to-left (RTL) manga pagination, and 60fps hardware-accelerated transforms.
* **Ambient Mesh & OLED Themes**: Midnight obsidian, pure OLED black, and high-contrast Porcelain light theme.

---

## 🔮 Version Milestones

### v1.8.0: The Arctica Update (shipping)

**Mangasurf - Arctica** — `v1.8.0`.

#### Shipped in this release
- **OPDS one-tap reader link.** The OPDS catalog is now not just a copy-able
  URL but a single clickable link with the access token embedded as basic-auth
  credentials, so Thorium, Readest, Panels, Aldiko and KyBook open the catalog
  on the first tap — no username/password prompt.
- **Read-state chapter list.** The manga page's chapter list now colours each
  row by its reading state: fully-read chapters are highlighted amber-yellow,
  fully-read **and** downloaded chapters are highlighted blue, and partially
  read chapters render as an in-row horizontal progress bar filled to the read
  fraction.
- **Read button starts at chapter 1.** The prominent Read button now defaults
  to the **first** chapter when reading online (previously the last), instead
  of only the user-selected one.
- **Online chapters in the reader.** The reader's Chapters tab now lists every
  online chapter of the series (with its read state) in addition to local
  sibling folders/archives, and lets you jump between them without leaving the
  reader. Finished chapters are auto-marked read so the highlights stay fresh.
- **Arctica branding + site redesign.** Release is branded "Mangasurf - Arctica",
  version bumped to 1.8.0, and the website rebuilt in a retro-cool, rustic,
  beautiful theme.
- **Per-row chapter progress wash.** Every chapter row is its own progress bar
  — a solid, flat translucent fill (no gradient) up to the read fraction,
  painted beneath the row's text so everything stays readable. Chapter rows
  were also centered, given more padding, and a new chapter-row size slider in
  Settings drives row height and the Read Online button.
- **Fresh chapters open on page 1.** Picking a chapter from the chapter list no
  longer inherits the previous chapter's scroll offset and lands on the LAST
  page. Chapter-list navigation opens fresh (`resume: false`), while reopening
  the same book/chapter from the library or Continue-Reading still resumes
  where you left off.
- **"Read" only when fully read.** The Read pill now appears only for chapters
  actually finished (tracker read set or the reader reaching the end), never
  for one merely partway through its progress.
- **Crash-safety & error tests.** Global `error`/`unhandledrejection` handlers
  surface and de-duplicate uncaught faults, `openPath` is guarded so a throw in
  the open pipeline is contained and reported, and a suite of Playwright tests
  covers fresh-open, resume, the read-pill rule, and every error path.

#### In progress / next
- **AniList & MyAnimeList Two-Way Sync**: Automatically update "Watching / Reading" chapters on user's anime/manga tracking accounts upon reaching 100% on a chapter.
- **Offline Optical Character Recognition (OCR)**: Live on-hover speech bubble translation for raw untranslated Japanese/Korean chapters.
- **LAN Server Web Push**: Push notifications on mobile Safari / Chrome when tracked manga release new chapters.

### v2.0.0: The Universal Ecosystem Update
* **Progressive Web App (PWA)**: Installable offline reader directly from the LAN server (:8577) to iPhone/Android home screens.
* **Kavita / Komga Sync Bridge**: Direct OPDS-PS bidirectional synchronization with home media servers.
* **Native Signed Packaging**: Automated notarized `.dmg` for macOS, signed `.msi` installers for Windows, and Flatpak/Snap packages for Linux distros.
