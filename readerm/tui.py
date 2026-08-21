"""Mangasurf - full-screen terminal UI (Textual).

Launch with:  mangasurf tui
         or:  python -m readerm tui
"""

import os
import sys
import threading

# Allow running this file directly (python readerm/tui.py): register the
# parent directory so the 'readerm' package resolves for relative imports.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"

# Textual is an optional extra ("pip install mangasurf[tui]"). Importing it at
# module scope means a missing install crashes `mangasurf tui` with a raw
# ModuleNotFoundError: the friendly message in run_tui() never gets to print,
# because the module fails while it is still being imported. Stand-ins keep
# the module importable so run_tui() can explain itself instead.
try:
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import (Button, Footer, Header, Input, Label,
                                 ListItem, ListView, ProgressBar, RichLog,
                                 Select, SelectionList, Static, Switch,
                                 TabbedContent, TabPane)
    from textual.widgets.selection_list import Selection

    TEXTUAL_AVAILABLE = True
except ImportError:                    # pragma: no cover - install dependent
    TEXTUAL_AVAILABLE = False

    App = object
    ComposeResult = object

    def on(*_args, **_kwargs):
        return lambda fn: fn

    def work(*_args, **_kwargs):
        return lambda fn: fn

    def Binding(*_args, **_kwargs):
        return None

    class _MissingMeta(type):
        """Any attribute lookup yields another placeholder."""
        def __getattr__(cls, _name):
            return cls

    class _Missing(metaclass=_MissingMeta):
        """Placeholder widget; only reachable when Textual is absent."""
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("Textual is not installed")

    Horizontal = Vertical = VerticalScroll = _Missing
    Button = Footer = Header = Input = Label = _Missing
    ListItem = ListView = ProgressBar = RichLog = _Missing
    Select = SelectionList = Static = Switch = _Missing
    TabbedContent = TabPane = Selection = _Missing

from .downloader import DownloadEngine, DownloadOptions
from .gui import load_settings, save_settings
from .sources import (DEFAULT_SOURCE, SOURCES, browse_all, detect_source,
                      genres_all, get_source, list_sources, search_all,
                      source_for_url)
from .utils import chapter_number
from .console import format_source_badge, format_colored_tag

ACCENT = "#7aa2f7"


# --------------------------------------------------------------------- app


class MangasurfTUI(App):
    """Search, browse and download manga without leaving the terminal."""

    TITLE = "Mangasurf"
    SUB_TITLE = "terminal edition"

    CSS = """
    Screen { background: $surface; }

    .hidden { display: none; }

    TabbedContent { height: 1fr; }
    TabPane { padding: 1 2; }

    /* ------------------------------------------------------- search tab */
    #src-help { color: $text-muted; margin-bottom: 1; height: auto; }
    #src-rank-list { height: 1fr; border: round $primary 30%; }
    #src-rank-list:focus { border: round $primary; }
    #src-actions { height: 3; margin-top: 1; }
    #src-actions Button { margin-right: 1; min-width: 12; }

    #search-bar { height: 3; margin-bottom: 1; }
    #source-select { width: 20; margin-right: 1; }
    #genre-select { width: 18; margin-left: 1; }
    #search-input { width: 1fr; }
    #search-btn { margin-left: 1; min-width: 12; }
    #search-status { color: $text-muted; height: 1; margin-bottom: 1; }
    #search-results { height: 1fr; border: round $primary 30%; }
    #search-results:focus-within { border: round $primary; }
    .result-title { text-style: bold; }
    .result-url { color: $text-muted; }

    /* -------------------------------------------------------- manga tab */
    #manga-empty { height: 1fr; content-align: center middle; color: $text-muted; }
    #manga-body { height: 1fr; }
    #manga-info {
        width: 44; min-width: 32; margin-right: 2;
        border: round $primary 30%; padding: 1 1;
    }
    #manga-cover {
        height: auto; min-height: 8; content-align: center middle;
        margin-bottom: 1; border: round $primary 20%; padding: 0;
    }
    #manga-title { text-style: bold; color: $primary; }
    #manga-source { color: $text-muted; text-style: italic; }
    #manga-meta { color: $text-muted; margin-top: 1; }
    #manga-tags { color: $secondary; margin-top: 1; }
    #manga-desc { margin-top: 1; color: $text 80%; }

    #manga-right { width: 1fr; }
    .opt-row { height: 3; margin-bottom: 1; }
    .opt-row Label { width: 12; content-align: left middle; height: 3; color: $text-muted; }
    .opt-row Select { width: 26; }
    .opt-row Input { width: 1fr; }
    #bundle-n { width: 10; margin-left: 1; }

    #chapter-tools { height: 3; margin-bottom: 1; }
    #range-input { width: 1fr; }
    #chapter-tools Button { margin-left: 1; min-width: 8; }
    #chapter-list { height: 1fr; border: round $primary 30%; }
    #chapter-list:focus { border: round $primary; }
    #download-row { height: 3; margin-top: 1; }
    #download-btn { width: 1fr; }
    #sel-count { width: 24; content-align: right middle; height: 3; color: $text-muted; }

    /* ---------------------------------------------------- downloads tab */
    #dl-empty { height: 1fr; content-align: center middle; color: $text-muted; }
    #dl-body { height: 1fr; }
    #dl-title { text-style: bold; color: $primary; height: 1; }
    #dl-status { color: $text-muted; height: 1; margin-bottom: 1; }
    #overall-row { height: 1; margin-bottom: 1; }
    #overall-bar { width: 1fr; }
    #overall-bar Bar { width: 1fr; }
    #overall-text { width: 14; content-align: right middle; }
    #active-box { height: auto; max-height: 12; border: round $primary 30%; padding: 0 1; margin-bottom: 1; }
    .ac-row { height: 1; }
    .ac-name { width: 30; }
    .ac-bar { width: 1fr; }
    .ac-bar Bar { width: 1fr; }
    .ac-count { width: 10; content-align: right middle; color: $text-muted; }
    #dl-log { height: 1fr; border: round $primary 30%; }
    #dl-actions { height: 3; margin-top: 1; }
    #stop-btn { min-width: 14; }

    /* ----------------------------------------------------- settings tab */
    #settings-box { width: 70; }
    .set-row { height: 3; margin-bottom: 1; }
    .set-row Label { width: 34; content-align: left middle; height: 3; }
    .set-row Input { width: 12; }
    .set-row Select { width: 22; }
    .set-hint { color: $text-muted; margin-bottom: 1; }
    #set-output { width: 34; }
    #save-flash { color: $success; margin-left: 2; content-align: left middle; height: 3; }
    """

    BINDINGS = [
        Binding("ctrl+s", "focus_search", "Search"),
        Binding("ctrl+d", "start_download", "Download"),
        Binding("ctrl+x", "stop_download", "Stop"),
        Binding("f1", "switch_tab('tab-search')", "Search tab", show=False),
        Binding("f2", "switch_tab('tab-manga')", "Manga tab", show=False),
        Binding("f3", "switch_tab('tab-downloads')", "Downloads tab", show=False),
        Binding("f4", "switch_tab('tab-sources')", "Sources tab", show=False),
        Binding("f5", "switch_tab('tab-settings')", "Settings tab", show=False),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.source_id = self.settings.get("default_source") or "all"
        self.source = None           # active Source for the open manga
        self.manga = None            # {info, chapters}
        self.results = []
        self.engine = None
        self.dl_thread = None
        self.active_rows = {}        # chapter name -> row widget
        self.total = 0

    # ------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-search"):

            with TabPane("Search", id="tab-search"):
                with Horizontal(id="search-bar"):
                    yield Select(
                        [("All sources", "all")]
                        + [(meta["name"], meta["id"]) for meta in list_sources()],
                        value=self.source_id if self.source_id in
                        ({"all"} | set(SOURCES)) else "all",
                        allow_blank=False,
                        id="source-select",
                    )
                    yield Input(
                        placeholder="Search manga or paste a manga URL...",
                        id="search-input",
                    )
                    yield Select([("Any genre", "")], value="", allow_blank=False,
                                 id="genre-select")
                    yield Button("Search", variant="primary", id="search-btn")
                yield Static("", id="search-status")
                yield ListView(id="search-results")

            with TabPane("Manga", id="tab-manga"):
                yield Static("Search for a manga first  (Ctrl+S)", id="manga-empty")
                with Horizontal(id="manga-body", classes="hidden"):
                    with VerticalScroll(id="manga-info"):
                        yield Static("", id="manga-cover")
                        yield Static("", id="manga-title")
                        yield Static("", id="manga-source")
                        yield Static("", id="manga-meta")
                        yield Static("", id="manga-tags")
                        yield Static("", id="manga-desc")
                    with Vertical(id="manga-right"):
                        with Horizontal(classes="opt-row"):
                            yield Label("Format")
                            yield Select(
                                [("CBZ", "cbz"), ("PDF", "pdf"), ("EPUB", "epub"),
                                 ("Images", "images")],
                                value="cbz", allow_blank=False, id="fmt-select",
                            )
                        with Horizontal(classes="opt-row"):
                            yield Label("Bundling")
                            yield Select(
                                [("Single file", "0"), ("Per chapter", "1"),
                                 ("Every N chapters", "n")],
                                value="0", allow_blank=False, id="bundle-select",
                            )
                            yield Input(value="10", id="bundle-n", type="integer",
                                        classes="hidden")
                        with Horizontal(classes="opt-row"):
                            yield Label("Save to")
                            yield Input(value=self.settings["output_dir"], id="output-dir")
                        with Horizontal(id="chapter-tools"):
                            yield Input(placeholder="Quick select: 1-20, 25, 30-40",
                                        id="range-input")
                            yield Button("Apply", id="range-btn")
                            yield Button("All", id="all-btn")
                            yield Button("None", id="none-btn")
                            yield Button("Latest", id="latest-btn")
                        yield SelectionList(id="chapter-list")
                        with Horizontal(id="download-row"):
                            yield Button("Download", variant="success", id="download-btn")
                            yield Static("", id="sel-count")

            with TabPane("Downloads", id="tab-downloads"):
                yield Static("No active downloads", id="dl-empty")
                with Vertical(id="dl-body", classes="hidden"):
                    yield Static("", id="dl-title")
                    yield Static("", id="dl-status")
                    with Horizontal(id="overall-row"):
                        yield ProgressBar(id="overall-bar", show_eta=False)
                        yield Static("0 / 0", id="overall-text")
                    yield Vertical(id="active-box")
                    yield RichLog(id="dl-log", markup=True, wrap=True)
                    with Horizontal(id="dl-actions"):
                        yield Button("Stop", variant="error", id="stop-btn")

            with TabPane("Sources", id="tab-sources"):
                yield Static(
                    "Rank sources with the buttons; higher sources win when the "
                    "same series appears on several sites. Space toggles a source "
                    "on or off.", id="src-help")
                yield ListView(id="src-rank-list")
                with Horizontal(id="src-actions"):
                    yield Button("Move up", id="src-up")
                    yield Button("Move down", id="src-down")
                    yield Button("Toggle", id="src-toggle")
                    yield Button("Reset", id="src-reset")

            with TabPane("Settings", id="tab-settings"):
                with Vertical(id="settings-box"):
                    yield Static("Changes apply to new downloads. Saved to "
                                 "~/.mangasurf/settings.json", classes="set-hint")
                    with Horizontal(classes="set-row"):
                        yield Label("Output directory")
                        yield Input(value=self.settings["output_dir"], id="set-output")
                    with Horizontal(classes="set-row"):
                        yield Label("Default format")
                        yield Select(
                            [("CBZ", "cbz"), ("PDF", "pdf"), ("EPUB", "epub"),
                             ("Images", "images")],
                            value=self.settings.get("format", "cbz"),
                            allow_blank=False, id="set-format",
                        )
                    with Horizontal(classes="set-row"):
                        yield Label("Concurrent chapters (1-8)")
                        yield Input(value=str(self.settings["chapter_workers"]),
                                    id="set-chapter-workers", type="integer")
                    with Horizontal(classes="set-row"):
                        yield Label("Images per chapter (1-10)")
                        yield Input(value=str(self.settings["image_workers"]),
                                    id="set-image-workers", type="integer")
                    with Horizontal(classes="set-row"):
                        yield Label("Delay between chapters (s)")
                        yield Input(value=str(self.settings["delay"]),
                                    id="set-delay", type="number")
                    with Horizontal(classes="set-row"):
                        yield Switch(value=self.settings.get("keep_images", False),
                                     id="set-keep")
                    with Horizontal(classes="set-row"):
                        yield Button("Save settings", variant="primary", id="save-btn")
                        yield Static("", id="save-flash")

        yield Footer()

    # ------------------------------------------------------------ sources

    def _refresh_source_list(self):
        from . import config as appconfig

        listview = self.query_one("#src-rank-list", ListView)
        index = listview.index or 0
        listview.clear()
        self._source_rows = appconfig.describe()
        for position, row in enumerate(self._source_rows, 1):
            enabled = row.get("enabled", True)
            mark = f"[{ACCENT}]on[/]" if enabled else "[red]off[/]"
            caps = []
            if row.get("supports_language"):
                caps.append("languages")
            if row.get("needs_flaresolverr"):
                caps.append("cloudflare")
            suffix = f"  [dim]{', '.join(caps)}[/]" if caps else ""
            listview.append(ListItem(Static(
                f"[dim]{position}.[/] [bold]{row.get('name', row['id'])}[/]  "
                f"{mark}{suffix}\n[dim]{row.get('base_url', '')}[/]"
            )))
        if self._source_rows:
            listview.index = min(index, len(self._source_rows) - 1)

    def _selected_source(self):
        rows = getattr(self, "_source_rows", [])
        listview = self.query_one("#src-rank-list", ListView)
        index = listview.index
        if index is None or not rows or index >= len(rows):
            return None
        return rows[index]["id"]

    @on(Button.Pressed, "#src-up")
    def handle_source_up(self, _e):
        from . import config as appconfig
        sid = self._selected_source()
        if not sid:
            return
        appconfig.move(sid, -1)
        self._refresh_source_list()

    @on(Button.Pressed, "#src-down")
    def handle_source_down(self, _e):
        from . import config as appconfig
        sid = self._selected_source()
        if not sid:
            return
        appconfig.move(sid, 1)
        self._refresh_source_list()

    @on(Button.Pressed, "#src-toggle")
    def handle_source_toggle(self, _e):
        from . import config as appconfig
        sid = self._selected_source()
        if not sid:
            return
        row = next((r for r in self._source_rows if r["id"] == sid), None)
        if not row:
            return
        appconfig.set_enabled(sid, not row.get("enabled", True))
        self._refresh_source_list()

    @on(Button.Pressed, "#src-reset")
    def handle_source_reset(self, _e):
        from . import config as appconfig
        appconfig.reset_config()
        self._refresh_source_list()

    def on_mount(self):
        self._load_genres()
        self._refresh_source_list()

    # ---------------------------------------------------------- bindings

    def action_focus_search(self):
        self.query_one(TabbedContent).active = "tab-search"
        self.query_one("#search-input", Input).focus()

    def action_start_download(self):
        self._start_download()

    def action_stop_download(self):
        if self.engine:
            self.engine.stop()
            self._set_status("Stopping...")

    # ------------------------------------------------------------ search

    @on(Input.Submitted, "#search-input")
    @on(Button.Pressed, "#search-btn")
    def handle_search(self, _event=None):
        query = self.query_one("#search-input", Input).value.strip()
        # An empty box is no longer a no-op: it means "show me trending".
        if query and (query.startswith(("http://", "https://"))
                      or detect_source(query)):
            self._load_manga(query)
            return

        genre = self._genre()
        if query:
            label = f"[dim]Searching for[/] [bold]{query}[/] ..."
        elif genre:
            label = f"[dim]Loading top[/] [bold]{genre}[/] ..."
        else:
            label = "[dim]Loading[/] [bold]trending[/] ..."
        self.query_one("#search-status", Static).update(label)
        self.query_one("#search-results", ListView).clear()
        self._do_search(query)

    def _genre(self):
        try:
            value = self.query_one("#genre-select", Select).value
            return str(value) if value else None
        except Exception:
            return None

    @work(thread=True, exclusive=True, group="search")
    def _do_search(self, query: str):
        genre = self._genre()
        language = self.settings.get("language", "en")
        try:
            if not query:
                # no query: show trending, optionally narrowed to a genre
                if self.source_id in ("all", None, ""):
                    results = browse_all(genre=genre, limit=8)
                else:
                    source = get_source(self.source_id, language=language)
                    try:
                        results = (source.browse(genre=genre, limit=30)
                                   if getattr(source, "supports_browse", False)
                                   else [])
                    finally:
                        source.close()
            elif self.source_id in ("all", None, ""):
                results = search_all(query, limit=12, genre=genre)
            else:
                source = get_source(self.source_id, language=language)
                try:
                    results = source.search(query, genre=genre)
                finally:
                    source.close()
            from . import features
            results = features.apply_filters(results)
        except Exception as e:
            self.call_from_thread(self._search_done, [], str(e))
            return
        self.call_from_thread(self._search_done, results, None)

    @work(thread=True, group="genres")
    def _load_genres(self):
        try:
            if self.source_id in ("all", None, ""):
                rows = genres_all()
            else:
                source = get_source(self.source_id)
                try:
                    rows = [{"name": g["name"]} for g in (source.genres() or [])]
                finally:
                    source.close()
        except Exception:
            rows = []
        self.call_from_thread(self._genres_loaded, rows)

    def _genres_loaded(self, rows):
        try:
            select = self.query_one("#genre-select", Select)
        except Exception:
            return
        current = select.value
        options = [("Any genre", "")] + [(r["name"], r["name"]) for r in rows[:60]]
        select.set_options(options)
        if any(value == current for _label, value in options):
            select.value = current

    @on(Select.Changed, "#genre-select")
    def handle_genre_changed(self, event: Select.Changed):
        self.handle_search()

    @on(Select.Changed, "#source-select")
    def handle_source_changed(self, event: Select.Changed):
        self.source_id = str(event.value)
        self.settings["default_source"] = self.source_id
        try:
            save_settings(self.settings)
        except Exception:
            pass
        self._load_genres()
        self.handle_search()

    def _search_done(self, results, error):
        status = self.query_one("#search-status", Static)
        listview = self.query_one("#search-results", ListView)
        listview.clear()
        if error:
            status.update(f"[red]Search failed: {error}[/]")
            return
        if not results:
            status.update("[yellow]Nothing to show. Try another genre, or "
                          "enable more sources.[/]")
            return
        self.results = results
        status.update(f"[dim]{len(results)} results - press Enter to open[/]")
        for r in results:
            src_name = r.get("source_name") or r.get("source") or ""
            badge = format_source_badge(r.get("source") or "", src_name)
            tag = f"{badge} " if src_name else ""
            listview.append(ListItem(
                Static(f"{tag}[bold {ACCENT}]{r['title']}[/]\n[dim]{r['url']}[/]")
            ))
        listview.focus()

    @on(ListView.Selected, "#search-results")
    def handle_result_selected(self, event: ListView.Selected):
        index = event.list_view.index
        if index is not None and 0 <= index < len(self.results):
            result = self.results[index]
            self._load_manga(result["url"], result.get("source"))

    # ------------------------------------------------------------- manga

    def _load_manga(self, url: str, source_id: str = None):
        self.query_one(TabbedContent).active = "tab-manga"
        self.query_one("#manga-empty", Static).update("Loading manga ...")
        self.query_one("#manga-empty").remove_class("hidden")
        self.query_one("#manga-body").add_class("hidden")
        self._fetch_manga(url, source_id)

    @work(thread=True, exclusive=True, group="manga")
    def _fetch_manga(self, url: str, source_id: str = None):
        try:
            language = self.settings.get("language", "en")
            if not source_id and self.source_id not in ("all", None, ""):
                source_id = self.source_id
            source = (get_source(source_id, language=language) if source_id
                      else source_for_url(url, language=language))
            self.source = source
            info = source.get_manga_info(url)
            chapters = source.get_chapters(url)
        except Exception as e:
            self.call_from_thread(self._manga_failed, str(e))
            return
        self.call_from_thread(self._manga_loaded, info, chapters)

    def _manga_failed(self, error):
        self.query_one("#manga-empty", Static).update(f"[red]Failed to load: {error}[/]")

    def _manga_loaded(self, info, chapters):
        self.manga = {"info": info, "chapters": chapters}
        self.query_one("#manga-empty").add_class("hidden")
        self.query_one("#manga-body").remove_class("hidden")

        # Start background cover render
        self.query_one("#manga-cover", Static).update("[dim]Loading cover...[/]")
        self._fetch_cover_art(info)

        self.query_one("#manga-title", Static).update(info["title"])
        provider = info.get("source_name") or (
            self.source.name if self.source else info.get("source") or "")
        badge = format_source_badge(info.get("source") or (self.source.id if self.source else ""), provider)
        self.query_one("#manga-source", Static).update(
            f"[dim]from[/] {badge}" if provider else "")
        meta = []
        if info.get("authors"):
            meta.append("by " + ", ".join(info["authors"]))
        if info.get("status"):
            status_color = "green" if str(info['status']).lower() == "ongoing" else ACCENT
            meta.append(f"[{status_color}]{info['status']}[/]")
        meta.append(f"{len(chapters)} chapters")
        self.query_one("#manga-meta", Static).update("  |  ".join(meta))
        
        # Tags formatted with vibrant per-category colors
        tags = info.get("tags") or []
        if tags:
            tag_badges = " ".join(format_colored_tag(t) for t in tags[:12])
            self.query_one("#manga-tags", Static).update(f"[dim]tags:[/] {tag_badges}")
        else:
            self.query_one("#manga-tags", Static).update("")
            
        self.query_one("#manga-desc", Static).update(info.get("description") or "")

        sel = self.query_one("#chapter-list", SelectionList)
        sel.clear_options()
        # newest first, all selected by default
        for i in range(len(chapters) - 1, -1, -1):
            sel.add_option(Selection(chapters[i]["name"], i, True))
        self._update_count()

    @work(thread=True, group="cover")
    def _fetch_cover_art(self, info):
        cover_url = info.get("cover")
        if not cover_url:
            self.call_from_thread(self._cover_ready, "")
            return
        try:
            from .covers import render_terminal_cover
            ansi_art = render_terminal_cover(cover_url, width=28, max_height=14,
                                             source_id=info.get("source"),
                                             referer=info.get("url"))
        except Exception:
            ansi_art = ""
        self.call_from_thread(self._cover_ready, ansi_art)

    def _cover_ready(self, ansi_art):
        try:
            cover_widget = self.query_one("#manga-cover", Static)
            if not ansi_art:
                cover_widget.update("[dim]No cover art[/]")
                return
            try:
                from rich.text import Text
                cover_widget.update(Text.from_ansi(ansi_art))
            except Exception:
                cover_widget.update(ansi_art)
        except Exception:
            pass

    def _update_count(self):
        if not self.manga:
            return
        sel = self.query_one("#chapter-list", SelectionList)
        n, total = len(sel.selected), len(self.manga["chapters"])
        self.query_one("#sel-count", Static).update(f"[dim]{n} / {total} selected[/]")
        btn = self.query_one("#download-btn", Button)
        btn.label = f"Download {n} chapter{'s' if n != 1 else ''}" if n else "Select chapters"
        btn.disabled = n == 0

    @on(SelectionList.SelectedChanged, "#chapter-list")
    def handle_selection_change(self, _event):
        self._update_count()

    @on(Button.Pressed, "#all-btn")
    def handle_all(self, _e):
        self.query_one("#chapter-list", SelectionList).select_all()

    @on(Button.Pressed, "#none-btn")
    def handle_none(self, _e):
        self.query_one("#chapter-list", SelectionList).deselect_all()

    @on(Button.Pressed, "#latest-btn")
    def handle_latest(self, _e):
        sel = self.query_one("#chapter-list", SelectionList)
        sel.deselect_all()
        if self.manga and self.manga["chapters"]:
            sel.select(len(self.manga["chapters"]) - 1)

    @on(Input.Submitted, "#range-input")
    @on(Button.Pressed, "#range-btn")
    def handle_range(self, _e=None):
        spec = self.query_one("#range-input", Input).value.strip()
        if not spec or not self.manga:
            return
        chapters = self.manga["chapters"]
        wanted = set()
        try:
            for part in spec.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    lo_s, hi_s = part.split("-", 1)
                    lo, hi = float(lo_s.strip()), float(hi_s.strip())
                    for i, c in enumerate(chapters):
                        num = chapter_number(c["name"])
                        if lo <= num <= hi:
                            wanted.add(i)
                else:
                    target = float(part)
                    for i, c in enumerate(chapters):
                        if chapter_number(c["name"]) == target:
                            wanted.add(i)
        except ValueError:
            self.notify("Invalid selection syntax", severity="error")
            return
        if not wanted:
            self.notify("No chapters matched", severity="warning")
            return
        sel = self.query_one("#chapter-list", SelectionList)
        sel.deselect_all()
        for i in wanted:
            sel.select(i)
        self.notify(f"Selected {len(wanted)} chapters")

    @on(Select.Changed, "#bundle-select")
    def handle_bundle_change(self, event: Select.Changed):
        n_input = self.query_one("#bundle-n", Input)
        n_input.set_class(event.value != "n", "hidden")

    # ---------------------------------------------------------- download

    @on(Button.Pressed, "#download-btn")
    def handle_download(self, _e):
        self._start_download()

    def _start_download(self):
        if not self.manga:
            self.notify("Open a manga first", severity="warning")
            return
        if self.dl_thread and self.dl_thread.is_alive():
            self.notify("A download is already running", severity="warning")
            self.query_one(TabbedContent).active = "tab-downloads"
            return

        sel = self.query_one("#chapter-list", SelectionList)
        indices = sorted(sel.selected)
        if not indices:
            self.notify("No chapters selected", severity="warning")
            return

        chapters = self.manga["chapters"]
        if len(indices) == len(chapters):
            selection = "all"
        else:
            nums = sorted(chapter_number(chapters[i]["name"]) for i in indices)
            selection = ",".join(
                str(int(n)) if n == int(n) else str(n) for n in nums)

        bundle_mode = self.query_one("#bundle-select", Select).value
        if bundle_mode == "1":
            bundle = 1
        elif bundle_mode == "n":
            try:
                bundle = max(2, int(self.query_one("#bundle-n", Input).value or 10))
            except ValueError:
                bundle = 10
        else:
            bundle = 0

        fmt = self.query_one("#fmt-select", Select).value
        settings = self.settings
        options = DownloadOptions(
            url=self.manga["info"]["url"],
            selection=selection,
            output_dir=self.query_one("#output-dir", Input).value.strip()
                        or settings["output_dir"],
            format=fmt,
            bundle=bundle,
            chapter_workers=settings["chapter_workers"],
            image_workers=settings["image_workers"],
            delay=settings["delay"],
            keep_images=settings.get("keep_images", False) or fmt == "images",
            source=(self.source.id if self.source else ""),
            language=settings.get("language", "en"),
        )

        # reset downloads tab
        self.total = len(indices)
        self.active_rows.clear()
        self.query_one("#dl-empty").add_class("hidden")
        self.query_one("#dl-body").remove_class("hidden")
        self.query_one("#dl-title", Static).update(self.manga["info"]["title"])
        self._set_status("Starting...")
        bar = self.query_one("#overall-bar", ProgressBar)
        bar.update(total=self.total, progress=0)
        self.query_one("#overall-text", Static).update(f"0 / {self.total}")
        box = self.query_one("#active-box", Vertical)
        box.remove_children()
        log = self.query_one("#dl-log", RichLog)
        log.clear()
        stop = self.query_one("#stop-btn", Button)
        stop.disabled = False
        self.query_one(TabbedContent).active = "tab-downloads"

        self.engine = DownloadEngine(options, on_event=self._on_engine_event)

        def runner():
            try:
                result = self.engine.run()
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            self.call_from_thread(self._download_finished, result)

        self.dl_thread = threading.Thread(target=runner, daemon=True)
        self.dl_thread.start()

    def _set_status(self, text):
        self.query_one("#dl-status", Static).update(f"[dim]{text}[/]")

    def _log(self, markup):
        self.query_one("#dl-log", RichLog).write(markup)

    # engine thread -> UI thread
    def _on_engine_event(self, event):
        self.call_from_thread(self._apply_event, event)

    def _apply_event(self, event):
        t = event["type"]
        if t == "status":
            self._set_status(event["message"])
        elif t == "plan":
            self.total = event["total"]
            self.query_one("#overall-bar", ProgressBar).update(
                total=self.total, progress=0)
            self.query_one("#overall-text", Static).update(f"0 / {self.total}")
            self._set_status(f"Downloading {self.total} chapters")
            self._log(f"[dim]Saving to {event['directory']}[/]")
        elif t == "chapter_start":
            self._ensure_row(event["chapter"])
        elif t == "chapter_progress":
            row = self._ensure_row(event["chapter"])
            row["bar"].update(total=event["total"], progress=event["done"])
            row["count"].update(f"{event['done']}/{event['total']}")
        elif t == "chapter_done":
            self._remove_row(event["chapter"])
            self.query_one("#overall-bar", ProgressBar).update(
                progress=event["completed"])
            self.query_one("#overall-text", Static).update(
                f"{event['completed']} / {event['total']}")
            self._log(f"[green]done[/]    {event['chapter']} "
                      f"[dim]({event['pages']} pages)[/]")
        elif t == "chapter_failed":
            self._remove_row(event["chapter"])
            self._log(f"[red]failed[/]  {event['chapter']}")
        elif t == "packaging":
            self._set_status(f"Packaging {event['file']}")
            self._log(f"[dim]packing {event['file']}[/]")
        elif t == "packaged":
            self._log(f"[green]created[/] {os.path.basename(event['file'])}")
        elif t == "error":
            self._log(f"[red]error[/]   {event['message']}")
        elif t == "stopped":
            self._log("[yellow]Stopped by user[/]")

    def _ensure_row(self, chapter):
        if chapter in self.active_rows:
            return self.active_rows[chapter]
        box = self.query_one("#active-box", Vertical)
        name = Static(chapter, classes="ac-name")
        bar = ProgressBar(classes="ac-bar", show_eta=False, show_percentage=True)
        count = Static("-", classes="ac-count")
        row = Horizontal(name, bar, count, classes="ac-row")
        box.mount(row)
        entry = {"row": row, "bar": bar, "count": count}
        self.active_rows[chapter] = entry
        return entry

    def _remove_row(self, chapter):
        entry = self.active_rows.pop(chapter, None)
        if entry:
            entry["row"].remove()

    def _download_finished(self, result):
        self.query_one("#stop-btn", Button).disabled = True
        for chapter in list(self.active_rows):
            self._remove_row(chapter)
        if result.get("ok"):
            self._set_status(
                f"Complete - {result.get('downloaded', 0)} chapters downloaded")
            self.query_one("#overall-bar", ProgressBar).update(progress=self.total)
            for out in result.get("outputs", []):
                self._log(f"[bold green]->[/] {out}")
            if result.get("failed"):
                self._log(f"[red]{len(result['failed'])} chapters failed:[/] "
                          + ", ".join(result["failed"][:8]))
            self.notify("Download complete")
        elif result.get("stopped"):
            self._set_status("Stopped")
        else:
            self._set_status(f"Failed: {result.get('error', 'unknown error')}")
            self.notify("Download failed", severity="error")

    @on(Button.Pressed, "#stop-btn")
    def handle_stop(self, _e):
        self.action_stop_download()

    # ---------------------------------------------------------- settings

    @on(Button.Pressed, "#save-btn")
    def handle_save(self, _e):
        def num(widget_id, cast, lo, hi, fallback):
            try:
                return min(hi, max(lo, cast(self.query_one(widget_id, Input).value)))
            except (ValueError, TypeError):
                return fallback

        self.settings.update({
            "output_dir": self.query_one("#set-output", Input).value.strip()
                          or self.settings["output_dir"],
            "format": self.query_one("#set-format", Select).value,
            "chapter_workers": num("#set-chapter-workers", int, 1, 8, 3),
            "image_workers": num("#set-image-workers", int, 1, 10, 6),
            "delay": num("#set-delay", float, 0.0, 10.0, 0.5),
            "keep_images": self.query_one("#set-keep", Switch).value,
        })
        save_settings(self.settings)
        # reflect into manga tab
        self.query_one("#output-dir", Input).value = self.settings["output_dir"]
        try:
            self.query_one("#fmt-select", Select).value = self.settings["format"]
        except Exception:
            pass
        self.query_one("#save-flash", Static).update("[green]Saved[/]")
        self.set_timer(2.0, lambda: self.query_one("#save-flash", Static).update(""))
        self.notify("Settings saved")


# Backwards-compatibility alias
MangasurfTUI = MangasurfTUI


def run_tui():
    from .logs import setup_logging
    setup_logging()
    if not TEXTUAL_AVAILABLE:
        print("The full-screen TUI needs Textual, which is not installed.\n"
              "    pip install textual          (or: pip install mangasurf[tui])\n"
              "\nThe interactive menu needs nothing extra:\n"
              "    mangasurf menu")
        return 1
    MangasurfTUI().run()
    return 0


if __name__ == "__main__":
    run_tui()
