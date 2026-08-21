"""Mangasurf command line interface.

Downloads manga from several sites (MangaDex, Mangakatana, Natomanga,
Weeb Central). The source is detected automatically from the URL.

Default behaviour: download every chapter and pack them into a single CBZ,
sorted into a per-manga folder inside the output directory.

    mangasurf <manga-url>                    one CBZ with all chapters
    mangasurf <manga-url> --per 10           one CBZ per 10 chapters
    mangasurf <manga-url> -c 1-50 -f pdf     chapters 1-50 as a single PDF
    mangasurf search "one piece"             search every source
    mangasurf search "one piece" -s mangadex search one source
    mangasurf sources                        list supported sites
    mangasurf info <manga-url>               show manga details and chapters
"""

import argparse
import os
import sys
import threading

# Allow running this file directly (python mangasurf/cli.py)
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import mangasurf  # noqa: F401
    __package__ = "mangasurf"

# Rich is optional. It used to be a hard import here, which meant a bare
# clone -- no `pip install -e .` -- could not run the CLI at all: `py cli.py`
# died with ImportError before argparse even ran. `mangasurf/console.py` uses
# Rich when it is installed and falls back to ANSI otherwise.
from .console import (ACCENT, DIM, ERR, HEAD, OK, RICH, WARN, Panel, Table,
                      box, console, download_progress, strip_markup)
from .downloader import DownloadEngine, DownloadOptions
from .sources import (DEFAULT_SOURCE, SOURCES, browse_all, detect_source,
                      genres_all, get_source, list_sources, search_all,
                      source_for_url)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mangasurf",
        description=(f"Download manga, manhwa and manhua from {len(SOURCES)} "
                     f"sources as CBZ, PDF or EPUB."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  mangasurf https://mangadex.org/title/<uuid>\n"
            "  mangasurf <url> --per 10               one CBZ per 10 chapters\n"
            "  mangasurf <url> -c 1-50 -f pdf         chapters 1-50 as one PDF\n"
            "  mangasurf <url> -c latest              only the newest chapter\n"
            "  mangasurf search \"one piece\"          search all sources\n"
            "  mangasurf search \"berserk\" -s mangadex\n"
            "  mangasurf search                           (no query) trending titles\n"
            "  mangasurf trending romance                 top romance across sources\n"
            "  mangasurf genres                           list every genre\n"
            "  mangasurf search \"blue\" -g Romance         genre-filtered search\n"
            "  mangasurf sources                          list supported sites\n"
            "  mangasurf config disable natomanga         exclude a source\n"
            "  mangasurf config up mangakatana            rank a source higher\n"
            "  mangasurf stats                            download statistics\n"
            "  mangasurf lock set                         set an app passcode\n"
            "  mangasurf watch add <url>                  track a series for updates\n"
            "  mangasurf watch check                      check every watched series\n"
            "  mangasurf disk usage                       disk usage per series\n"
            "  mangasurf covers --dry-run                 plan a cover rebuild, change nothing\n"
            "  mangasurf covers                           rebuild cover.jpg beside each CBZ\n"
            "  mangasurf covers -o DIR --sort-only        just split a flat folder by series\n"
            "  mangasurf library verify                   check files still exist\n"
            "  mangasurf library scan ~/Manga             re-link moved folders\n"
            "  mangasurf info <url>\n"
            "  mangasurf resume                       resume an interrupted download\n"
            "  mangasurf menu                         interactive numbered menu\n"
            "  mangasurf tui                          full-screen terminal UI\n"
            "\nsearch syntax:\n"
            "  mangasurf search \"solo\" --type manhwa      only manhwa\n"
            "  mangasurf search \"one piece\" --status Ongoing\n"
            "  mangasurf search \"naruto\" -n 5 --sort title\n"
            "  mangasurf search \"berserk\" --sort chapters --reverse\n"
            "  mangasurf search \"blue\" --urls               URLs only, pipe-friendly\n"
            "  mangasurf search \"blue\" --json               machine-readable\n"
            "  mangasurf search \"berserk\" --open 1          search, then show #1\n"
            "  mangasurf search \"berserk\" --download 1      search, then grab #1\n"
        ),
    )
    parser.add_argument("target", nargs="?",
                        help="manga URL, or a command: search | info | sources | config | "
                             "stats | history | lock | export | watch | disk | "
                             "trending | genres | health | library | gui | tui | "
                             "menu | resume | covers")
    parser.add_argument("query", nargs="*", help="arguments for search / info")
    parser.add_argument("-c", "--chapters", default="all", metavar="SEL",
                        help="chapter selection: all | 5 | 1-20 | 1,5,10-20 | 50- | latest | first (default: all)")
    parser.add_argument("-o", "--output", default="downloads", metavar="DIR",
                        help="output directory (default: downloads)")
    parser.add_argument("-f", "--format", default="cbz", choices=["cbz", "pdf", "epub", "images"],
                        help="output format (default: cbz)")
    parser.add_argument("--per", type=int, default=0, metavar="N",
                        help="chapters per output file: 0 = everything in one file, 1 = one file per chapter, N = N chapters per file (default: 0)")
    parser.add_argument("--also", action="append", default=[], choices=["cbz", "pdf", "epub", "images"],
                        metavar="FMT", help="produce an additional format (repeatable)")
    parser.add_argument("--keep-images", action="store_true",
                        help="keep the raw page images after packaging")
    parser.add_argument("-w", "--workers", type=int, default=3, metavar="N",
                        help="concurrent chapter downloads, 1-8 (default: 3)")
    parser.add_argument("--image-workers", type=int, default=6, metavar="N",
                        help="concurrent image downloads per chapter, 1-10 (default: 6)")
    parser.add_argument("--delay", type=float, default=0.5, metavar="S",
                        help="delay between chapters in seconds (default: 0.5)")
    parser.add_argument("--name-single", default="{title} - Chapters {chapters}", metavar="TPL",
                        help="filename template for single-file bundles (default: {title} - Chapters {chapters})")
    parser.add_argument("--name-chapter", default="{title} - Chapter {chapter}", metavar="TPL",
                        help="template for per-chapter files")
    parser.add_argument("--name-range", default="{title} - Chapters {chapters}", metavar="TPL",
                        help="template for chapter-range bundles")
    source_group = parser.add_argument_group("sources")
    source_group.add_argument("-s", "--source", default="", metavar="ID",
                              choices=[""] + list(SOURCES),
                              help="force a source: " + " | ".join(SOURCES)
                                   + " (default: detect from the URL)")
    source_group.add_argument("-l", "--language", default="en", metavar="LANG",
                              help="translation language, MangaDex only (default: en)")
    source_group.add_argument("--scanlator", default="", metavar="NAME",
                              help="preferred scanlation group, MangaDex only")
    source_group.add_argument("--data-saver", action="store_true",
                              help="download compressed pages, MangaDex only")
    source_group.add_argument("-g", "--genre", default=None, metavar="NAME",
                              help="filter by genre (see: mangasurf genres)")
    search_group = parser.add_argument_group("search and listing")
    search_group.add_argument("--type", default=None, metavar="KIND",
                              choices=["manga", "manhwa", "manhua", "comic",
                                       "novel", "any"],
                              help="only this series type (manga/manhwa/manhua)")
    search_group.add_argument("--status", default=None, metavar="S",
                              help="only this status, e.g. Ongoing or Completed")
    search_group.add_argument("-n", "--limit", type=int, default=0, metavar="N",
                              help="show at most N results per source")
    search_group.add_argument("--sort", default=None, metavar="KEY",
                              choices=["title", "source", "chapters", "year"],
                              help="sort results by this column")
    search_group.add_argument("--reverse", action="store_true",
                              help="reverse the sort order")
    search_group.add_argument("--json", action="store_true",
                              help="print results as JSON instead of a table")
    search_group.add_argument("--urls", action="store_true",
                              help="print only URLs, one per line (pipe-friendly)")
    covers_group = parser.add_argument_group("covers")
    covers_group.add_argument("--dry-run", action="store_true",
                              help="covers: show the plan, change nothing")
    covers_group.add_argument("--sort-only", action="store_true",
                              help="covers: only split a flat folder into "
                                   "one folder per series")
    covers_group.add_argument("--replace", action="store_true",
                              help="covers: replace covers that already exist")

    search_group.add_argument("--open", type=int, default=0, metavar="N",
                              help="after searching, show details for result N")
    search_group.add_argument("--download", type=int, default=0, metavar="N",
                              help="after searching, download result N")

    parser.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument("--plain", action="store_true", help="plain log output (no fancy progress UI)")
    return parser


# ------------------------------------------------------------------ commands

def cmd_sources():
    """List every supported site, categories, and capabilities."""
    from .console import format_source_badge
    
    console.print(Panel(
        f"[bold bright_white]MANGASURF SOURCES REGISTRY[/] — [bright_cyan]{len(list_sources())} Scrapers Active[/]\n"
        f"[{DIM}]High-concurrency multi-source scraper engine with 0.0s instant failover[/]",
        border_style=ACCENT, box=box.ROUNDED
    ))
    
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("ID", style="bold")
    table.add_column("Source", style=HEAD)
    table.add_column("Base URL", style=DIM, overflow="fold")
    table.add_column("Features")
    table.add_column("Status", justify="center")

    for meta in list_sources():
        notes = []
        if meta.get("supports_browse"):
            notes.append("[bright_green]browse[/]")
        if meta.get("supports_genres"):
            notes.append("[bright_magenta]genres[/]")
        if meta.get("supports_language"):
            notes.append("[bright_cyan]languages[/]")
        if meta.get("supports_scanlator"):
            notes.append("[yellow]scanlators[/]")
        if meta.get("needs_flaresolverr"):
            notes.append("[bold red]cloudflare[/]")
        
        status = "[bright_green]● active[/]"
        badge = format_source_badge(meta["id"], meta["name"])
        table.add_row(meta["id"], badge, meta["base_url"], " ".join(notes) or "[dim]-[/]", status)

    console.print(table)
    console.print(f"[{DIM}]Search a specific source:[/] mangasurf search \"title\" -s <id>")
    console.print(f"[{DIM}]Direct download:[/]         mangasurf <url>")
    return 0


def cmd_config(args) -> int:
    """Show or change per-source ranking and exclusions."""
    from . import config as appconfig

    rest = [a for a in args.query]
    action = (rest[0].lower() if rest else "show")

    if action in ("enable", "disable", "include", "exclude"):
        if len(rest) < 2:
            console.print("[red]Usage: mangasurf config enable|disable <source>[/]")
            return 1
        source_id = rest[1].lower()
        if source_id not in SOURCES:
            console.print(f"[red]Unknown source '{source_id}'[/]")
            return 1
        on = action in ("enable", "include")
        appconfig.set_enabled(source_id, on)
        console.print(f"{SOURCES[source_id].name}: "
                      f"[{ACCENT}]{'enabled' if on else 'excluded'}[/]")
    elif action in ("up", "down"):
        if len(rest) < 2:
            console.print(f"[red]Usage: mangasurf config {action} <source>[/]")
            return 1
        appconfig.move(rest[1].lower(), -1 if action == "up" else 1)
    elif action == "rank":
        order = [s.lower() for s in rest[1:]]
        if not order:
            console.print("[red]Usage: mangasurf config rank <source> <source> ...[/]")
            return 1
        appconfig.reorder(order)
        console.print("Ranking updated.")
    elif action == "reset":
        appconfig.reset_config()
        console.print("Source configuration reset.")
    elif action != "show":
        console.print(f"[red]Unknown action '{action}'[/]")
        console.print(f"[{DIM}]show | enable | disable | up | down | rank | reset[/]")
        return 1

    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("#", style=DIM, justify="right")
    table.add_column("ID")
    table.add_column("Site")
    table.add_column("Search", justify="center")
    table.add_column("Status")
    for index, row in enumerate(appconfig.describe(), 1):
        enabled = row.get("enabled", True)
        table.add_row(
            str(index), row["id"], row.get("name", row["id"]),
            "yes" if row.get("search_enabled", True) else "no",
            f"[{ACCENT}]enabled[/]" if enabled else "[red]excluded[/]",
        )
    console.print(table)
    console.print(f"[{DIM}]mangasurf config up|down <source>   "
                  f"mangasurf config disable <source>[/]")
    return 0


def cmd_stats() -> int:
    from . import features

    stats = features.get_stats()
    totals = stats.get("totals", {})
    derived = stats.get("derived", {})
    if not totals:
        console.print("[yellow]No download statistics yet.[/]")
        return 0

    grid = Table.grid(padding=(0, 3))
    grid.add_column(style=DIM)
    grid.add_column()
    grid.add_row("Downloads", str(totals.get("downloads", 0)))
    grid.add_row("Chapters", str(totals.get("chapters", 0)))
    grid.add_row("Pages", str(totals.get("pages", 0)))
    grid.add_row("Data", derived.get("human_bytes", "-"))
    grid.add_row("Time", derived.get("human_time", "-"))
    grid.add_row("Speed", f"{derived.get('avg_pages_per_second', 0)} pages/s")
    grid.add_row("Top source", derived.get("top_source", "-"))
    console.print(Panel(grid, title="[bold]Statistics[/]",
                        border_style=ACCENT, box=box.ROUNDED))

    per_source = stats.get("sources", {})
    if per_source:
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("Source")
        table.add_column("Chapters", justify="right")
        table.add_column("Pages", justify="right")
        table.add_column("Data", justify="right")
        for name, row in sorted(per_source.items(),
                                key=lambda kv: -kv[1].get("chapters", 0)):
            table.add_row(name, str(row.get("chapters", 0)),
                          str(row.get("pages", 0)),
                          features.human_size(row.get("bytes", 0)))
        console.print(table)
    return 0


def cmd_history(args) -> int:
    from . import features

    rest = [a for a in args.query]
    if rest and rest[0].lower() == "clear":
        features.clear_history()
        console.print("History cleared.")
        return 0
    items = features.get_history(25)
    if not items:
        console.print("[yellow]No search history.[/]")
        return 0
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("Query")
    table.add_column("Source", style=DIM)
    table.add_column("Hits", justify="right", style=DIM)
    table.add_column("When", style=DIM)
    for item in items:
        table.add_row(item.get("query", ""), item.get("source", ""),
                      str(item.get("results", 0)), item.get("date", ""))
    console.print(table)
    return 0


def cmd_lock(args) -> int:
    """Manage the app passcode from the terminal."""
    import getpass

    from . import passlock

    rest = [a for a in args.query]
    action = (rest[0].lower() if rest else "status")

    if action == "status":
        status = passlock.status()
        console.print(Panel(
            f"Passcode: [{ACCENT}]{'on' if status['enabled'] else 'off'}[/]\n"
            f"Auto-lock: {status['auto_lock_minutes'] or 'never'}\n"
            f"Recovery key configured: {'yes' if status['has_recovery'] else 'no'}",
            title="[bold]Lock[/]", border_style=ACCENT, box=box.ROUNDED))
        return 0

    if action in ("set", "on", "enable"):
        code = getpass.getpass("New passcode: ")
        if code != getpass.getpass("Confirm passcode: "):
            console.print("[red]Passcodes do not match.[/]")
            return 1
        result = passlock.set_passcode(code)
        if not result.get("ok"):
            console.print(f"[red]{result['error']}[/]")
            return 1
        console.print(Panel(
            f"[bold]{result['recovery_key']}[/]\n\n"
            f"[{DIM}]Store this somewhere safe. It is shown once and is the only "
            f"way back in if you forget the passcode.[/]",
            title="[bold]Recovery key[/]", border_style=ACCENT, box=box.ROUNDED))
        return 0

    if action in ("off", "disable"):
        result = passlock.disable(getpass.getpass("Current passcode: "))
        console.print("Lock disabled." if result.get("ok")
                      else f"[red]{result['error']}[/]")
        return 0 if result.get("ok") else 1

    if action == "change":
        current = getpass.getpass("Current passcode: ")
        new = getpass.getpass("New passcode: ")
        result = passlock.change_passcode(current, new)
        console.print("Passcode changed." if result.get("ok")
                      else f"[red]{result['error']}[/]")
        return 0 if result.get("ok") else 1

    console.print(f"[{DIM}]Usage: mangasurf lock status|set|change|off[/]")
    return 1


def cmd_export(args) -> int:
    from . import features

    rest = [a for a in args.query]
    if not rest:
        console.print("[red]Usage: mangasurf export <file> [json|csv|md][/]")
        return 1
    path = rest[0]
    fmt = rest[1] if len(rest) > 1 else (
        os.path.splitext(path)[1].lstrip(".") or "json")
    try:
        features.export_library(path, fmt)
    except Exception as e:
        console.print(f"[red]Export failed:[/] {e}")
        return 1
    console.print(f"Exported library to [bold]{path}[/]")
    return 0


def _print_results(results, header=None):
    """Shared result table for search / browse output."""
    from . import features

    results = features.apply_filters(results)
    if not results:
        console.print("[yellow]Nothing to show.[/]")
        return 1
    if header:
        console.print(f"[bold]{header}[/]")
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("#", style=DIM, justify="right")
    table.add_column("Source", style=ACCENT)
    table.add_column("Title")
    table.add_column("URL", style=DIM, overflow="fold")
    for index, row in enumerate(results, 1):
        table.add_row(str(index), row.get("source_name") or row.get("source") or "?",
                      row.get("title", "?"), row.get("url", ""))
    console.print(table)
    console.print(f"[{DIM}]Download with: mangasurf <url>[/]")
    return 0


def cmd_trending(args) -> int:
    """Discovery listing: trending, or a genre, across the enabled sources."""
    rest = list(args.query)
    genre = " ".join(rest) if rest else None
    source_id = args.source

    label = f"Top {genre}" if genre else "Trending now"
    with console.status(f"Fetching {label.lower()}..."):
        if source_id and source_id != "all":
            source = get_source(source_id, language=args.language)
            try:
                if not getattr(source, "supports_browse", False):
                    console.print(f"[yellow]{source.name} cannot list trending "
                                  f"titles.[/]")
                    return 1
                results = source.browse(genre=genre, limit=24)
            finally:
                source.close()
        else:
            results = browse_all(genre=genre, limit=8)
    return _print_results(results, label)


def cmd_genres(args) -> int:
    """List the genres available across the enabled sources."""
    source_id = args.source
    if source_id and source_id != "all":
        source = get_source(source_id)
        try:
            rows = [{"name": g["name"], "sources": {source_id: g["id"]}}
                    for g in (source.genres() or [])]
        finally:
            source.close()
    else:
        rows = genres_all()

    if not rows:
        console.print("[yellow]No genres available.[/]")
        return 1

    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("Genre")
    table.add_column("Available on", style=DIM)
    for row in rows:
        table.add_row(row["name"], ", ".join(sorted(row["sources"])))
    console.print(table)
    console.print(f"[{DIM}]Browse one with: mangasurf trending <genre>[/]")
    return 0


def cmd_api(args) -> int:
    """Print one local-API endpoint as JSON.

    The same data ``GET /local/<name>`` serves, without starting a server --
    for scripts, and for agents that would rather pipe into ``jq`` than hold
    a token. Documented in MD/AGENT.md.
    """
    from . import localapi

    name = (getattr(args, "query", None) or ["info"])[0] or "info"
    if name in ("list", "endpoints", "help"):
        console.print(f"[bold {ACCENT}]Local API endpoints[/]")
        for endpoint in sorted(localapi.ENDPOINTS):
            console.print(f"  {endpoint}")
        console.print(f"\n[{DIM}]mangasurf api <name>   "
                      f"or   GET /local/<name>[/]")
        return 0
    if name not in localapi.ENDPOINTS:
        console.print(f"[red]No endpoint[/] {name!r}")
        console.print(f"[{DIM}]Try: {', '.join(sorted(localapi.ENDPOINTS))}[/]")
        return 1
    kwargs = {}
    if name == "books" and getattr(args, "json", False):
        kwargs["include_chapters"] = True
    # Printed with print(), not console.print(): rich would wrap and colour
    # the JSON, and this output is meant to be piped.
    print(localapi.dump(name, **kwargs))
    return 0


def cmd_health() -> int:
    """Circuit-breaker and cache diagnostics."""
    from .robust import health_report

    report = health_report()
    breakers = report["breakers"]
    if not breakers:
        console.print(f"[{DIM}]No source calls recorded yet this session.[/]")
    else:
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("Source")
        table.add_column("State")
        table.add_column("Failures", justify="right")
        table.add_column("Retry in", justify="right")
        for name, row in sorted(breakers.items()):
            state = row["state"]
            colour = {"closed": ACCENT, "half-open": "yellow"}.get(state, "red")
            table.add_row(name, f"[{colour}]{state}[/]", str(row["failures"]),
                          f"{row['retry_after']:.0f}s" if row["retry_after"] else "-")
        console.print(table)

    for label, key in (("Browse cache", "browse_cache"),
                       ("Genre cache", "genre_cache")):
        stats = report[key]
        console.print(f"[{DIM}]{label}: {stats['entries']} entries, "
                      f"{stats['hit_rate']}% hit rate[/]")
    return 0


def cmd_library(args) -> int:
    """Verify the library and re-link folders the user has moved."""
    from . import library

    rest = list(args.query)
    action = (rest[0].lower() if rest else "verify")

    if action in ("verify", "check"):
        report = library.verify_entries()
        missing = report["missing"]
        if not missing:
            console.print(f"[green]All {len(report['present'])} entries "
                          f"resolve on disk.[/]")
            return 0
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("Title")
        table.add_column("Folder", style=DIM, overflow="fold")
        table.add_column("Problem", style=DIM)
        for row in missing:
            problems = []
            if not row["directory_ok"]:
                problems.append("folder missing")
            if row["missing_outputs"]:
                problems.append(f"{len(row['missing_outputs'])} file(s) gone")
            table.add_row(row.get("title") or "?", row.get("directory") or "-",
                          ", ".join(problems))
        console.print(table)
        console.print(f"[{DIM}]Re-link with: mangasurf library scan <folder>[/]")
        return 0

    if action in ("scan", "find"):
        roots = rest[1:] or [args.output]
        proposals = library.find_moved_entries(roots)
        if not proposals:
            console.print("[yellow]No moved folders found under: "
                          + ", ".join(roots) + "[/]")
            return 0
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("Title")
        table.add_column("New location", style=DIM, overflow="fold")
        for p in proposals:
            table.add_row(p.get("title") or "?", p.get("new") or "")
        console.print(table)

        if not args.yes:
            try:
                answer = console.input(
                    f"[{ACCENT}]Re-link these {len(proposals)}? \\[Y/n][/] "
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                console.print()
                return 130
            if answer and answer not in ("y", "yes"):
                console.print("Cancelled.")
                return 0

        result = library.apply_relocations(proposals)
        console.print(f"Re-linked [bold]{result['applied']}[/] entries.")
        return 0

    if action in ("move", "relocate"):
        if len(rest) < 3:
            console.print("[red]Usage: mangasurf library move <url> <new-folder>[/]")
            return 1
        result = library.relocate_entry(rest[1], rest[2])
        if result.get("ok"):
            console.print(f"Re-linked [bold]{result.get('title')}[/] -> "
                          f"{result.get('new')}")
            return 0
        console.print(f"[red]{result.get('error')}[/]")
        return 1

    if action in ("metadata", "meta", "sync-metadata"):
        roots = rest[1:] or None
        result = library.rebuild_library_metadata(roots)
        console.print(f"[green]Synced manga.json metadata for [bold]{result.get('written', 0)}[/] folders (total {result.get('total_series', 0)} series).[/]")
        return 0

    console.print(f"[{DIM}]Usage: mangasurf library verify|scan [folder]|"
                  f"move <url> <folder>|metadata[/]")
    return 1


def cmd_watch(args) -> int:
    """Watch a series, or list / check the watchlist."""
    from . import tracking

    rest = list(args.query)
    action = (rest[0].lower() if rest else "list")

    if action == "list":
        entries = tracking.get_watchlist()
        if not entries:
            console.print("[yellow]Nothing is being watched.[/]")
            console.print(f"[{DIM}]Add one with: mangasurf watch add <url>[/]")
            return 0
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("Title")
        table.add_column("Source", style=DIM)
        table.add_column("Chapters", justify="right")
        table.add_column("New", justify="right")
        table.add_column("Checked", style=DIM)
        for entry in entries:
            new = entry.get("new_chapters", 0)
            table.add_row(
                entry.get("title", "?"), entry.get("source", "-"),
                str(entry.get("known_chapters", 0)),
                f"[{ACCENT}]+{new}[/]" if new else "-",
                entry.get("checked", "-"))
        console.print(table)
        return 0

    if action in ("add", "remove", "rm"):
        if len(rest) < 2:
            console.print(f"[red]Usage: mangasurf watch {action} <url>[/]")
            return 1
        url = rest[1]
        if action == "add":
            try:
                source = source_for_url(url)
                info = source.get_manga_info(url)
                chapters = source.get_chapters(url)
                source.close()
            except Exception as e:
                console.print(f"[red]Error:[/] {e}")
                return 1
            tracking.watch(url, info["title"], len(chapters),
                           source=info.get("source"), cover=info.get("cover"))
            console.print(f"Watching [bold]{info['title']}[/] "
                          f"([{DIM}]{len(chapters)} chapters[/])")
        else:
            console.print("Removed." if tracking.unwatch(url)
                          else "[yellow]Not in the watchlist.[/]")
        return 0

    if action == "check":
        entries = tracking.get_watchlist()
        if not entries:
            console.print("[yellow]Nothing is being watched.[/]")
            return 0
        with console.status(f"Checking {len(entries)} series..."):
            updates = tracking.check_updates()
        if not updates:
            console.print("[green]Everything is up to date.[/]")
            return 0
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("Title")
        table.add_column("New", justify="right")
        table.add_column("Total", justify="right")
        for update in updates:
            table.add_row(update["title"], f"[{ACCENT}]+{update['new']}[/]",
                          str(update["total"]))
        console.print(table)
        return 0

    console.print(f"[{DIM}]Usage: mangasurf watch list|add|remove|check [url][/]")
    return 1


def cmd_covers(args) -> int:
    """Rebuild cover.jpg beside every CBZ.

    The GUI offers a picker; here the best-ranked candidate is used, since
    a terminal cannot show thumbnails. --dry-run prints the plan only.
    """
    from . import covers

    root = args.output if args.output != "downloads" else None
    root = root or load_settings().get("output_dir", "downloads")
    overwrite = bool(getattr(args, "replace", False))
    groups = covers.plan(root, overwrite=overwrite)
    if not groups:
        console.print(f"[{OK}]Every archive under {root} already has a cover.[/]")
        return 0

    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("Series")
    table.add_column("Archives", justify="right", style=DIM)
    table.add_column("Folder", style=DIM, overflow="fold")
    for group in groups:
        note = " (will move)" if group["needs_move"] else ""
        table.add_row(group["title"], str(len(group["archives"])),
                      group["target_dir"] + note)
    console.print(table)

    dry = bool(getattr(args, "dry_run", False) or getattr(args, "urls", False))
    if dry:
        console.print(f"[{DIM}]Dry run: nothing was changed.[/]")
        return 0

    # --sort folders: split a flat folder into one folder per series and
    # stop there, without fetching any covers.
    if getattr(args, "sort_only", False):
        moved = folders = 0
        for group in groups:
            if not group["needs_move"]:
                continue
            try:
                covers.isolate(group)
                folders += 1
                moved += len(group["archives"])
            except OSError as e:
                console.print(f"  [{ERR}]failed[/] {group['title']}: {e}")
        console.print(f"{moved} archive(s) sorted into {folders} folder(s)")
        return 0

    saved = failed = 0
    for group in groups:
        try:
            directory = covers.isolate(group)
        except OSError as e:
            console.print(f"  [{ERR}]failed[/] {group['title']}: {e}")
            failed += 1
            continue

        # auto_cover measures each candidate and applies the same rules the
        # GUI's Smart search uses: exact title, then the Settings ranking,
        # then resolution so a list thumbnail is never chosen.
        result = covers.auto_cover(group["title"], directory)
        if result.get("ok"):
            saved += 1
            chosen = result.get("chosen") or {}
            size = ""
            if result.get("width"):
                size = f" {result['width']}x{result['height']}"
            console.print(f"  [{OK}]saved[/] {group['title']} "
                          f"[{DIM}]from {chosen.get('source_name')}{size}[/]")
        else:
            failed += 1
            console.print(f"  [{ERR}]{result.get('error', 'failed')}[/] "
                          f"{group['title']}")

    console.print(f"\n{saved} cover(s) written"
                  + (f", {failed} failed" if failed else ""))
    return 0 if saved else 1


def cmd_disk(args) -> int:
    """Disk usage, duplicate files and orphaned library entries."""
    from . import features, tracking

    rest = list(args.query)
    action = (rest[0].lower() if rest else "usage")
    root = rest[1] if len(rest) > 1 else args.output

    if action == "usage":
        rows = tracking.disk_usage(root)
        if not rows:
            console.print(f"[yellow]Nothing found in {root}[/]")
            return 0
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("Series")
        table.add_column("Files", justify="right", style=DIM)
        table.add_column("Size", justify="right")
        total = 0
        for row in rows[:30]:
            total += row["bytes"]
            table.add_row(row["name"], str(row["files"]),
                          features.human_size(row["bytes"]))
        console.print(table)
        console.print(f"[{DIM}]Total: {features.human_size(total)}[/]")
        return 0

    if action in ("dupes", "duplicates"):
        with console.status(f"Scanning {root}..."):
            groups = tracking.scan_duplicates(root)
        if not groups:
            console.print("[green]No duplicate files found.[/]")
            return 0
        wasted = sum(g["wasted"] for g in groups)
        for group in groups[:20]:
            console.print(f"[{ACCENT}]{features.human_size(group['size'])}[/] "
                          f"x{len(group['files'])}")
            for path in group["files"]:
                console.print(f"  [{DIM}]{path}[/]")
        console.print(f"\n[bold]{features.human_size(wasted)}[/] wasted "
                      f"across {len(groups)} groups")
        return 0

    if action == "orphans":
        orphans = tracking.find_orphans()
        if not orphans:
            console.print("[green]No orphaned library entries.[/]")
            return 0
        for orphan in orphans:
            console.print(f"[yellow]{orphan['title']}[/]")
            if orphan["directory_gone"]:
                console.print(f"  [{DIM}]folder missing: {orphan['directory']}[/]")
            for missing in orphan["missing"]:
                console.print(f"  [{DIM}]missing: {missing}[/]")
        return 0

    console.print(f"[{DIM}]Usage: mangasurf disk usage|dupes|orphans [dir][/]")
    return 1


def _null_status():
    """A no-op stand-in for console.status() when printing machine output."""
    import contextlib
    return contextlib.nullcontext()


def _narrow(results, series_type=None, status=None):
    """Apply the --type / --status narrowing to a result list.

    Series type is derived rather than requested: only one source accepts a
    type parameter, so classify_type() maps origin language and tags, with a
    per-source default for single-type catalogues. Results whose type cannot
    be determined are kept -- dropping them would erase whole sources from a
    filtered search.
    """
    from .sources.base import classify_type

    if series_type and series_type.lower() != "any":
        want = series_type.lower()
        kept = []
        for row in results:
            kind = (row.get("series_type")
                    or classify_type(row.get("original_language"),
                                     row.get("tags")))
            if not kind:
                cls = SOURCES.get(row.get("source"))
                kind = getattr(cls, "default_series_type", None)
            if not kind or str(kind).lower() == want:
                kept.append(row)
        results = kept

    if status and status.lower() != "any":
        want = status.lower()
        results = [r for r in results
                   if not r.get("status")
                   or str(r["status"]).lower() == want]
    return results


def _sort_results(results, key=None, reverse=False):
    """Sort by one of the displayed columns. Unknown values sort last."""
    if not key:
        return results

    def sort_key(row):
        if key == "title":
            return (0, str(row.get("title") or "").lower())
        if key == "source":
            return (0, str(row.get("source_name") or row.get("source") or "").lower())
        if key == "chapters":
            count = features._chapter_count(row)
            return (1, 0) if count is None else (0, -count)
        if key == "year":
            year = row.get("year")
            return (1, 0) if not year else (0, -int(year))
        return (0, 0)

    from . import features
    return sorted(results, key=sort_key, reverse=reverse)


def _emit(results, as_json=False, urls_only=False):
    """Machine-readable output. Returns True if it handled the printing."""
    if urls_only:
        for row in results:
            print(row.get("url", ""))
        return True
    if as_json:
        import json
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return True
    return False


def cmd_search(query: str, source_id: str = "", language: str = "en",
               genre: str = None, series_type=None, status=None,
               limit: int = 0, sort=None, reverse=False, as_json=False,
               urls_only=False, open_index: int = 0,
               download_index: int = 0, args=None):
    # An empty query is a request for discovery, not an error.
    if not query:
        with console.status("Fetching trending titles..."):
            if source_id and source_id != "all":
                source = get_source(source_id, language=language)
                try:
                    results = (source.browse(genre=genre, limit=24)
                               if getattr(source, "supports_browse", False) else [])
                finally:
                    source.close()
            else:
                results = browse_all(genre=genre, limit=8)
        return _print_results(
            results, f"Top {genre}" if genre else "Trending now")

    per_source = limit if limit > 0 else 10
    quiet = as_json or urls_only          # keep machine output clean

    if source_id:
        label = SOURCES[source_id].name
        status_ctx = (console.status(f"Searching [bold]{label}[/] for [bold]{query}[/]...")
                      if not quiet else _null_status())
        with status_ctx:
            source = get_source(source_id, language=language)
            try:
                results = source.search(query, genre=genre,
                                        limit=per_source * 3)
            finally:
                source.close()
    else:
        status_ctx = (console.status(f"Searching all sources for [bold]{query}[/]...")
                      if not quiet else _null_status())
        with status_ctx:
            results = search_all(query, limit=per_source, genre=genre)

    from . import features
    results = features.apply_filters(results)
    results = _narrow(results, series_type, status)
    results = _sort_results(results, sort, reverse)
    if limit > 0:
        results = results[:limit] if source_id else results
    features.add_history(query, source_id or "all", len(results))

    if not results:
        if not quiet:
            console.print("[yellow]No results found.[/]")
        return 1

    if _emit(results, as_json, urls_only):
        return 0

    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("#", style=DIM, justify="right")
    table.add_column("Source")
    table.add_column("Title", style=HEAD)
    table.add_column("Type", style=DIM)
    table.add_column("URL", style=DIM, overflow="fold")
    for i, r in enumerate(results, 1):
        from .console import format_source_badge
        badge = format_source_badge(r.get("source") or "", r.get("source_name") or r.get("source") or "?")
        table.add_row(str(i), badge,
                      r.get("title", "?"), r.get("series_type") or "",
                      r.get("url", ""))
    console.print(table)

    # --open N / --download N act on the numbers just printed, so a search
    # and the thing you wanted from it are one command instead of a
    # copy-paste of a URL.
    if open_index:
        if not 1 <= open_index <= len(results):
            console.print(f"[yellow]--open must be 1-{len(results)}.[/]")
            return 1
        console.print()
        return cmd_info(results[open_index - 1]["url"], source_id, language)

    if download_index:
        if not 1 <= download_index <= len(results):
            console.print(f"[yellow]--download must be 1-{len(results)}.[/]")
            return 1
        chosen = results[download_index - 1]
        console.print(f"[{DIM}]Downloading:[/] {chosen.get('title', '?')}")
        if args is not None:
            args.target = chosen["url"]
            args.source = chosen.get("source") or source_id
            return cmd_download(args)

    console.print(f"[{DIM}]Download with: mangasurf <url>   "
                  f"or: mangasurf search \"{query}\" --download N[/]")
    return 0


def cmd_info(url: str, source_id: str = "", language: str = "en"):
    if not url:
        console.print("[red]Provide a manga URL.[/]")
        return 1
    try:
        source = (get_source(source_id, language=language) if source_id
                  else source_for_url(url, language=language))
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        return 1
    with console.status("Fetching manga information & cover..."):
        try:
            info = source.get_manga_info(url)
            chapters = source.get_chapters(url)
        except Exception as e:
            console.print(f"[red]Error:[/] {e}")
            return 1
        finally:
            source.close()

    from .console import format_source_badge, format_colored_tag
    provider = info.get("source_name") or source.name
    source_badge = format_source_badge(info.get("source") or source_id or source.id, provider)

    # Render TrueColor cover if available
    cover_art = ""
    if info.get("cover"):
        from .covers import render_terminal_cover
        try:
            cover_art = render_terminal_cover(info["cover"], width=30, max_height=18,
                                              source_id=info.get("source") or source_id,
                                              referer=url)
        except Exception:
            cover_art = ""

    body = [f"[{DIM}]Source:[/]   {source_badge}", f"[{DIM}]URL:[/]      [{DIM}]{url}[/]"]
    if info.get("authors"):
        body.append(f"[{DIM}]Author:[/]   [bold]{', '.join(info['authors'])}[/]")
    if info.get("status"):
        status_color = "bright_green" if str(info['status']).lower() == "ongoing" else "bright_cyan"
        body.append(f"[{DIM}]Status:[/]   [{status_color}]{info['status']}[/]")
    if info.get("tags"):
        tag_pills = " ".join(format_colored_tag(t) for t in (info.get("tags") or [])[:12])
        body.append(f"[{DIM}]Tags:[/]     {tag_pills}")
    body.append(f"[{DIM}]Chapters:[/] [bold bright_white]{len(chapters)}[/] available")
    if info.get("description"):
        body.append("")
        body.append(f"[{DIM}]{info['description'][:400]}{'...' if len(info['description']) > 400 else ''}[/]")

    if cover_art:
        try:
            from rich.text import Text
            console.print()
            console.print(Text.from_ansi(cover_art))
        except Exception:
            print(cover_art)

    console.print(Panel("\n".join(body), title=f"[bold bright_white]{info['title']}[/]",
                        border_style=ACCENT, box=box.ROUNDED))

    if chapters:
        first, last = chapters[0]["name"], chapters[-1]["name"]
        console.print(f"[{DIM}]First:[/] {first}    [{DIM}]Latest:[/] {last}")
        console.print(f"\n[{OK}]Download command:[/] mangasurf \"{url}\" --format cbz")
    return 0


def cmd_resume(args) -> int:
    """Resume the last interrupted job recorded in the journal."""
    from .downloader import DownloadEngine, DownloadOptions
    from .logs import clear_journal, read_journal

    from .logs import read_journals

    jobs = read_journals()
    if not jobs:
        console.print("[yellow]No interrupted download to resume.[/]")
        return 1
    if len(jobs) > 1:
        # Concurrent GUI downloads can strand several at once.
        console.print(f"[{DIM}]{len(jobs)} interrupted jobs found; "
                      f"resuming the most recent. Run again for the next.[/]")
        table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
        table.add_column("#", style=DIM, justify="right")
        table.add_column("Title")
        table.add_column("Started", style=DIM)
        for index, entry in enumerate(jobs, 1):
            table.add_row(str(index), entry.get("title") or "?",
                          entry.get("started") or "?")
        console.print(table)
    job = jobs[0]
    title = job.get("title", "Unknown manga")
    started = job.get("started", "?")
    console.print(Panel(
        f"[bold]{title}[/]\n[{DIM}]Interrupted job from {started}. "
        f"Completed chapters will be skipped.[/]",
        title="[bold]Resume download[/]", border_style=ACCENT, box=box.ROUNDED))

    if not args.yes:
        try:
            answer = console.input(f"[{ACCENT}]Resume? \\[Y/n][/] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return 130
        if answer and answer not in ("y", "yes"):
            # The first prompt guards EOF/Ctrl-C; this one did not, so a
            # piped "n" crashed with EOFError instead of exiting cleanly.
            try:
                discard = console.input(
                    f"[{DIM}]Discard this job? \\[y/N][/] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                console.print()
                return 0
            if discard in ("y", "yes"):
                clear_journal(job.get("job_id"))
                console.print("Discarded.")
            return 0

    options = DownloadOptions(**job["options"])
    if args.plain:
        return _run_plain(options)
    return _run_rich(options, skip_confirm=True)


def cmd_download(args) -> int:
    options = DownloadOptions(
        url=args.target,
        selection=args.chapters,
        output_dir=args.output,
        format=args.format,
        bundle=max(0, args.per),
        chapter_workers=max(1, min(8, args.workers)),
        image_workers=max(1, min(10, args.image_workers)),
        delay=max(0.0, args.delay),
        keep_images=args.keep_images or args.format == "images" or "images" in args.also,
        extra_formats=[f for f in args.also if f != "images"],
        name_single=args.name_single,
        name_chapter=args.name_chapter,
        name_range=args.name_range,
        source=args.source,
        language=args.language,
        scanlator=args.scanlator,
        data_saver=args.data_saver,
    )

    if args.plain:
        return _run_plain(options)
    return _run_rich(options, skip_confirm=args.yes)


def _run_plain(options) -> int:
    def on_event(event):
        t = event["type"]
        if t == "status":
            print(event["message"])
        elif t == "plan":
            print(f"{event['title']}: {event['total']} chapters -> {event['directory']}")
        elif t == "chapter_done":
            print(f"[{event['completed']}/{event['total']}] {event['chapter']} ({event['pages']} pages)")
        elif t == "chapter_failed":
            print(f"FAILED: {event['chapter']}")
        elif t == "packaged":
            print(f"Created: {event['file']}")
        elif t == "error":
            print(f"ERROR: {event['message']}", file=sys.stderr)

    result = DownloadEngine(options, on_event).run()
    return 0 if result.get("ok") else 1


def _run_rich(options, skip_confirm=False) -> int:
    try:
        source = (get_source(options.source, language=options.language)
                  if options.source
                  else source_for_url(options.url, language=options.language))
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        return 1
    with console.status("Fetching manga information..."):
        try:
            info = source.get_manga_info(options.url)
            chapters = source.get_chapters(options.url)
        except Exception as e:
            console.print(f"[red]Error:[/] {e}")
            return 1
        finally:
            source.close()

    from .utils import parse_selection
    try:
        selected = parse_selection(options.selection, chapters)
    except ValueError as e:
        console.print(f"[red]Error:[/] {e}")
        return 1
    if not selected:
        console.print("[red]Selection matched no chapters.[/]")
        return 1

    if options.bundle == 0:
        bundle_desc = "everything in one file"
    elif options.bundle == 1:
        bundle_desc = "one file per chapter"
    else:
        bundle_desc = f"{options.bundle} chapters per file"

    fmt_desc = options.format.upper()
    if options.extra_formats:
        fmt_desc += " + " + " + ".join(f.upper() for f in options.extra_formats)

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style=DIM)
    summary.add_column()
    summary.add_row("Source", info.get("source_name") or source.name)
    summary.add_row("Manga", f"[bold]{info['title']}[/]")
    summary.add_row("Chapters", f"{len(selected)} of {len(chapters)}  ({selected[0]['name']} to {selected[-1]['name']})")
    summary.add_row("Format", fmt_desc)
    summary.add_row("Bundling", bundle_desc)
    summary.add_row("Output", options.output_dir)
    console.print(Panel(summary, title="[bold]Download plan[/]", border_style=ACCENT, box=box.ROUNDED))

    if not skip_confirm:
        try:
            answer = console.input(f"[{ACCENT}]Proceed? \\[Y/n][/] ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return 130
        if answer and answer not in ("y", "yes"):
            console.print("Cancelled.")
            return 0

    # Built in console.py so the Rich and no-Rich paths stay in step; it also
    # adds a percentage and an ETA column, which the elapsed-time-only bar
    # lacked (an 800-chapter series gave no sense of how long remained).
    progress = download_progress(console)
    overall = progress.add_task("[bold]Overall", total=len(selected))
    chapter_tasks = {}
    lock = threading.Lock()
    result_holder = {}

    def on_event(event):
        t = event["type"]
        with lock:
            if t == "chapter_start":
                chapter_tasks[event["chapter"]] = progress.add_task(
                    f"  {event['chapter']}", total=None)
            elif t == "chapter_progress":
                task = chapter_tasks.get(event["chapter"])
                if task is not None:
                    progress.update(task, total=event["total"], completed=event["done"])
            elif t == "chapter_done":
                task = chapter_tasks.pop(event["chapter"], None)
                if task is not None:
                    progress.remove_task(task)
                progress.advance(overall)
                progress.console.print(
                    f"  [{ACCENT}]done[/] {event['chapter']} [{DIM}]({event['pages']} pages)[/]")
            elif t == "chapter_failed":
                task = chapter_tasks.pop(event["chapter"], None)
                if task is not None:
                    progress.remove_task(task)
                progress.advance(overall)
                progress.console.print(f"  [red]failed[/] {event['chapter']}")
            elif t == "packaging":
                progress.console.print(f"  [{DIM}]packing {event['file']}[/]")
            elif t == "packaged":
                progress.console.print(f"  [{ACCENT}]created[/] {event['file']}")
            elif t == "error":
                progress.console.print(f"[red]Error:[/] {event['message']}")

    engine = DownloadEngine(options, on_event)
    try:
        with progress:
            result = engine.run()
            result_holder.update(result)
    except KeyboardInterrupt:
        engine.stop()
        console.print("\n[yellow]Stopped by user.[/]")
        return 130

    if result_holder.get("ok"):
        lines = [f"Downloaded [bold]{result_holder['downloaded']}[/] chapters to "
                 f"[bold]{result_holder['directory']}[/]"]
        for out in result_holder.get("outputs", []):
            lines.append(f"[{DIM}]{out}[/]")
        if result_holder.get("failed"):
            lines.append(f"[red]{len(result_holder['failed'])} chapters failed:[/] "
                         + ", ".join(result_holder["failed"][:8]))
        console.print(Panel("\n".join(lines), title="[bold]Complete[/]",
                            border_style=ACCENT, box=box.ROUNDED))
        return 0
    return 1


# ---------------------------------------------------------------------- main

#: Subcommands that own their entire flag set. They are handed off before the
#: main parser runs, because it would reject `--port`/`--no-auth` as unknown
#: arguments before dispatch ever happened -- `mangasurf server --port 9000`
#: died on "unrecognized arguments" while plain `mangasurf server` was read as
#: a URL to download.
DELEGATED = {
    "server": ("mangasurf.server", "main"),
    "serve": ("mangasurf.server", "main"),
    "phone": ("mangasurf.server", "main"),
    "opds": ("mangasurf.opdsserve", "main"),
    "catalog": ("mangasurf.opdsserve", "main"),
}


def main(argv=None):
    from .logs import setup_logging
    setup_logging()

    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0].lower() in DELEGATED:
        import importlib

        module_name, function = DELEGATED[raw[0].lower()]
        module = importlib.import_module(module_name)
        return getattr(module, function)(raw[1:])

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.target:
        parser.print_help()
        return 0

    command = args.target.lower()
    if command in ("sources", "source"):
        return cmd_sources()
    if command == "config":
        return cmd_config(args)
    if command == "stats":
        return cmd_stats()
    if command == "history":
        return cmd_history(args)
    if command == "lock":
        return cmd_lock(args)
    if command == "export":
        return cmd_export(args)
    if command == "watch":
        return cmd_watch(args)
    if command == "disk":
        return cmd_disk(args)
    if command in ("covers", "cover"):
        return cmd_covers(args)
    if command in ("library", "lib"):
        return cmd_library(args)
    if command == "search":
        return cmd_search(" ".join(args.query), args.source, args.language,
                          args.genre, series_type=args.type,
                          status=args.status, limit=args.limit,
                          sort=args.sort, reverse=args.reverse,
                          as_json=args.json, urls_only=args.urls,
                          open_index=args.open, download_index=args.download,
                          args=args)
    if command in ("trending", "browse", "popular"):
        return cmd_trending(args)
    if command in ("genres", "genre"):
        return cmd_genres(args)
    if command == "health":
        return cmd_health()
    if command == "api":
        return cmd_api(args)
    # "server" and "opds" never reach here -- see DELEGATED above, which
    # hands them off before the main parser can reject their flags.
    if command == "info":
        return cmd_info(args.query[0] if args.query else "",
                        args.source, args.language)
    if command == "gui":
        from .gui import run_gui
        return run_gui()
    if command == "tui":
        from .tui import run_tui
        return run_tui()
    if command in ("menu", "i", "interactive"):
        from .menu import run_menu
        return run_menu()
    if command == "resume":
        return cmd_resume(args)

    if not args.source and detect_source(args.target) is None:
        console.print(f"[red]No source recognises that URL:[/] {args.target}")
        console.print(f"[{DIM}]Supported sites:[/]")
        for meta in list_sources():
            console.print(f"  [{DIM}]{meta['name']:<14}{meta['base_url']}[/]")
        console.print(f"[{DIM}]Or search: mangasurf search \"manga name\"[/]")
        return 1
    return cmd_download(args)


if __name__ == "__main__":
    sys.exit(main())
