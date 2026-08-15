# Vendored third-party code

## foliate-js

The reading engine under `readerm/reader/foliate/` is a vendored copy of
[foliate-js](https://github.com/johnfactotum/foliate-js) by John Factotum,
used under the MIT Licence. The full licence text is kept alongside the code
at `readerm/reader/foliate/LICENSE`.

* Upstream commit: `78914aef4466eb960965702401634c2cb348e9b1`
* Fetched: 2026-08-03

### Why the engine and not the Foliate application

Foliate itself is a GTK4 / GJS / WebKitGTK application and does not run on
Windows. Checked rather than assumed — MSYS2, the only realistic Windows GTK
channel, has **no** `gjs` and **no** `webkitgtk` package. `foliate-js`, by
contrast, contains no GTK, GJS or Node API calls at all, so it runs unchanged
in WebView2 on Windows. This is the same split Readest made when it rewrote
Foliate for multiple platforms.

### Local changes

The vendored files are unmodified. Manga-specific behaviour is added
*alongside* them in `readerm/reader/app/manga-view.js` rather than by patching
upstream, so the engine can be re-based on a newer commit without merge pain.

The one thing that had to be built rather than reused is continuous vertical
("webtoon") reading: comics are routed to `fixed-layout.js`, whose entire
attribute surface is `static observedAttributes = ['zoom']`. `flow: scrolled`
exists only in `paginator.js`, which handles reflowable text, so upstream has
no long-strip mode.

### Files deliberately omitted

* `vendor/pdfjs/*.map` — 7.7 MB of debug source maps.
* `vendor/pdfjs/cmaps/` — 1.7 MB of CJK encoding tables, only needed for PDFs
  using those encodings.

Dropping them takes the vendored tree from 13 MB to 4 MB.
