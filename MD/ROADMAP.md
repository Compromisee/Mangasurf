# 🗺️ Mangasurf Long-Term Architecture & Product Roadmap

Vision, milestones, and technical architecture evolution for **Mangasurf**.

---

## 📍 Release Roadmap

```
v1.7.3 (Current) ──────> v1.8.0 (Q3 2026) ──────> v2.0.0 (Q4 2026) ──────> v3.0.0 (2027)
- 38 Sources            - AniList / MAL Sync     - Full WebAssembly      - Peer-to-Peer
- 100% curl_cffi        - AI OCR Translation     - Native macOS .dmg     - Distributed Mesh
- Async batch engine    - Web Push for Server    - Multi-GPU WebGL       - Auto-Dubbing TTS
- Per-chapter counts    - E-Ink Optimized Mode   - PWA Installable       - Smart Panel Crop
- Docs collection       - Verified source checks - Streaming reader       - P2P chapter mesh
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

### v1.8.0: The AI & Cloud Sync Update
* **AniList & MyAnimeList Two-Way Sync**: Automatically update "Watching / Reading" chapters on user's anime/manga tracking accounts upon reaching 100% on a chapter.
* **Offline Optical Character Recognition (OCR)**: Live on-hover speech bubble translation for raw untranslated Japanese/Korean chapters.
* **LAN Server Web Push**: Push notifications on mobile Safari / Chrome when tracked manga release new chapters.

### v2.0.0: The Universal Ecosystem Update
* **Progressive Web App (PWA)**: Installable offline reader directly from the LAN server (:8577) to iPhone/Android home screens.
* **Kavita / Komga Sync Bridge**: Direct OPDS-PS bidirectional synchronization with home media servers.
* **Native Signed Packaging**: Automated notarized `.dmg` for macOS, signed `.msi` installers for Windows, and Flatpak/Snap packages for Linux distros.
