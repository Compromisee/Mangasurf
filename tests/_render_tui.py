"""Headless TUI screenshot generator.

Drives the real MangasurfTUI app through Textual's ``run_test`` and exports
each tab as an SVG -> PNG. Search results, preview metadata and covers are
injected so the screenshots look like a live session without any network.
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

# Covers and output live inside the repo so they persist (no /tmp access
# guarantees here). Generated on the fly from a palette so the screenshots are
# deterministic and offline.
_COVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "tests", "_tui_covers")
_os = os
DOCS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCES = [
    ("mangadex", "MangaDex"), ("asurascans", "Asura Scans"),
    ("weebcentral", "Weeb Central"), ("kagane", "Kagane"),
    ("natomanga", "Natomanga"), ("comix", "Comix"),
]


def _make_covers():
    """Generate a small set of stylised manga-cover PNGs deterministically."""
    import os as _os
    _os.makedirs(_COVER_DIR, exist_ok=True)
    from PIL import Image, ImageDraw
    import math
    specs = {
        "solo":  ("#7cc7ff", "#123a63", "#0b1c2e"),   # ice-blue
        "chainsaw": ("#ff6b4a", "#5a1414", "#2b0808"),  # red
        "onepiece": ("#ffe08a", "#a53d12", "#3a1204"),  # gold-orange
        "bluelock": ("#9adfff", "#0a4f7a", "#04263c"),  # cyan
        "jjk":  ("#c9a0ff", "#3a1a5a", "#140626"),   # violet
    }
    def _hex(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    for name, (top, mid, bot) in specs.items():
        path = _os.path.join(_COVER_DIR, f"{name}.png")
        if _os.path.isfile(path):
            continue
        topc, midc, botc = _hex(top), _hex(mid), _hex(bot)
        img = Image.new("RGB", (400, 560), botc)
        dr = ImageDraw.Draw(img)
        # vertical gradient from top colour into background
        for y in range(560):
            t = y / 560
            c = tuple(int(topc[i] + (botc[i] - topc[i]) * t) for i in range(3))
            dr.line([(0, y), (400, y)], fill=c)
        # glowing orb / sun behind the title (concentric rings)
        cx, cy, r = 200, 190, 110
        for i in range(r, 0, -4):
            ring = tuple(min(255, int(topc[j] * (0.35 + 0.65 * (i / r))))
                         for j in range(3))
            dr.ellipse([cx - i, cy - i, cx + i, cy + i], fill=ring)
        # terrain bands
        dr.rectangle([0, 360, 400, 560], fill=midc)
        dr.rectangle([0, 430, 400, 470], fill=botc)
        dr.rectangle([0, 480, 400, 505], fill=topc)
        # top + bottom title strips (dark)
        dr.rectangle([40, 30, 360, 92], fill=(0, 0, 0))
        dr.rectangle([40, 495, 360, 545], fill=(0, 0, 0))
        img.save(path)
    return


def _cover_for(title):
    """Return the cover PNG path for a title (workspace-relative)."""
    _make_covers()
    by_title = {
        "Solo Leveling": "solo", "Chainsaw Man": "chainsaw",
        "One Piece": "onepiece", "Blue Lock": "bluelock",
        "Jujutsu Kaisen": "jjk", "Vinland Saga": "solo",
        "Frieren": "bluelock", "Kaiju No. 8": "onepiece",
        "Dandadan": "chainsaw", "Sakamoto Days": "jjk",
    }
    return _os.path.join(_COVER_DIR, f"{by_title.get(title, 'solo')}.png")


def make_results():
    from mangasurf.tui import MangasurfTUI
    import mangasurf.console as console
    out = []
    titles = ["Solo Leveling", "Chainsaw Man", "One Piece", "Blue Lock",
              "Jujutsu Kaisen", "Vinland Saga", "Frieren", "Kaiju No. 8",
              "Dandadan", "Sakamoto Days"]
    for i, title in enumerate(titles):
        sid, name = SOURCES[i % len(SOURCES)]
        out.append({
            "title": title,
            "url": f"https://example.com/{title.replace(' ', '-').lower()}",
            "source": sid,
            "source_name": name,
            "latest": "Ch. 127" if i % 3 else "Ch. 45",
            "tags": ["Action", "Fantasy"],
            "cover": _cover_for(title),
            "status": "Completed" if i % 4 else "Ongoing",
        })
    return out


async def run():
    import mangasurf.tui as tui
    from mangasurf.tui import MangasurfTUI

    # Keep the harness fully offline/deterministic: disable the live network
    # search and any threaded genre loading that auto-fires on mount, so the
    # screenshots always show exactly the content we seed below. Also neuter
    # the threaded cover worker so it can't overwrite the art we paint below.
    tui.MangasurfTUI.handle_search = lambda self, _event=None: None
    tui.MangasurfTUI._load_genres = lambda self: None
    tui.MangasurfTUI._preview_cover_worker = lambda self, _info=None: None

    app = MangasurfTUI()
    results = make_results()

    async with app.run_test(size=(120, 44)) as pilot:
        from textual.widgets import ListView, Static
        from textual.containers import Vertical

        # --- seed the search tab ---
        app.results = results
        from mangasurf.console import format_source_badge, format_colored_tag
        from textual.widgets import ListItem, Static
        lv = app.query_one("#search-results", ListView)
        lv.clear()
        # NOTE: do NOT call app._load_genres() here — it triggers Select.Changed
        # which fires a live network search that overwrites our seeded rows.
        for i, r in enumerate(results):
            badge = format_source_badge(r["source"], r["source_name"])
            tag = "  ".join(format_colored_tag(t) for t in r.get("tags", [])[:2])
            lv.append(ListItem(Static(
                f"[#7ca7ff]{i + 1:02d}[/]  [bold #d7e3ff]{r['title']}[/]"
                f"   {badge}  [#64748b]Ch. {r.get('latest','')}[/]  {tag}")))
        app.query_one("#search-status", Static).update(
            f"[dim]{len(results)} results - press Enter to open[/]")
        # Preview the first result (cover + title + source badge) without the
        # threaded cover worker (which needs an actual thread).
        r0 = results[0]
        badge0 = format_source_badge(r0["source"], r0["source_name"])
        app.query_one("#search-preview-title", Static).update(
            f"[bold #ececf1]{r0['title']}[/]")
        app.query_one("#search-preview-meta", Static).update(
            f"{badge0}   [#8a8a95]Latest {r0['latest']}  |  {r0['status']}[/]")
        try:
            app.query_one("#search-preview-empty", Static).add_class("hidden")
        except Exception:
            pass
        # Give any in-flight background search time to settle, THEN paint the
        # cover so it isn't overwritten.
        await pilot.pause(1.2)
        try:
            from mangasurf.covers import render_terminal_cover
            ansi = render_terminal_cover(r0["cover"], width=22, max_height=11,
                                         source_id=r0["source"])
            if ansi:
                from rich.text import Text
                art = app.query_one("#search-cover-art", Static)
                # Grow the parent cover slot so the multi-line art isn't clipped.
                art.parent.styles.height = 13
                art.styles.height = 12
                art.update(Text.from_ansi(ansi))
        except Exception:
            pass
        await pilot.pause(0.3)

        svg = app.export_screenshot(title="Mangasurf TUI · Search")
        open("/tmp/tui-search.svg", "w").write(svg)

        # --- manga tab ---
        try:
            app.query_one("TabbedContent").active = "tab-manga"
        except Exception:
            pass
        await pilot.pause(0.2)
        # Populate manga info panel with the first title.
        from textual.widgets import SelectionList, Select
        from textual.containers import Horizontal
        try:
            app.query_one("#manga-empty", Static).add_class("hidden")
        except Exception:
            pass
        try:
            app.query_one("#manga-body", Horizontal).remove_class("hidden")
        except Exception:
            pass
        r = results[0]
        app.query_one("#manga-title", Static).update(r["title"])
        app.query_one("#manga-source", Static).update(
            f"[#64748b]{r['source_name']} · {r['status']}[/]")
        app.query_one("#manga-meta", Static).update(
            "[#64748b]Chapters 179 · Status Ongoing · Rating 9.1[/]")
        app.query_one("#manga-tags", Static).update(
            "[#8ab4ff]Action  Fantasy  [dim]Shonen  Hunters  Leveling[/]")
        app.query_one("#manga-desc", Static).update(
            "The weakest hunter in all of mankind, Sung Jin-Woo, is the only one "
            "who survives a deadly dungeon. Gifted with the System, he sets out "
            "to become the world's strongest hunter.")
        manga_ansi = render_terminal_cover(r["cover"], width=28, max_height=14,
                                           source_id=r["source"])
        try:
            m_art = app.query_one("#manga-cover-art", Static)
            m_art.parent.styles.height = 16
            m_art.styles.height = 15
            m_art.update(
                __import__("rich.text", fromlist=["Text"]).Text.from_ansi(manga_ansi))
        except Exception:
            pass
        # Chapters list
        sel = app.query_one("#chapter-list", SelectionList)
        sel.clear_options()
        from textual.widgets.selection_list import Selection
        for i in range(12, 0, -1):
            sel.add_option(Selection(f"[bold #ececf1]Chapter {i}[/]   "
                                     f"[#64748b]2026-08-{i:02d} · 8 pages[/]", i, True))
        app._update_count()
        await pilot.pause(0.3)
        svg = app.export_screenshot(title="Mangasurf TUI · Manga")
        open("/tmp/tui-manga.svg", "w").write(svg)

        # --- downloads tab ---
        app.query_one("TabbedContent").active = "tab-downloads"
        await pilot.pause(0.2)
        from textual.containers import Vertical as _Vertical
        try:
            app.query_one("#dl-empty", Static).add_class("hidden")
        except Exception:
            pass
        try:
            app.query_one("#dl-body", _Vertical).remove_class("hidden")
        except Exception:
            pass
        app.query_one("#dl-title", Static).update("[bold #6fd7e8]DOWNLOADING  ·  SOLO LEVELING[/]")
        app.query_one("#dl-netline", Static).update(
            "[#8a8a95]12.4 MB/s  ·  3 concurrent  ·  to ~/Downloads/Mangasurf[/]")
        app.query_one("#dl-status", Static).update(
            "[#8a8a95]Chapter 127 of 179  ·  88.2% overall[/]")
        try:
            bar = app.query_one("#overall-bar")
            from textual.widgets import ProgressBar
            bar.update(total=179, progress=158)
            app.query_one("#overall-text", Static).update("[#6fd7e8]88.2%[/]")
        except Exception:
            pass
        # Active worker rows
        try:
            box = app.query_one("#active-box", _Vertical)
            box.remove_children()
        except Exception:
            pass
        try:
            from textual.widgets import Static as _S, Horizontal as _H
        except Exception:
            pass
        try:
            from textual.widgets import Static as _Static, ProgressBar as _PB
            from textual.containers import Horizontal as _H, Vertical as _V
            box = app.query_one("#active-box", _V)
            box.remove_children()
            for n, s, d, t in [
                ("Chapter 127", "MangaDex", 46, 52),
                ("Chapter 126", "MangaDex", 31, 47),
                ("Chapter 125", "MangaDex", 12, 50),
            ]:
                # Mount the row to the (live) box first, THEN add children,
                # exactly like the app's _ensure_row does.
                row = _V(classes="ac-row")
                box.mount(row, before=None)
                row.mount(_Static(f"[#5bbccf]WORKER[/]  [bold #ececf1]{n}[/]   "
                                  f"[#a6adc0][{s}][/]", classes="ac-head"))
                row.mount(_Static(f"[#64748b]Progress:[/] [#67e8f9]Page {d} / {t}[/]",
                                  classes="ac-lines"))
                bar = _PB(classes="ac-bar", show_eta=False, show_percentage=True)
                bar.update(total=t, progress=d)
                row.mount(_H(bar, _Static(f"{d}/{t}", classes="ac-count")))
        except Exception:
            pass
        # Session log
        try:
            from textual.widgets import RichLog
            log = app.query_one("#dl-log", RichLog)
            log.write("[#5bbccf]11:42:07[/] [green]✔[/] Chapter 124 complete (50 pages)")
            log.write("[#5bbccf]11:42:10[/] [#8a8a95]→[/] Chapter 125: 50 pages queued")
            log.write("[#5bbccf]11:42:31[/] [#8a8a95]→[/] Chapter 126: 47 pages queued")
            log.write("[#5bbccf]11:43:02[/] [green]✔[/] Chapter 125 complete (50 pages)")
            log.write("[#5bbccf]11:43:19[/] [#8a8a95]→[/] Chapter 127: 52 pages queued")
        except Exception:
            pass
        await pilot.pause(0.4)
        svg = app.export_screenshot(title="Mangasurf TUI · Downloads")
        open("/tmp/tui-downloads.svg", "w").write(svg)

        # --- settings tab ---
        app.query_one("TabbedContent").active = "tab-settings"
        await pilot.pause(0.2)
        # Fill the scraper matrix on the right.
        try:
            from mangasurf.tui import list_sources
            lv = app.query_one("#scraper-list", ListView)
            lv.clear()
            for idx, meta in enumerate(list_sources()[:14]):
                lv.append(ListItem(Static(
                    f"[#8a8a95]{idx + 1:02d}[/]  [bold #ececf1]{meta.get('name') or meta.get('id')}[/]"
                    f"   [#8a8a95]{meta.get('base_url') or ''}[/]  "
                    f"[#a6adc0]{'API' if meta.get('supports_scanlator') is not None else 'HTML'}[/]  "
                    f"[#8a8a95]{'18+' if meta.get('adult_only') else 'SFW'}[/]")))
        except Exception:
            pass
        await pilot.pause(0.3)
        svg = app.export_screenshot(title="Mangasurf TUI · Settings")
        open("/tmp/tui-settings.svg", "w").write(svg)

    import cairosvg
    docs = os.path.join(DOCS_DIR, "docs")
    os.makedirs(docs, exist_ok=True)
    for name in ("search", "manga", "downloads", "settings"):
        cairosvg.svg2png(url=f"/tmp/tui-{name}.svg",
                         write_to=os.path.join(docs, f"tui-{name}.png"),
                         output_width=1100)
        print("wrote docs/tui-%s.png" % name)


if __name__ == "__main__":
    asyncio.run(run())
