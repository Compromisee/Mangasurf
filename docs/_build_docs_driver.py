#!/usr/bin/env python3
"""Generate all themed documentation pages."""
import os
from _build_docs import write_page, HERE, page  # noqa

# ---------------------------------------------------------------- getting-started
write_page(
    "getting-started.html",
    "Getting Started",
    "Install Mangasurf and its curl_cffi HTTP engine, then run your first download.",
    [
        ("prereqs", "Prerequisites", "fact_check"),
        ("install", "Install", "download"),
        ("verify", "Verify", "verified"),
        ("launch", "Launch", "play_circle"),
        ("quickstart", "Quick Start", "bolt"),
    ],
    """
<h2 id="prereqs"><span class="mi">fact_check</span>Prerequisites</h2>
<p>Mangasurf runs on <b>Python 3.11 or newer</b>. If you install from source you also need <code>git</code>, and for the full desktop experience <code>PyQt6</code> and <code>pywebview</code>.</p>

<h2 id="install"><span class="mi">download</span>Install</h2>
<div class="doc-callout"><p><span class="mi">info</span> Mangasurf's HTTP engine is <b>100% curl_cffi</b> — the <code>requests</code> package is not used at all. curl_cffi ships prebuilt wheels for CPython 3.8–3.13 on Linux, macOS and Windows, so there's normally <b>no compiler needed</b>.</p></div>
<pre><code># 1. The native HTTP binding
pip install curl_cffi

# 2. The rest of the project
git clone https://github.com/Compromisee/Mangasurf.git
cd Mangasurf
pip install -r requirements.txt</code></pre>
<p>Or install the published package with extras:</p>
<pre><code>pip install "mangasurf[all]"      # GUI + TUI + tray + servers
pip install "mangasurf[gui]"      # desktop app only</code></pre>

<h2 id="verify"><span class="mi">verified</span>Verify the engine</h2>
<pre><code>python -c "from mangasurf import http; print(http.get('https://cloudflare.com', timeout=10).status_code)"</code></pre>
<p>This prints <code>200</code> even on Cloudflare-fronted pages, because curl_cffi sends a genuine browser TLS/JA3+JA4 fingerprint (<code>impersonate="chrome"</code> by default).</p>

<h2 id="launch"><span class="mi">play_circle</span>Launch</h2>
<div class="doc-card-grid">
  <div class="doc-card"><div class="doc-icon"><span class="mi">window</span></div><h3>Desktop GUI</h3><p><code>python gui.py</code> — the PyQt6 app with the Foliate reader.</p></div>
  <div class="doc-card"><div class="doc-icon"><span class="mi">widgets</span></div><h3>Launcher</h3><p><code>python launcher.py</code> — pick your interface.</p></div>
  <div class="doc-card"><div class="doc-icon"><span class="mi">lan</span></div><h3>LAN / Server</h3><p><code>python server.py</code> — drive it from your phone.</p></div>
  <div class="doc-card"><div class="doc-icon"><span class="mi">menu_book</span></div><h3>OPDS Catalog</h3><p><code>python opdsserve.py</code> — stream to e-readers.</p></div>
</div>

<h2 id="quickstart"><span class="mi">bolt</span>Quick start</h2>
<pre><code># Free-text search across every enabled source
mangasurf "solo leveling"

# Target a specific source
mangasurf "@kagane solo leveling"
mangasurf "mangakatana: naruto"

# Download a whole manga (or paste a series URL)
mangasurf --url "https://mangadex.org/title/&lt;uuid&gt;" --format cbz --selection all</code></pre>
<p>See <a href="index.html">the landing page</a> or the <a href="https://github.com/Compromisee/mangasurf/blob/master/MD/SYNTAX.md">SYNTAX.md</a> CLI reference for the full command grammar.</p>
""",
)

# ---------------------------------------------------------------- sources
write_page(
    "sources.html",
    "Sources",
    "Every one of the 38 registered manga sources, how they plug in, and how to add a verified one.",
    [
        ("registry", "Registry", "lan"),
        ("add", "Add a source", "add_circle"),
        ("capabilities", "Capabilities", "tune"),
        ("adult", "Safe mode", "lock"),
        ("troubleshoot", "Dead sites", "south"),
    ],
    """
<h2 id="registry"><span class="mi">lan</span>Registry</h2>
<p>Each source is a <code>Source</code> subclass in <code>mangasurf/sources/</code>, registered in <code>sources/__init__.py</code>. The CLI, GUI and HTTP API all pick a new source up automatically — no wiring elsewhere.</p>
<div class="doc-callout"><p><span class="mi">info</span> The README source table and this page are generated from the live registry, so the row count can't drift from the code.</p></div>

<h2 id="add"><span class="mi">add_circle</span>Add a new source</h2>
<pre><code>1. write  mangasurf/sources/&lt;name&gt;.py   # a Source subclass
2. import it in mangasurf/sources/__init__.py and append to SOURCE_CLASSES
3. done — search, browse and download pick it up automatically</code></pre>
<p>Your source implements the four methods the download engine relies on:</p>
<ul>
  <li><code>search(query, **filters)</code> → list of search results</li>
  <li><code>get_manga_info(url)</code> → title / cover / description / tags</li>
  <li><code>get_chapters(url)</code> → chapters, <b>oldest first</b></li>
  <li><code>get_chapter_images(chapter)</code> → ordered page image URLs</li>
</ul>

<h2 id="capabilities"><span class="mi">tune</span>Capabilities</h2>
<table><tr><th>Attribute</th><th>Meaning</th></tr>
<tr><td><code>supports_search</code></td><td>can search by query</td></tr>
<tr><td><code>supports_browse</code></td><td>offers trending / latest discovery</td></tr>
<tr><td><code>supports_genres</code></td><td>exposes a genre list for filtering</td></tr>
<tr><td><code>supports_language</code></td><td>shows a translation-language filter</td></tr>
<tr><td><code>supports_scanlator</code></td><td>multiple releases per chapter number</td></tr>
<tr><td><code>default_series_type</code></td><td>manga / manhwa / manhua fallback</td></tr>
<tr><td><code>cover_needs_referer</code></td><td>cover CDN blocks hotlinks; proxy via Python</td></tr>
<tr><td><code>needs_flaresolverr</code></td><td>Cloudflare-protected; needs FlareSolverr</td></tr>
<tr><td><code>adult_only</code></td><td>adult-exclusive; hidden behind Safe mode</td></tr>
</table>

<h2 id="adult"><span class="mi">lock</span>Safe mode</h2>
<p>Sources flagged <code>adult_only = True</code> are hidden from filtered searches unless Safe mode is on. This keeps general-audience browsing clean while leaving adult sources one toggle away.</p>

<h2 id="troubleshoot"><span class="mi">south</span>Dead / Cloudflare sites</h2>
<div class="doc-callout warn"><p><span class="mi">warning</span> A source whose domain 404s, doesn't resolve, or sits behind Cloudflare should set <code>needs_flaresolverr = True</code> or not be registered at all. Unverified sources fail silently and drag every search down.</p></div>
<p>If a site is behind Cloudflare, start the solver on port 8191 and it will be bypassed automatically: <code>python start_flaresolverr.py</code>.</p>
""",
)

# ---------------------------------------------------------------- http-engine
write_page(
    "http-engine.html",
    "curl_cffi Engine",
    "Mangasurf's HTTP layer — real browser impersonation and a fast async batch engine.",
    [
        ("why", "Why curl_cffi", "bolt"),
        ("impersonate", "Impersonation", "fingerprint"),
        ("async", "Async engine", "speed"),
        ("api", "API", "code"),
        ("env", "Configuration", "settings"),
    ],
    """
<h2 id="why"><span class="mi">bolt</span>Why curl_cffi</h2>
<p>Mangasurf is <b>100% curl_cffi</b>. The <code>requests</code> package has been removed entirely; every page fetch, image download and batch request flows through <code>mangasurf/http.py</code>. curl_cffi is a thin, native C binding over libcurl and is much faster per request than urllib3, the engine behind requests.</p>

<h2 id="impersonate"><span class="mi">fingerprint</span>Browser impersonation</h2>
<p>By default every request impersonates a real Chrome over TLS, sending a genuine JA3/JA4 fingerprint. Cloudflare and Akamai bot checks that reject vanilla clients are passed automatically.</p>
<pre><code># Switch the fingerprint at runtime
MANGASURF_IMPERSONATE=safari python gui.py
MANGASURF_IMPERSONATE=firefox python gui.py</code></pre>

<h2 id="async"><span class="mi">speed</span>Fast async engine</h2>
<p>The chapter downloader sprays every page across a <b>single libcurl multi handle</b> (<code>http.download_many</code> / <code>Source.download_many</code>), so a 30-page chapter arrives in roughly one page's latency instead of thirty round trips. Downloads remain atomic: each page streams to a <code>.part</code> file and is renamed only after magic-byte validation.</p>
<pre><code>from mangasurf import http

responses = http.fetch_many([url1, url2, url3], timeout=15)   # concurrent GET
ok = http.download_many([{"url": u, "path": p}, ...])         # concurrent stream</code></pre>

<h2 id="api"><span class="mi">code</span>Requests-style API</h2>
<p>Source plugins keep calling <code>session.get(...).json()</code>, and the exception names you're used to still work — they're aliased to curl_cffi exceptions (<code>RequestException</code>, <code>Timeout</code>, <code>SSLError</code>, <code>HTTPError</code>, ...).</p>

<h2 id="env"><span class="mi">settings</span>Configuration</h2>
<table><tr><th>Variable</th><th>Effect</th></tr>
<tr><td><code>MANGASURF_IMPERSONATE</code></td><td>Browser profile (default <code>chrome</code>)</td></tr>
<tr><td><code>HTTP_PROXY</code> / <code>HTTPS_PROXY</code></td><td>Proxy support for curl_cffi</td></tr>
</table>
""",
)

# ---------------------------------------------------------------- downloading
write_page(
    "downloading.html",
    "Downloading",
    "Formats, concurrency, crash-safe resume, and accurate per-chapter downloaded counts.",
    [
        ("formats", "Formats", "folder"),
        ("concurrency", "Concurrency", "speed"),
        ("resume", "Resume", "restart_alt"),
        ("counts", "Accurate counts", "checklist"),
        ("queue", "Queue", "queue"),
    ],
    """
<h2 id="formats"><span class="mi">folder</span>Formats</h2>
<p>Download a manga as <b>CBZ</b>, <b>PDF</b>, <b>EPUB</b> or raw image folders, with per-chapter or bundled naming. You can also request several formats at once and output them side by side.</p>

<h2 id="concurrency"><span class="mi">speed</span>Concurrency</h2>
<table><tr><th>Setting</th><th>Default</th><th>Meaning</th></tr>
<tr><td><code>chapter_workers</code></td><td>3</td><td>chapters downloaded in parallel</td></tr>
<tr><td><code>image_workers</code></td><td>6</td><td>pages per chapter (overridden by the async engine)</td></tr>
<tr><td><code>use_async</code></td><td><span class="ver">true</span></td><td>curl_cffi batch engine for images</td></tr>
<tr><td><code>retries</code></td><td>5</td><td>retries per page</td></tr>
<tr><td><code>delay</code></td><td>0.5s</td><td>polite delay between chapters</td></tr>
</table>

<h2 id="resume"><span class="mi">restart_alt</span>Crash-safe resume</h2>
<p>Images stream to a <code>.part</code> file and are renamed only after validation. A crashed run resumes on the next pass — finished pages are skipped, missing ones refetched. Completed chapters are checkpointed so they are never redownloaded.</p>

<h2 id="counts"><span class="mi">checklist</span>Accurate per-chapter counts</h2>
<p>A bundled CBZ holds many chapters but is a single file. Mangasurf counts the <b>chapters</b> (read from each series' <code>manga.json</code> via <code>downloaded_status</code>) rather than the file count, so the search-result badge and the manga detail view always agree — no more "1 Downloaded" on a 30-chapter bundle.</p>

<h2 id="queue"><span class="mi">queue</span>Download queue</h2>
<p>Queue multiple series and download them in parallel. The cart / queue respects the chapter selection (all, new, a range, or specific picks), and each job can target a different <code>format</code>, <code>language</code>, and preferred <code>scanlator</code> group.</p>
""",
)

# ---------------------------------------------------------------- roadmap
write_page(
    "roadmap.html",
    "Roadmap",
    "Where Mangasurf is going — the current release, next milestones, and what's on the backlog.",
    [
        ("line", "Release line", "timeline"),
        ("173", "In v1.7.3", "check_circle"),
        ("180", "Next: v1.8.0", "flag"),
        ("200", "Later: v2.0+", "rocket_launch"),
    ],
    """
<h2 id="line"><span class="mi">timeline</span>Release line</h2>
<pre><code>v1.7.3 (now) ──→ v1.8.0 (Q3 2026) ──→ v2.0.0 (Q4 2026) ──→ v3.0.0 (2027)
- 38 Sources         - AniList / MAL sync   - WebAssembly reader  - Peer-to-peer mesh
- curl_cffi engine   - AI OCR translation   - Native macOS .dmg   - Distributed network
- Per-chapter counts - E-ink mode           - PWA installable    - Auto-dubbing TTS</code></pre>

<h2 id="173"><span class="mi">check_circle</span>Shipped in v1.7.3</h2>
<ul>
  <li><b>38 sources</b>, including the new verified <span class="ver">Manhwa68</span>, <span class="ver">ManhwaBuddy</span>, <span class="ver">Hentai18</span> and <span class="ver">ComicLand</span>, plus a best-effort <span class="ver">Yurivan</span>.</li>
  <li>The HTTP layer is <b>100% curl_cffi</b> with a fast async batch engine.</li>
  <li>Fixed search badges that said “1 chapter downloaded” for bundled CBZs.</li>
  <li>Removed the fake <span class="ver">Kings Manga</span> and <span class="ver">Kamiya Scans</span> sources.</li>
</ul>

<h2 id="180"><span class="mi">flag</span>Next: v1.8.0</h2>
<ul>
  <li>AniList / MyAnimeList read &amp; write sync.</li>
  <li>AI-powered OCR chapter translation overlay.</li>
  <li>E-ink-optimized reading mode.</li>
  <li>Web push notifications for the LAN server.</li>
</ul>

<h2 id="200"><span class="mi">rocket_launch</span>Later: v2.0+</h2>
<ul>
  <li>WebAssembly renderer and PWA install.</li>
  <li>Multi-GPU WebGL page rendering.</li>
  <li>Distributed / peer-to-peer chapter mesh.</li>
</ul>
""",
)

# ---------------------------------------------------------------- troubleshooting
write_page(
    "troubleshooting.html",
    "Troubleshooting",
    "Fix curl_cffi installs, Cloudflare walls, slow downloads, and reader issues.",
    [
        ("curl", "curl_cffi install", "download"),
        ("cloudflare", "Cloudflare walls", "shield"),
        ("slow", "Slow downloads", "speed"),
        ("counts", "Wrong counts", "checklist"),
        ("paging", "One page only", "pages"),
        ("covers", "Missing covers", "image"),
        ("yurivan", "Yurivan &amp; dead sites", "bug_report"),
    ],
    """
<h2 id="curl"><span class="mi">download</span>curl_cffi won't install</h2>
<div class="doc-callout"><p><span class="mi">info</span> Wheels are prebuilt for CPython 3.8–3.13, so on a normal setup this should never happen. If your platform has no wheel, build from source:</p></div>
<pre><code># Linux build deps
sudo apt install libcurl4-openssl-dev python3-dev
pip install --no-binary curl_cffi curl_cffi

# Fedora
sudo dnf install libcurl-devel</code></pre>

<h2 id="cloudflare"><span class="mi">shield</span>“Just a moment...” / Cloudflare 403</h2>
<p>This is a bot wall. Two fixes:</p>
<ol>
  <li>Start <b>FlareSolverr</b> on port 8191 (<code>python start_flaresolverr.py</code>) for the handful of protected sources.</li>
  <li>Or switch the browser fingerprint: <code>MANGASURF_IMPERSONATE=firefox python gui.py</code>.</li>
</ol>

<h2 id="slow"><span class="mi">speed</span>Downloads are slow</h2>
<p>Confirm <code>use_async</code> is on (default). Behind a proxy, curl_cffi honors <code>HTTP_PROXY</code> / <code>HTTPS_PROXY</code> — set them before launching. The batch engine avoids one round-trip per page, so a whole chapter usually arrives in about one page's latency.</p>

<h2 id="counts"><span class="mi">checklist</span>Wrong downloaded count</h2>
<p>Refresh the library (Settings → <b>Rescan All Books</b>) so each series' <code>manga.json</code> chapter list is current; the badge reads from there.</p>

<h2 id="paging"><span class="mi">pages</span>“Load more” says No More Results after one page</h2>
<p>Several sources used to ignore the page number and hand back the same first
page every time, so the front-end deduplicated them into nothing. This is
fixed for <b>comicland</b> (its API paginates by a row <code>offset</code>, not
<code>?page=</code>), <b>mangatitan</b> (pages ≥2 use a blog-archive layout),
and <b>yurivan</b> (it now slices by page). On <b>mangak</b> the Trending
browse is a static top-50 list by design — that page genuinely has no page 2,
so use search, which paginates.</p>

<h2 id="covers"><span class="mi">image</span>Covers not loading on a source</h2>
<p>If covers show a placeholder or never render, the host is refusing a
cross-origin browser request (usually a wrong Referer) — MangaDex, Webtoons,
Manhwa68, Hentai18 and Yurivan are all hotlink-sensitive. Those thumbnails are
routed through <code>proxy_cover</code>, which fetches the image in Python with
the right Referer and hands back a data URI. If one still fails, the host's
CDN may have rotated its URL scheme; the cover URL under
<code>~/.mangasurf/logs</code> will show what happened.</p>

<h2 id="yurivan"><span class="mi">bug_report</span>Yurivan returns nothing / dead sources</h2>
<p><b>Yurivan</b> gates every page behind a client-side age gate, so server-side scraping is best-effort — prefer the other adult sources. For any source that times out or 404s, check it isn't Cloudflare-protected (the source should set <code>needs_flaresolverr</code>) and confirm the domain still resolves.</p>

<div class="doc-callout ok"><p><span class="mi">check_circle</span> Still stuck? Open an issue on GitHub with the source id, the query, and the exact URL — the log file under <code>~/.mangasurf/</code> helps a lot.</p></div>
""",
)
