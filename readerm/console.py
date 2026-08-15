"""Terminal styling for the CLI, with a working fallback when Rich is absent.

Why this module exists
----------------------
``cli.py`` imported Rich at module scope::

    from rich import box
    from rich.console import Console

If Rich is not installed that is an immediate ``ImportError`` and **nothing**
runs -- not ``--help``, not ``sources``, not a download. Reproduced by hiding
the module from the import system: ``import readerm.cli`` exits 1 with
``ImportError: No module named 'rich'`` before a single line of the program
executes.

That matters because this project is routinely run straight from a clone
(``py cli.py``), where nothing has installed the dependencies from
``pyproject.toml``. ``tui.py`` already guards its optional import of Textual
and prints an instruction instead of a traceback; the CLI did not.

So Rich is now optional here too. When it is installed everything behaves as
before. When it is not, the shims below reimplement the small slice the CLI
actually uses -- markup-stripped printing, tables, panels and a progress
display -- with ANSI escapes and plain text.

Colour
------
``NO_COLOR`` (any value) disables colour, ``FORCE_COLOR``/``CLICOLOR_FORCE``
enables it even when piped, matching the de-facto conventions Rich follows.
On Windows, ANSI is enabled through the console API when possible; Windows 10
1511+ supports it, and older hosts fall back to no colour rather than printing
raw escape codes.
"""

import os
import re
import shutil
import sys
import time

__all__ = [
    "RICH", "console", "Table", "Panel", "box", "Progress", "colour_enabled",
    "style", "strip_markup", "ACCENT", "DIM", "OK", "WARN", "ERR", "HEAD",
]

#: Semantic styles, used everywhere instead of raw colour names so the palette
#: can be changed in one place.
ACCENT = "bright_cyan"
DIM = "grey58"
OK = "bright_green"
WARN = "yellow"
ERR = "bright_red"
HEAD = "bold bright_white"


def _want_colour(stream=None):
    """Whether to emit ANSI colour, honouring the usual environment flags."""
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") or os.environ.get("CLICOLOR_FORCE"):
        return True
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
    except Exception:
        return False
    if os.name == "nt":
        return _enable_windows_ansi()
    return True


def _enable_windows_ansi():
    """Turn on ANSI processing for the Windows console.

    Windows 10 1511+ understands escape codes but only once
    ENABLE_VIRTUAL_TERMINAL_PROCESSING is set. Without this the fallback would
    print literal ``[36m`` noise, which is worse than no colour at all.
    """
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):        # stdout, stderr
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False


try:                                        # pragma: no cover - import dependent
    from rich import box                    # noqa: F401
    from rich.console import Console
    from rich.panel import Panel            # noqa: F401
    from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                               SpinnerColumn, TextColumn, TimeElapsedColumn,
                               TimeRemainingColumn)
    from rich.table import Table            # noqa: F401

    RICH = True
    console = Console(highlight=False, soft_wrap=False)

    def colour_enabled():
        return console.color_system is not None

    def download_progress(console_=None):
        """The progress display used while downloading.

        Adds a download-rate style ETA column: with 800-chapter series the
        elapsed time alone gives no sense of how long is left.
        """
        return Progress(
            SpinnerColumn(style=ACCENT),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=28, complete_style=ACCENT,
                      finished_style=OK),
            MofNCompleteColumn(),
            TextColumn("[" + DIM + "]{task.percentage:>3.0f}%[/]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(compact=True),
            console=console_ or console,
            transient=False,
        )

except ImportError:                         # pragma: no cover - install dependent
    RICH = False

    _ANSI = {
        "bold": "1", "dim": "2", "italic": "3", "underline": "4",
        "red": "31", "green": "32", "yellow": "33", "blue": "34",
        "magenta": "35", "cyan": "36", "white": "37",
        "bright_red": "91", "bright_green": "92", "bright_yellow": "93",
        "bright_blue": "94", "bright_magenta": "95", "bright_cyan": "96",
        "bright_white": "97", "grey58": "90", "grey": "90",
    }

    _TAG = re.compile(r"\[(/?)([a-z0-9_#\. ]*)\]", re.I)

    def strip_markup(text):
        """Remove Rich-style ``[bold]`` tags from a string."""
        return _TAG.sub("", str(text))

    def style(text, spec):
        """Wrap text in ANSI codes for a Rich-style style string."""
        if not spec or not colour_enabled():
            return str(text)
        codes = [_ANSI[p] for p in str(spec).split() if p in _ANSI]
        if not codes:
            return str(text)
        return "\x1b[" + ";".join(codes) + "m" + str(text) + "\x1b[0m"

    _COLOUR = None

    def colour_enabled():
        global _COLOUR
        if _COLOUR is None:
            _COLOUR = _want_colour()
        return _COLOUR

    def _render(text):
        """Translate the Rich markup the CLI uses into ANSI, or strip it."""
        text = str(text)
        if not colour_enabled():
            return strip_markup(text)

        out, stack, pos = [], [], 0
        for match in _TAG.finditer(text):
            out.append(text[pos:match.start()])
            closing, spec = match.group(1), match.group(2).strip()
            if closing:
                if stack:
                    stack.pop()
                out.append("\x1b[0m")
                if stack:                   # restore the enclosing style
                    out.append(_codes(stack[-1]))
            else:
                stack.append(spec)
                out.append(_codes(spec))
            pos = match.end()
        out.append(text[pos:])
        if stack:
            out.append("\x1b[0m")
        return "".join(out)

    def _codes(spec):
        codes = [_ANSI[p] for p in str(spec).split() if p in _ANSI]
        return "\x1b[" + ";".join(codes) + "m" if codes else ""

    class box:                              # noqa: N801 - mirrors rich.box
        SIMPLE_HEAD = "SIMPLE_HEAD"
        ROUNDED = "ROUNDED"
        MINIMAL = "MINIMAL"
        SIMPLE = "SIMPLE"

    class Console:
        """The handful of Console methods the CLI actually calls."""

        def __init__(self, **_kwargs):
            self.file = sys.stdout

        @property
        def width(self):
            return shutil.get_terminal_size((100, 24)).columns

        @property
        def is_terminal(self):
            try:
                return sys.stdout.isatty()
            except Exception:
                return False

        def print(self, *objects, **kwargs):
            if not objects:
                print()
                return
            end = kwargs.pop("end", "\n")
            parts = []
            for obj in objects:
                if isinstance(obj, (Table, Panel)):
                    parts.append(obj.render(self.width))
                else:
                    parts.append(_render(obj))
            print(" ".join(parts), end=end)

        def rule(self, title=""):
            width = max(8, self.width)
            label = strip_markup(title)
            if label:
                bar = "-" * max(0, width - len(label) - 3)
                print(_render(f"[{DIM}]--[/] ") + _render(title) + " " +
                      _render(f"[{DIM}]{bar}[/]"))
            else:
                print(_render(f"[{DIM}]{'-' * width}[/]"))

        def input(self, prompt=""):
            return input(strip_markup(prompt))

        def status(self, *_a, **_k):
            return _NullContext()

    class _NullContext:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def update(self, *_a, **_k):
            pass

    class Table:
        """Minimal column-aligned table."""

        def __init__(self, box=None, header_style=None, title=None,
                     show_header=True, **_kwargs):
            self.columns = []
            self.rows = []
            self.header_style = header_style
            self.title = title
            self.show_header = show_header
            self._grid = False

        @classmethod
        def grid(cls, padding=None, **kwargs):
            """Headerless layout table, as used for the download summary."""
            table = cls(show_header=False, **kwargs)
            table._grid = True
            return table

        def add_column(self, header="", style=None, justify="left",
                       overflow=None, **_kwargs):
            self.columns.append({"header": header, "style": style,
                                 "justify": justify})

        def add_row(self, *cells, **_kwargs):
            # Table.grid() callers often add rows without declaring columns.
            while len(self.columns) < len(cells):
                self.add_column("")
            self.rows.append([("" if c is None else str(c)) for c in cells])

        def render(self, width=100):
            if not self.columns:
                return ""
            plain = [[strip_markup(c) for c in row] for row in self.rows]
            widths = []
            for index, column in enumerate(self.columns):
                longest = max([len(strip_markup(column["header"]))] +
                              [len(r[index]) for r in plain
                               if index < len(r)] or [0])
                widths.append(longest)

            # Shrink the widest column if the table would wrap.
            budget = width - (2 * len(widths))
            while sum(widths) > budget and max(widths) > 8:
                widths[widths.index(max(widths))] -= 1

            lines = []
            if self.title:
                lines.append(_render(f"[{HEAD}]{self.title}[/]"))
            if self.show_header:
                cells = []
                for column, size in zip(self.columns, widths):
                    text = strip_markup(column["header"])[:size]
                    text = (text.rjust(size) if column["justify"] == "right"
                            else text.ljust(size))
                    cells.append(_render(f"[{self.header_style or HEAD}]"
                                         f"{text}[/]"))
                lines.append("  ".join(cells))
                lines.append(_render(f"[{DIM}]" +
                                     "  ".join("-" * s for s in widths) +
                                     "[/]"))
            for row in plain:
                cells = []
                for index, (column, size) in enumerate(zip(self.columns,
                                                           widths)):
                    text = (row[index] if index < len(row) else "")[:size]
                    text = (text.rjust(size) if column["justify"] == "right"
                            else text.ljust(size))
                    cells.append(_render(f"[{column['style']}]{text}[/]")
                                 if column["style"] else text)
                lines.append("  ".join(cells))
            return "\n".join(lines)

    class Panel:
        def __init__(self, renderable, title=None, border_style=None,
                     box=None, **_kwargs):
            self.renderable = renderable
            self.title = title

        @classmethod
        def fit(cls, renderable, **kwargs):
            return cls(renderable, **kwargs)

        def render(self, width=100):
            body = self.renderable
            if isinstance(body, (Table, Panel)):
                body = body.render(width - 4)
            body = _render(body)
            lines = str(body).split("\n")
            inner = max([len(strip_markup(_ANSI_RE.sub("", line)))
                         for line in lines] or [0])
            inner = max(inner, len(strip_markup(self.title or "")) + 2)
            inner = min(inner, max(10, width - 4))
            top = ("+- " + strip_markup(self.title) + " "
                   ).ljust(inner + 3, "-") + "+" if self.title \
                else "+" + "-" * (inner + 2) + "+"
            out = [_render(f"[{DIM}]{top}[/]")]
            for line in lines:
                pad = inner - len(_ANSI_RE.sub("", line))
                out.append(_render(f"[{DIM}]|[/] ") + line + " " * max(0, pad)
                           + _render(f" [{DIM}]|[/]"))
            out.append(_render(f"[{DIM}]+{'-' * (inner + 2)}+[/]"))
            return "\n".join(out)

    class Progress:
        """Single-line progress bar with the same API surface the CLI uses."""

        def __init__(self, *_columns, console=None, **_kwargs):
            self.console = console or Console()
            self._tasks = {}
            self._next = 0
            self._active = False
            self._last = 0.0

        # -- context manager -------------------------------------------
        def __enter__(self):
            self._active = True
            return self

        def __exit__(self, *_exc):
            self._active = False
            self._flush(force=True)
            if self._bar_shown():
                sys.stdout.write("\n")
                sys.stdout.flush()
            return False

        # -- task api --------------------------------------------------
        def add_task(self, description, total=None, **_kwargs):
            task_id = self._next
            self._next += 1
            self._tasks[task_id] = {"description": strip_markup(description),
                                    "total": total, "completed": 0}
            self._flush()
            return task_id

        def update(self, task_id, total=None, completed=None,
                   advance=None, description=None, **_kwargs):
            task = self._tasks.get(task_id)
            if task is None:
                return
            if total is not None:
                task["total"] = total
            if completed is not None:
                task["completed"] = completed
            if advance:
                task["completed"] += advance
            if description is not None:
                task["description"] = strip_markup(description)
            self._flush()

        def advance(self, task_id, amount=1):
            self.update(task_id, advance=amount)

        def remove_task(self, task_id):
            self._tasks.pop(task_id, None)
            self._flush()

        # -- rendering -------------------------------------------------
        def _bar_shown(self):
            return self.console.is_terminal and colour_enabled() is not None

        def _flush(self, force=False):
            if not self._active or not self._tasks:
                return
            if not self.console.is_terminal:
                return                      # piped: only discrete lines
            now = time.time()
            if not force and now - self._last < 0.08:
                return                      # throttle repaints
            self._last = now

            task = self._tasks[min(self._tasks)]     # the overall task
            total, done = task["total"] or 0, task["completed"]
            fraction = (done / total) if total else 0.0
            filled = int(28 * fraction)
            bar = "#" * filled + "." * (28 - filled)
            text = (f"{task['description'][:28]:28} [{bar}] "
                    f"{done}/{total or '?'} {fraction * 100:3.0f}%")
            width = max(20, self.console.width - 1)
            sys.stdout.write("\r" + text[:width].ljust(width))
            sys.stdout.flush()

    _ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

    console = Console()

    def download_progress(console_=None):
        return Progress(console=console_ or console)


if RICH:                                    # pragma: no cover - import dependent
    _MARKUP = re.compile(r"\[(/?)([a-z0-9_#\. ]*)\]", re.I)

    def strip_markup(text):
        return _MARKUP.sub("", str(text))

    def style(text, spec):
        return f"[{spec}]{text}[/]" if spec else str(text)
