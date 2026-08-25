#!/usr/bin/env python3
"""Regenerate every standalone documentation page for the Mangasurf site.

Each output HTML is fully self-contained (inline theme CSS) and mirrors the
landing page (docs/index.html) exactly: same CSS variables, fonts, Material
Symbols icon system, glass nav, moving-mesh background and footer.

Run with:  python docs/_build_docs.py
"""

import os

HERE = os.path.abspath(os.path.dirname(__file__))
theme = open(os.path.join(HERE, ".theme.css"), encoding="utf-8").read()

# Extra styles for doc reading content, built on the theme variables.
DOC_CSS = """
/* ── Docs reading layout (built on the landing theme) ─────────────────── */
.doc-main { padding: 40px 0 20px; }
.doc-head { text-align: center; max-width: 860px; margin: 0 auto 40px; }
.doc-head .section-tag { margin-bottom: 10px; }
.doc-head h1 { font-size: clamp(30px, 5vw, 52px); font-weight: 900; letter-spacing: -0.04em; margin-bottom: 14px; }
.doc-head p { color: var(--text-muted); font-size: 16px; max-width: 720px; margin: 0 auto; }
.doc-toc { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin: 0 auto 44px; max-width: 820px; }
.doc-toc a { padding: 7px 14px; border-radius: 999px; background: var(--bg-surface); border: 1px solid var(--border);
  color: var(--text-muted); font-size: 13px; font-weight: 600; text-decoration: none; transition: all .2s; }
.doc-toc a:hover { color: var(--accent); border-color: var(--accent); box-shadow: 0 0 16px var(--accent-glow); }
.doc-content { max-width: 860px; margin: 0 auto; }
.doc-content h2 { font-size: 24px; font-weight: 800; letter-spacing: -0.02em; color: var(--text-main);
  margin: 46px 0 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.doc-content h2 .mi { color: var(--accent); vertical-align: -4px; margin-right: 6px; }
.doc-content h3 { font-size: 18px; font-weight: 800; color: var(--text-main); margin: 28px 0 10px; }
.doc-content p { color: var(--text-muted); margin: 0 0 14px; }
.doc-content ul, .doc-content ol { color: var(--text-muted); margin: 0 0 16px; padding-left: 22px; }
.doc-content li { margin: 6px 0; }
.doc-content code { font-family: var(--font-mono); background: var(--bg-surface-elevated);
  border: 1px solid var(--border); padding: 2px 7px; border-radius: var(--radius-sm); font-size: 0.86em; color: var(--accent); }
.doc-content pre { background: var(--bg-surface-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-md); padding: 16px 18px; overflow: auto; margin: 0 0 18px; }
.doc-content pre code { background: none; border: 0; color: var(--text-main); padding: 0; }
.doc-content table { width: 100%; border-collapse: collapse; margin: 16px 0 22px; font-size: 0.92em; }
.doc-content th, .doc-content td { border: 1px solid var(--border); padding: 10px 14px; text-align: left; color: var(--text-muted); }
.doc-content th { background: var(--bg-surface); color: var(--text-main); font-weight: 700; }
.doc-content a { color: var(--accent); text-decoration: none; }
.doc-content a:hover { text-decoration: underline; }
.doc-callout { border-left: 3px solid var(--accent); background: var(--bg-surface);
  border-radius: 0 var(--radius-md) var(--radius-md) 0; padding: 16px 18px; margin: 20px 0; }
.doc-callout.warn { border-left-color: var(--amber); }
.doc-callout.err { border-left-color: var(--danger); }
.doc-callout.ok { border-left-color: var(--success); }
.doc-callout p { margin: 0; }
.doc-card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin: 22px 0; }
.doc-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
  padding: 22px; transition: all .25s; }
.doc-card:hover { border-color: var(--accent); box-shadow: 0 0 24px var(--accent-glow); transform: translateY(-2px); }
.doc-card .doc-icon { display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px;
  border-radius: var(--radius-md); background: rgba(56,189,248,.12); color: var(--accent); }
.doc-card h3 { margin: 14px 0 6px; }
.doc-card p { margin: 0; font-size: 14px; }
.ver { color: var(--accent); font-weight: 600; }
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0; }
@media (max-width: 640px) { .nav-links { display: none; } }

/* ── Docs sidebar (expandable tree, like most docs sites) ─────────────── */
.docs-layout {
  display: grid;
  grid-template-columns: 268px minmax(0, 1fr);
  gap: 40px;
  align-items: start;
  max-width: 1220px;
  margin: 0 auto;
}
.docs-sidebar {
  position: sticky;
  top: 96px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 18px 14px;
  backdrop-filter: blur(16px);
  box-shadow: var(--shadow-glass);
}
.sidebar-brand {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; font-weight: 800; letter-spacing: .08em;
  text-transform: uppercase; color: var(--text-dim);
  padding: 0 8px 14px; margin-bottom: 8px; border-bottom: 1px solid var(--border);
}
.sidebar-brand .mi { color: var(--accent); }
.dtree { display: flex; flex-direction: column; gap: 4px; }
.dtree-group { border-radius: var(--radius-md); overflow: hidden; }
.dtree-group > .dtree-toggle {
  width: 100%; display: flex; align-items: center; gap: 10px;
  background: none; border: 0; cursor: pointer;
  color: var(--text-muted); font-family: var(--font-ui);
  font-size: 14px; font-weight: 700; text-align: left;
  padding: 9px 10px; border-radius: var(--radius-md); transition: all .18s;
}
.dtree-group > .dtree-toggle:hover { background: rgba(255,255,255,.06); color: var(--text-main); }
.dtree-group.open > .dtree-toggle { background: rgba(56,189,248,.12); color: var(--text-main); }
.dtree-group .chevron { display: inline-flex; color: var(--text-dim); transition: transform .18s; margin-left: auto; }
.dtree-group.open .chevron { transform: rotate(90deg); }
.dtree-children { display: none; flex-direction: column; gap: 2px; padding: 4px 6px 6px; }
.dtree-group.open .dtree-children { display: flex; }
.dtree-children a {
  display: flex; align-items: center; gap: 8px;
  color: var(--text-muted); text-decoration: none; font-size: 13px; font-weight: 500;
  padding: 7px 10px; border-radius: var(--radius-sm); transition: all .15s;
}
.dtree-children a .mi { font-size: 15px; color: var(--text-dim); }
.dtree-children a:hover { color: var(--text-main); background: rgba(255,255,255,.05); }
.dtree-children a.active { color: var(--accent); background: rgba(56,189,248,.1); }
.dtree-children a.active .mi { color: var(--accent); }
.docs-panel-toggle {
  display: none; align-items: center; gap: 8px; width: 100%;
  background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md);
  color: var(--text-main); font-family: var(--font-ui); font-size: 14px; font-weight: 700;
  padding: 12px 16px; cursor: pointer; margin: 0 0 20px; backdrop-filter: blur(12px);
}
@media (max-width: 860px) {
  .docs-layout { grid-template-columns: 1fr; gap: 0; }
  .docs-sidebar { display: none; position: fixed; inset: 0 auto 0 0; z-index: 60;
    max-height: 100vh; height: 100vh; width: 300px; border-radius: 0 20px 20px 0; padding: 22px 16px; }
  .docs-sidebar.show { display: block; }
  .docs-panel-toggle { display: flex; }
}
/* docs-body wraps the head + content so it sits next to the sidebar. */
.docs-body { min-width: 0; }
@media (max-width: 640px) { .nav-links { display: none; } }
"""

# Moving-mesh background JS (same as the landing page).
MESH_JS = """
(function initMeshCanvas() {
  const canvas = document.getElementById('mesh-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let width, height;
  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  }
  window.addEventListener('resize', resize);
  resize();
  const orbs = [
    { x: 0.2, y: 0.3, r: 420, color: 'rgba(56, 189, 248, 0.18)', vx: 0.0004, vy: 0.0003 },
    { x: 0.8, y: 0.2, r: 480, color: 'rgba(129, 140, 248, 0.16)', vx: -0.0003, vy: 0.0004 },
    { x: 0.5, y: 0.7, r: 520, color: 'rgba(192, 132, 252, 0.14)', vx: 0.0003, vy: -0.0003 },
    { x: 0.1, y: 0.8, r: 380, color: 'rgba(16, 185, 129, 0.12)', vx: 0.0005, vy: -0.0004 },
    { x: 0.9, y: 0.9, r: 440, color: 'rgba(251, 191, 36, 0.10)', vx: -0.0004, vy: -0.0002 },
  ];
  let time = 0;
  function animate() {
    time += 1;
    ctx.clearRect(0, 0, width, height);
    for (const orb of orbs) {
      const cx = (orb.x + Math.sin(time * orb.vx) * 0.15) * width;
      const cy = (orb.y + Math.cos(time * orb.vy) * 0.15) * height;
      const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, orb.r);
      grad.addColorStop(0, orb.color);
      grad.addColorStop(1, 'rgba(7, 8, 12, 0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(cx, cy, orb.r, 0, Math.PI * 2);
      ctx.fill();
    }
    requestAnimationFrame(animate);
  }
  animate();
})();
"""

MENU = {
    "getting-started.html": ("rocket_launch", "Getting Started"),
    "sources.html": ("hub", "Sources"),
    "http-engine.html": ("bolt", "curl_cffi Engine"),
    "downloading.html": ("download", "Downloading"),
    "roadmap.html": ("map", "Roadmap"),
    "troubleshooting.html": ("build", "Troubleshooting"),
}


#: Tree of every doc page and its on-page sections (anchor -> label), shown in
#: the expandable sidebar. The "current" page's group is expanded +
#: highlighted; every other group is collapsed to keep the tree scannable.
DOC_TREE = {
    "getting-started.html": ("rocket_launch", "Getting Started", [
        ("prereqs", "Prerequisites", "fact_check"),
        ("install", "Install", "download"),
        ("verify", "Verify", "verified"),
        ("launch", "Launch", "play_circle"),
        ("quickstart", "Quick Start", "bolt"),
    ]),
    "sources.html": ("hub", "Sources", [
        ("registry", "Registry", "lan"),
        ("add", "Add a source", "add_circle"),
        ("capabilities", "Capabilities", "tune"),
        ("adult", "Safe mode", "lock"),
        ("troubleshoot", "Dead sites", "south"),
    ]),
    "http-engine.html": ("bolt", "curl_cffi Engine", [
        ("why", "Why curl_cffi", "bolt"),
        ("impersonate", "Impersonation", "fingerprint"),
        ("async", "Async engine", "speed"),
        ("api", "API", "code"),
        ("env", "Configuration", "settings"),
    ]),
    "downloading.html": ("download", "Downloading", [
        ("formats", "Formats", "folder"),
        ("concurrency", "Concurrency", "speed"),
        ("resume", "Resume", "restart_alt"),
        ("counts", "Accurate counts", "checklist"),
        ("queue", "Queue", "queue"),
    ]),
    "roadmap.html": ("map", "Roadmap", [
        ("line", "Release line", "timeline"),
        ("173", "In v1.7.3", "check_circle"),
        ("180", "Next: v1.8.0", "flag"),
        ("200", "Later: v2.0+", "rocket_launch"),
    ]),
    "troubleshooting.html": ("build", "Troubleshooting", [
        ("curl", "curl_cffi install", "download"),
        ("cloudflare", "Cloudflare walls", "shield"),
        ("slow", "Slow downloads", "speed"),
        ("counts", "Wrong counts", "checklist"),
        ("yurivan", "Yurivan &amp; dead sites", "bug_report"),
    ]),
}

SIDEBAR_JS = """
(function() {
  var toggle = document.getElementById('docs-panel-toggle');
  var panel = document.getElementById('docs-panel');
  if (toggle && panel) {
    toggle.addEventListener('click', function() {
      panel.classList.toggle('show');
    });
    // Close the drawer when a link inside it is clicked (mobile).
    panel.addEventListener('click', function(e) {
      var a = e.target.closest('a');
      if (a && window.matchMedia('(max-width: 860px)').matches) {
        panel.classList.remove('show');
      }
    });
  }
  // Chevron groups expand/collapse.
  document.querySelectorAll('.dtree-group > .dtree-toggle').forEach(function(btn) {
    btn.addEventListener('click', function() {
      btn.parentElement.classList.toggle('open');
    });
  });
})();
"""


#: The page currently being rendered, so ``page()`` can expand its sidebar
#: group. ``write_page`` sets it before rendering each page.
_CURRENT_PAGE = "getting-started.html"


def _current_page() -> str:
    return _CURRENT_PAGE


def _sidebar_html(current: str, version: str) -> str:
    groups = []
    for href, (icon, name, sections) in DOC_TREE.items():
        is_current = href == current
        open_attr = " open" if is_current else ""
        active_page = ""
        active_href = href if is_current else ""
        li = [f"""
        <div class="dtree-group{open_attr}">
          <button type="button" class="dtree-toggle"
                  aria-expanded="{'true' if is_current else 'false'}">
            <span class="mi">{icon}</span>{name}
            <span class="chevron"><span class="mi">chevron_right</span></span>
          </button>
          <div class="dtree-children">"""]
        for anchor, label, sicon in sections:
            # On the current page, section links are same-page (no .html). On
            # other pages they deep-link into that page's anchor.
            target = f"{href}#{anchor}" if not is_current else f"#{anchor}"
            cls = "active" if is_current and False else ""
            li.append(f"""
            <a href="{target}" class="{cls}"><span class="mi">{sicon}</span>{label}</a>""")
        li.append("""
          </div>
        </div>""")
        groups.append("".join(li))
    return f"""
<div class="sidebar-brand"><span class="mi">menu_book</span>Documentation · v{version}</div>
<nav class="dtree">{"".join(groups)}</nav>"""


def page(title, tagline, toc, content, version="1.7.3", sources=38,
         current=None):
    current = current or _current_page()
    nav_links = "".join(
        f'<li><a href="{href}" class="nav-link"><span class="mi">{icon}</span>{name}</a></li>'
        for href, (icon, name) in MENU.items()
    )
    toc_html = "".join(
        f'<a href="#{anchor}"><span class="mi">{itype}</span>{text}</a>'
        for anchor, text, itype in toc
    )
    sidebar = _sidebar_html(current, version)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Mangasurf Documentation</title>
<meta name="description" content="{tagline}">
<link rel="icon" type="image/svg+xml" href="icon.svg">
<link rel="alternate icon" href="icon.ico">
<link rel="apple-touch-icon" href="icon.png">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,300..700,0..1,0">
<style>{theme}
{DOC_CSS}
</style>
</head>
<body>
<canvas id="mesh-canvas"></canvas>
<div class="ambient-grid-overlay"></div>

<header class="container" style="padding-top:16px;">
  <nav class="site-nav">
    <a href="index.html" class="nav-brand">
      <div class="brand-icon-box" style="padding:0;overflow:hidden;background:none;border:none">
        <img src="icon.svg" alt="Mangasurf Logo" style="width:36px;height:36px;object-fit:contain;border-radius:9px" />
      </div>
      <span>MANGASURF</span>
    </a>
    <ul class="nav-links">{nav_links}</ul>
    <a href="index.html" class="btn btn-primary nav-cta" style="padding:8px 18px;font-size:13px">
      <span class="mi">arrow_back</span>Back to Home
    </a>
  </nav>
</header>

<main class="doc-main container">
  <button type="button" class="docs-panel-toggle" id="docs-panel-toggle">
    <span class="mi">menu_open</span>Documentation contents
  </button>
  <div class="docs-layout">
    <aside class="docs-sidebar" id="docs-panel">
      {sidebar}
    </aside>
    <div class="docs-body">
      <section class="doc-head">
        <div class="section-tag"><span class="mi">menu_book</span> Documentation</div>
        <h1 class="text-gradient">{title}</h1>
        <p>{tagline}</p>
        <div class="doc-toc">{toc_html}</div>
        <div class="hero-pill-badge" style="display:inline-flex">
          <span class="pulse-dot"></span>
          <span>Mangasurf v{version} · {sources} Sources</span>
        </div>
      </section>

      <div class="doc-content">
{content}
      </div>
    </div>
  </div>
</main>

<footer>
  <div class="container">
    <div class="footer-grid">
      <div class="footer-col">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
          <div class="brand-icon-box" style="width:32px;height:32px;padding:0;overflow:hidden;background:none;border:none">
            <img src="icon.svg" alt="Mangasurf Logo" style="width:32px;height:32px;object-fit:contain;border-radius:8px" />
          </div>
          <strong style="font-size:18px;letter-spacing:-0.02em">MANGASURF</strong>
        </div>
        <p style="color:var(--text-muted);font-size:13px;line-height:1.6;max-width:320px">
          Open-source manga ecosystem, omnibar search, and high-performance downloader across {sources} registered sources.
        </p>
      </div>
      <div class="footer-col">
        <h4>Documentation</h4>
        <ul>
          <li><a href="getting-started.html">Getting Started</a></li>
          <li><a href="sources.html">Sources</a></li>
          <li><a href="http-engine.html">curl_cffi Engine</a></li>
          <li><a href="downloading.html">Downloading</a></li>
          <li><a href="roadmap.html">Roadmap</a></li>
          <li><a href="troubleshooting.html">Troubleshooting</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>On GitHub</h4>
        <ul>
          <li><a href="https://github.com/Compromisee/mangasurf/blob/master/MD/SYNTAX.md">SYNTAX.md (CLI Guide)</a></li>
          <li><a href="https://github.com/Compromisee/mangasurf/blob/master/MD/FEATURES.md">FEATURES.md</a></li>
          <li><a href="https://github.com/Compromisee/mangasurf/blob/master/MD/AGENT.md">AGENT.md (Data Schema)</a></li>
          <li><a href="https://github.com/Compromisee/mangasurf/blob/master/MD/CHANGELOG.md">CHANGELOG.md</a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4>Project</h4>
        <ul>
          <li><a href="https://github.com/Compromisee/mangasurf" target="_blank">GitHub Repository</a></li>
          <li><a href="https://github.com/Compromisee/mangasurf/issues" target="_blank">Issue Tracker</a></li>
          <li><a href="https://github.com/Compromisee/mangasurf/releases" target="_blank">Release Downloads</a></li>
        </ul>
      </div>
    </div>
    <div class="footer-bottom">
      <span>Mangasurf v{version} &bull; Open source</span>
      <span>{sources} Sources &bull; Foliate Reader &bull; PyQt6 &bull; Textual TUI</span>
    </div>
  </div>
</footer>
<script>{MESH_JS}
{SIDEBAR_JS}</script>
</body>
</html>
"""


def write_page(path, title, tagline, toc, content):
    global _CURRENT_PAGE
    _CURRENT_PAGE = path
    out = page(title, tagline, toc, content, current=path)
    with open(os.path.join(HERE, path), "w", encoding="utf-8") as f:
        f.write(out)
    print(f"wrote {path} ({len(out)} bytes)")


if __name__ == "__main__":
    raise SystemExit("import me from build_docs.py driver")
