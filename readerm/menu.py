"""Progressive interactive menu: ``readerm menu``.

A numbered, step-by-step interface driven entirely by typing a number and
pressing Enter. It needs nothing beyond ``rich``, which is already a hard
dependency -- the full-screen TUI needs Textual, which is an optional extra
and is frequently not installed.

Design notes
------------

* **Every prompt accepts a number.** Options are always listed with an index
  so the user never has to remember a command name.
* **Every prompt accepts ``b`` and ``q``.** Back and quit work at any depth,
  so it is impossible to get stranded in a submenu.
* **Nothing is destructive without a confirmation**, and confirmations
  default to "no".
* **A paste is understood anywhere a URL is sensible**, because that is what
  people actually do with a manga link.
* Interrupts (Ctrl-C) and EOF (Ctrl-D, or a closed stdin in a pipe) unwind
  cleanly rather than dumping a traceback.
"""

import os
import sys

# Allow running this file directly (python readerm/menu.py, or PyCharm's
# "Run file"). Without this the relative imports below have no parent
# package and raise ImportError before anything else can happen.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"

# Rich is optional -- see readerm/console.py. menu.py had the same hard
# import as cli.py, so a clone without dependencies installed could not run
# `py menu.py` either: it failed at import, before printing anything.
from .console import (ACCENT, DIM, ERR, HEAD, OK, RICH, WARN, Panel, Table,
                      box, console, strip_markup)

from . import config as appconfig
from . import features, library, tracking
from .sources import (SOURCES, browse_all, detect_source, genres_all,
                      get_source, list_sources, search_all)

# console, ACCENT and DIM come from .console so the Rich and no-Rich paths
# share one palette.


class Back(Exception):
    """Raised to unwind one level of menu."""


class Quit(Exception):
    """Raised to leave the menu entirely."""


# --------------------------------------------------------------- prompting


def ask(prompt, default=None, allow_empty=False):
    """Read one line. ``b`` goes back, ``q`` quits, EOF quits cleanly."""
    suffix = f" [{DIM}]({default})[/]" if default else ""
    try:
        raw = console.input(f"[{ACCENT}]{prompt}[/]{suffix} [{DIM}]›[/] ").strip()
    except (EOFError, KeyboardInterrupt):
        # A closed stdin (piped input that ran out) or Ctrl-C must not look
        # like a crash.
        console.print()
        raise Quit from None

    low = raw.lower()
    if low in ("q", "quit", "exit"):
        raise Quit
    if low in ("b", "back"):
        raise Back
    if not raw:
        if default is not None:
            return str(default)
        if allow_empty:
            return ""
        return ask(prompt, default, allow_empty)
    return raw


def ask_number(prompt, low, high, default=None):
    """Read an integer in ``[low, high]``, re-prompting until it is valid."""
    while True:
        raw = ask(prompt, default)
        try:
            value = int(raw)
        except ValueError:
            console.print(f"[yellow]Type a number between {low} and {high}.[/]")
            continue
        if low <= value <= high:
            return value
        console.print(f"[yellow]Out of range: pick {low}-{high}.[/]")


def confirm(prompt, default=False):
    hint = "Y/n" if default else "y/N"
    raw = ask(f"{prompt} [{DIM}]({hint})[/]", allow_empty=True).lower()
    if not raw:
        return default
    return raw.startswith("y")


def choose(title, options, footer=None):
    """Show a numbered list and return the index the user picked.

    ``options`` is a list of ``(label, hint)`` pairs.
    """
    console.print()
    console.print(f"[bold]{title}[/]")
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column(justify="right", style=ACCENT, no_wrap=True)
    table.add_column()
    table.add_column(style=DIM)
    for index, item in enumerate(options, 1):
        label, hint = item if isinstance(item, (tuple, list)) else (item, "")
        table.add_row(str(index), label, hint)
    console.print(table)
    console.print(f"[{DIM}]{footer or 'b = back   q = quit'}[/]")
    return ask_number("Choose", 1, len(options)) - 1


def pause():
    try:
        console.input(f"[{DIM}]Press Enter to continue…[/]")
    except (EOFError, KeyboardInterrupt):
        raise Quit from None


def header():
    console.print()
    console.print(Panel.fit(
        "[bold]ReaderM[/]  [grey58]interactive menu[/]",
        border_style=ACCENT, box=box.ROUNDED))


# ------------------------------------------------------------ result lists


def show_results(results):
    """Print a numbered result table. Returns the list actually shown."""
    if not results:
        console.print("[yellow]No results.[/]")
        return []
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("#", style=DIM, justify="right")
    table.add_column("Title")
    table.add_column("Source", style=ACCENT)
    table.add_column("Type", style=DIM)
    for index, row in enumerate(results, 1):
        table.add_row(
            str(index),
            (row.get("title") or "?")[:58],
            row.get("source_name") or row.get("source") or "?",
            row.get("series_type") or "",
        )
    console.print(table)
    return results


def pick_result(results):
    """Let the user pick one row by number, or go back."""
    if not results:
        raise Back
    index = ask_number(f"Open which? [{DIM}](1-{len(results)})[/]",
                       1, len(results))
    return results[index - 1]


# ------------------------------------------------------------------ search


def menu_search():
    query = ask("Search for", allow_empty=True)
    source_id = pick_source(optional=True)

    with console.status(f"Searching for [bold]{query}[/]…"):
        if source_id:
            source = get_source(source_id)
            try:
                results = source.search(query, limit=25)
            finally:
                source.close()
        else:
            results = search_all(query, limit=8)
        results = features.apply_filters(results)

    features.add_history(query, source_id or "all", len(results))
    shown = show_results(results)
    if not shown:
        pause()
        return
    manga_menu(pick_result(shown)["url"])


def menu_trending():
    genre = None
    if confirm("Filter by genre?"):
        genre = pick_genre()
    with console.status("Fetching trending titles…"):
        results = features.apply_filters(browse_all(genre=genre, limit=8))
    shown = show_results(results)
    if not shown:
        pause()
        return
    manga_menu(pick_result(shown)["url"])


def menu_url():
    url = ask("Paste a manga URL")
    if detect_source(url) is None:
        console.print("[yellow]No source recognises that link.[/]")
        pause()
        return
    manga_menu(url)


# ------------------------------------------------------------------ pickers


def pick_source(optional=False):
    """Return a source id, or "" for all sources."""
    rows = [meta for meta in list_sources()]
    options = []
    if optional:
        options.append(("All sources", "search every enabled site"))
    for meta in rows:
        flags = []
        if meta.get("adult_only"):
            flags.append("18+")
        if meta.get("needs_flaresolverr"):
            flags.append("needs FlareSolverr")
        options.append((meta["name"], ", ".join(flags)))

    index = choose("Which source?", options)
    if optional:
        if index == 0:
            return ""
        return rows[index - 1]["id"]
    return rows[index]["id"]


def pick_genre():
    with console.status("Loading genres…"):
        genres = genres_all()
    if not genres:
        return None
    names = [(g["name"], f"{len(g.get('sources', {}))} sources") for g in genres[:40]]
    return genres[choose("Which genre?", names)]["name"]


# ------------------------------------------------------------- manga screen


def manga_menu(url):
    with console.status("Loading manga…"):
        source = get_source(detect_source(url) or "")
        try:
            info = source.get_manga_info(url)
            chapters = source.get_chapters(url)
        finally:
            source.close()

    downloaded = set(library.match_downloaded(url, chapters))

    console.print()
    console.print(Panel(
        f"[bold]{info.get('title', '?')}[/]\n"
        f"[{DIM}]{info.get('status') or 'Unknown status'} · "
        f"{len(chapters)} chapters · {len(downloaded)} downloaded[/]",
        border_style=ACCENT, box=box.ROUNDED))

    while True:
        try:
            index = choose("What now?", [
                ("Download all chapters", f"{len(chapters)} chapters"),
                ("Download a range", "e.g. 1-20, 25, 30-"),
                ("Download only new ones",
                 f"{len(chapters) - len(downloaded)} not yet downloaded"),
                ("List chapters", ""),
                ("Show details", "authors, year, tags"),
                ("Bookmark", ""),
                ("Watch for updates", ""),
            ])
        except Back:
            return

        if index == 0:
            run_download(url, "all", info)
        elif index == 1:
            spec = ask("Chapters", "all")
            run_download(url, spec, info)
        elif index == 2:
            fresh = [c["name"] for c in chapters if c["name"] not in downloaded]
            if not fresh:
                console.print("[yellow]Everything is already downloaded.[/]")
                pause()
                continue
            from .utils import chapter_number
            spec = ",".join(
                str(chapter_number(name)).rstrip("0").rstrip(".")
                for name in fresh)
            run_download(url, spec or "all", info)
        elif index == 3:
            list_chapters(chapters, downloaded)
        elif index == 4:
            show_details(info)
        elif index == 5:
            library.toggle_bookmark(info)
            console.print("[green]Bookmark toggled.[/]")
            pause()
        elif index == 6:
            tracking.watch(url, info.get("title", "?"), len(chapters))
            console.print("[green]Now watching for new chapters.[/]")
            pause()


def list_chapters(chapters, downloaded):
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("#", style=DIM, justify="right")
    table.add_column("Chapter")
    table.add_column("", style="green")
    for index, chapter in enumerate(chapters, 1):
        mark = "✓" if chapter["name"] in downloaded else ""
        table.add_row(str(index), chapter["name"], mark)
    console.print(table)
    pause()


def show_details(info):
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column(style=DIM)
    table.add_column()
    for label, key in (("Title", "title"), ("Status", "status"),
                       ("Year", "year"), ("Type", "series_type"),
                       ("Language", "original_language"),
                       ("Demographic", "demographic")):
        value = info.get(key)
        if value:
            table.add_row(label, str(value))
    if info.get("authors"):
        table.add_row("Authors", ", ".join(info["authors"][:5]))
    if info.get("tags"):
        table.add_row("Tags", ", ".join(info["tags"][:10]))
    console.print(table)
    pause()


def run_download(url, selection, info):
    settings = _settings()
    fmt_names = ["cbz", "pdf", "epub", "images"]
    fmt = fmt_names[choose("Format?", [
        ("CBZ", "comic archive, the usual choice"),
        ("PDF", ""),
        ("EPUB", ""),
        ("Images", "loose files, no packaging"),
    ])]

    output = ask("Save to", settings.get("output_dir") or "downloads")
    if not confirm(f"Download [{ACCENT}]{selection}[/] as {fmt.upper()} "
                   f"into {output}?", default=True):
        return

    from .cli import _run_rich
    from .downloader import DownloadOptions

    options = DownloadOptions(
        url=url,
        selection=selection,
        output_dir=output,
        format=fmt,
        chapter_workers=int(settings.get("chapter_workers", 3) or 3),
        image_workers=int(settings.get("image_workers", 6) or 6),
        delay=float(settings.get("delay", 0.5) or 0.5),
        retries=int(settings.get("retries", 5) or 5),
        name_single=settings.get("name_single") or "{title} - Chapters {chapters}",
        name_chapter=settings.get("name_chapter") or "{title} - Chapter {chapter}",
        name_range=settings.get("name_range") or "{title} - Chapters {chapters}",
    )
    _run_rich(options, skip_confirm=True)
    pause()


def _settings():
    from .gui import load_settings
    return load_settings()


# --------------------------------------------------------------- library


def menu_library():
    entries = list(library.load_library().values())
    if not entries:
        console.print("[yellow]The library is empty.[/]")
        pause()
        return
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("#", style=DIM, justify="right")
    table.add_column("Title")
    table.add_column("Chapters", justify="right", style=DIM)
    table.add_column("Last download", style=DIM)
    for index, entry in enumerate(entries, 1):
        table.add_row(str(index), entry.get("title", "?"),
                      str(len(entry.get("chapters", {}))),
                      entry.get("last_download", ""))
    console.print(table)

    if confirm("Open one?"):
        entry = entries[ask_number("Which", 1, len(entries)) - 1]
        manga_menu(entry.get("url"))


def menu_bookmarks():
    data = library.folders_with_contents()
    rows = list(data["unfiled"])
    for folder in data["folders"]:
        rows.extend(folder.get("items", []))
    if not rows:
        console.print("[yellow]No bookmarks yet.[/]")
        pause()
        return
    table = Table(box=box.SIMPLE_HEAD, header_style=f"bold {ACCENT}")
    table.add_column("#", style=DIM, justify="right")
    table.add_column("Title")
    table.add_column("Source", style=ACCENT)
    for index, row in enumerate(rows, 1):
        table.add_row(str(index), row.get("title", "?"),
                      row.get("source_name") or row.get("source") or "")
    console.print(table)
    if confirm("Open one?"):
        manga_menu(rows[ask_number("Which", 1, len(rows)) - 1]["url"])


# --------------------------------------------------------------- settings


def menu_settings():
    from .gui import load_settings, update_settings

    while True:
        settings = load_settings()
        try:
            index = choose("Settings", [
                ("Download folder", settings.get("output_dir", "")),
                ("Default format", settings.get("format", "cbz")),
                ("Concurrent chapters", str(settings.get("chapter_workers", 3))),
                ("Images per chapter", str(settings.get("image_workers", 6))),
                ("Delay between chapters", f"{settings.get('delay', 0.5)}s"),
                ("Retries", str(settings.get("retries", 5))),
                ("Sources", "enable, disable and reorder"),
                ("Content filters", "safe mode, chapter counts"),
            ])
        except Back:
            return

        if index == 0:
            update_settings({"output_dir": ask("Download folder",
                                               settings.get("output_dir"))})
        elif index == 1:
            fmt = ["cbz", "pdf", "epub", "images"][
                choose("Default format", ["CBZ", "PDF", "EPUB", "Images"])]
            update_settings({"format": fmt})
        elif index == 2:
            update_settings({"chapter_workers":
                             ask_number("Concurrent chapters", 1, 8, 3)})
        elif index == 3:
            update_settings({"image_workers":
                             ask_number("Images per chapter", 1, 10, 6)})
        elif index == 4:
            raw = ask("Delay in seconds", str(settings.get("delay", 0.5)))
            try:
                update_settings({"delay": max(0.0, float(raw))})
            except ValueError:
                console.print("[yellow]Not a number.[/]")
        elif index == 5:
            update_settings({"retries": ask_number("Retries", 1, 10, 5)})
        elif index == 6:
            menu_sources()
            continue
        elif index == 7:
            menu_filters()
            continue
        console.print("[green]Saved.[/]")


def menu_sources():
    while True:
        rows = appconfig.describe()
        options = []
        for row in rows:
            state = "on " if row.get("enabled", True) else "off"
            options.append((f"[{state}] {row['name']}",
                            f"rank {row.get('rank', 0)}"))
        options.append(("Done", ""))
        try:
            index = choose("Toggle a source", options)
        except Back:
            return
        if index == len(rows):
            return
        row = rows[index]
        appconfig.set_enabled(row["id"], not row.get("enabled", True))


def menu_filters():
    while True:
        current = features.get_filters()
        try:
            index = choose("Content filters", [
                ("Safe mode", "on" if current.get("safe_mode") else "off"),
                ("Minimum chapters", str(current.get("min_chapters", 0))),
                ("Maximum chapters", str(current.get("max_chapters", 0))),
                ("Strict chapter range",
                 "on" if current.get("strict_chapter_range") else "off"),
                ("Hide results with no cover",
                 "on" if current.get("hide_no_cover") else "off"),
            ])
        except Back:
            return
        if index == 0:
            features.set_filters(safe_mode=not current.get("safe_mode"))
        elif index == 1:
            features.set_filters(min_chapters=ask_number("Minimum", 0, 10000, 0))
        elif index == 2:
            features.set_filters(max_chapters=ask_number("Maximum", 0, 10000, 0))
        elif index == 3:
            features.set_filters(
                strict_chapter_range=not current.get("strict_chapter_range"))
        elif index == 4:
            features.set_filters(hide_no_cover=not current.get("hide_no_cover"))


# -------------------------------------------------------------- top level


def menu_tools():
    try:
        index = choose("Tools", [
            ("Download statistics", ""),
            ("Search history", ""),
            ("Watched series", ""),
            ("Verify library files", "check everything still exists"),
            ("Disk usage", ""),
        ])
    except Back:
        return

    from . import cli
    if index == 0:
        cli.cmd_stats()
    elif index == 1:
        for entry in features.get_history(20):
            console.print(f"  [{DIM}]{entry.get('when', '')}[/]  "
                          f"{entry.get('query', '')}")
    elif index == 2:
        for entry in tracking.get_watchlist():
            console.print(f"  {entry.get('title', '?')}")
    elif index == 3:
        report = library.verify_entries()
        console.print(f"  missing: {len(report['missing'])}")
    elif index == 4:
        usage = tracking.disk_usage()
        console.print(f"  {features.human_size(usage.get('total', 0))} total")
    pause()


MAIN_MENU = [
    ("Search for a manga", "by title, across every source"),
    ("Browse trending", "discovery, optionally by genre"),
    ("Open a URL", "paste a link from any supported site"),
    ("Library", "what you have already downloaded"),
    ("Bookmarks", ""),
    ("Settings", "folders, formats, sources, filters"),
    ("Tools", "stats, history, watchlist, disk usage"),
    ("Quit", ""),
]


def run_menu(argv=None):
    """Entry point for ``readerm menu``."""
    from .logs import setup_logging
    setup_logging()

    if not sys.stdin.isatty():
        console.print("[yellow]The interactive menu needs a terminal.[/]")
        console.print(f"[{DIM}]Try: readerm search \"one piece\"[/]")
        return 1

    header()
    console.print(f"[{DIM}]Type a number and press Enter. "
                  f"b = back, q = quit.[/]")

    while True:
        try:
            index = choose("Main menu", MAIN_MENU,
                           footer="q = quit")
            if index == 0:
                menu_search()
            elif index == 1:
                menu_trending()
            elif index == 2:
                menu_url()
            elif index == 3:
                menu_library()
            elif index == 4:
                menu_bookmarks()
            elif index == 5:
                menu_settings()
            elif index == 6:
                menu_tools()
            elif index == 7:
                raise Quit
        except Back:
            continue          # back at the top level just redraws the menu
        except Quit:
            console.print(f"[{DIM}]Bye.[/]")
            return 0
        except Exception as exc:            # noqa: BLE001 - never crash out
            console.print(f"[red]Something went wrong:[/] {exc}")
            try:
                pause()
            except Quit:
                return 0


if __name__ == "__main__":
    sys.exit(run_menu())
