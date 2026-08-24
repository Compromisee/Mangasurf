#!/usr/bin/env python3
"""One window to launch any Mangasurf interface.

    python landing.py

Five ways in, one place to pick from: the desktop app, the terminal menu,
the full-screen TUI, the CLI, and the phone server. Terminal-based ones open
in a real terminal window; the graphical ones are spawned directly.

The venv problem
----------------
Double-clicking ``tui.py`` in a file manager, or opening a terminal from a
launcher, does not inherit the project's virtual environment — so the child
process gets the *system* Python, which has none of Mangasurf's dependencies
and dies with ImportError. That is confusing in a way that looks like a bug
in the app.

:func:`find_python` therefore searches, in order:

1. the interpreter running this file, if it is already in a venv —
   ``python landing.py`` from an activated venv is the common case;
2. ``$VIRTUAL_ENV``, if one is active but somehow not ours;
3. ``.venv`` / ``venv`` / ``env`` in the project folder, then in its parent,
   then its grandparent — "two layers above" covers the usual
   ``projects/mangasurf-checkout/Mangasurf`` nesting;
4. the current interpreter, as a last resort.

Whatever it picks is shown in the window, because "which Python is this
actually using" is the first question when something fails to start.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
import time

# Allow running this file directly (python mangasurf/landing.py, or an
# IDE's "Run file"). Without this the relative imports below have no
# parent package and raise ImportError before anything else happens.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    import mangasurf  # noqa: F401
    __package__ = "mangasurf"

#: True when running from a PyInstaller build. A frozen app has no .py
#: files to hand to an interpreter, so every target is re-launched as the
#: executable itself with a subcommand instead.
FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    #: The folder holding Mangasurf.exe -- what the user thinks of as "the
    #: app", and where a venv search would be pointless.
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    #: This module lives in the package, so the project root -- the folder
    #: holding gui.py, tui.py and a possible .venv -- is one level up.
    HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("mangasurf.landing")

#: Where to look for a virtual environment, relative to the project folder.
#: Two levels up, as requested -- a checkout is often one folder inside a
#: workspace that owns the venv.
VENV_SEARCH_DEPTH = 2
VENV_NAMES = (".venv", "venv", "env", ".env")


def _venv_python(root):
    """The interpreter inside a venv directory, or None."""
    for name in VENV_NAMES:
        base = os.path.join(root, name)
        for rel in (os.path.join("Scripts", "python.exe"),   # Windows
                    os.path.join("bin", "python3"),
                    os.path.join("bin", "python")):
            candidate = os.path.join(base, rel)
            if os.path.isfile(candidate):
                return candidate
    return None


def find_python():
    """Return ``(path, description)`` for the interpreter to launch with."""
    if FROZEN:
        # There is no interpreter to find: the executable is its own.
        return sys.executable, "packaged build"
    if sys.prefix != sys.base_prefix:
        return sys.executable, "this venv"

    active = os.environ.get("VIRTUAL_ENV")
    if active:
        found = _venv_python(os.path.dirname(active)) or _venv_python(active)
        if found:
            return found, "$VIRTUAL_ENV"

    root = HERE
    for depth in range(VENV_SEARCH_DEPTH + 1):
        found = _venv_python(root)
        if found:
            where = "project folder" if depth == 0 else f"{depth} level(s) up"
            return found, where
        parent = os.path.dirname(root)
        if parent == root:
            break
        root = parent

    return sys.executable, "system Python (no venv found)"


def terminal_command(python, script_args, title):
    """Build a command that runs ``script_args`` in a visible terminal.

    A TUI written to a pipe is useless, so these genuinely need a terminal
    window rather than ``subprocess.Popen`` with captured output.
    """
    inner = [python] + script_args
    system = platform.system()

    if system == "Windows":
        # `start` needs a title argument first, or it treats a quoted path
        # as the title and opens an empty prompt.
        quoted = " ".join(f'"{part}"' for part in inner)
        return ["cmd", "/c", "start", title, "cmd", "/k", quoted], True

    if system == "Darwin":
        script = " ".join(shlex.quote(part) for part in inner)
        osa = (f'tell application "Terminal" to do script '
               f'"cd {shlex.quote(HERE)} && {script}"')
        return ["osascript", "-e", osa], False

    # Linux/BSD: try the emulators most likely to be installed. Each wants a
    # slightly different way of being handed a command.
    joined = " ".join(shlex.quote(part) for part in inner)
    held = f"{joined}; echo; read -p 'Press Enter to close…'"
    for emulator, args in (
        ("x-terminal-emulator", ["-e", "bash", "-lc", held]),
        ("gnome-terminal", ["--", "bash", "-lc", held]),
        ("konsole", ["-e", "bash", "-lc", held]),
        ("xfce4-terminal", ["-e", f"bash -lc {shlex.quote(held)}"]),
        ("alacritty", ["-e", "bash", "-lc", held]),
        ("kitty", ["bash", "-lc", held]),
        ("xterm", ["-e", "bash", "-lc", held]),
    ):
        if shutil.which(emulator):
            return [emulator] + args, False
    return None, False


class Launcher:
    """Starts interfaces and records what happened. The window's JS API."""

    #: id -> (label, script args, needs a terminal, blurb)
    #:
    #: ``script args`` are for a source checkout, where an interpreter is
    #: handed a .py file. A frozen build has no .py files at all, so
    #: :attr:`FROZEN_ARGS` re-invokes the executable with a subcommand
    #: instead -- without that, every tile in the packaged exe failed with
    #: "can't open file 'gui.py'".
    TARGETS = {
        "gui": ("Desktop app", ["gui.py"], False,
                "The full interface: cover grid, queue, stats, tools."),
        "menu": ("Terminal menu", ["-m", "mangasurf.cli", "menu"], True,
                 "Numbered prompts. No extra dependencies needed."),
        "tui": ("Full-screen TUI", ["tui.py"], True,
                "Keyboard-driven, works over SSH. Needs the tui extra."),
        "cli": ("Command line", ["-m", "mangasurf.cli", "--help"], True,
                "Opens a shell with the CLI help, ready to type into."),
        "server": ("Phone server", ["server.py", "--gui"], False,
                   "Serve this interface to your phone over Wi-Fi."),
        "opds": ("OPDS catalog", ["opdsserve.py", "--gui"], False,
                 "Read your library in Readest, Panels or any OPDS app."),
    }

    #: id -> arguments passed to the executable itself when frozen.
    FROZEN_ARGS = {
        "gui": ["gui"],
        "menu": ["menu"],
        "tui": ["tui"],
        "cli": ["--help"],
        "server": ["server", "--gui"],
        "opds": ["opds", "--gui"],
    }

    def __init__(self):
        self.python, self.python_where = find_python()
        self._log = []
        self._seq = 0
        self._lock = threading.Lock()
        self._children = {}

        if FROZEN:
            self.add("info", f"Packaged build: {sys.executable}")
        else:
            self.add("info", f"Project folder: {HERE}")
            self.add("info", f"Python: {self.python}  ({self.python_where})")
        if not FROZEN and self.python_where.startswith("system"):
            self.add("warn", "No virtual environment found. If a launch fails "
                             "with ImportError, activate your venv and run "
                             "landing.py from there.")

    # --------------------------------------------------------------- log

    def add(self, level, message):
        with self._lock:
            self._seq += 1
            self._log.append({"seq": self._seq,
                              "time": time.strftime("%H:%M:%S"),
                              "level": level, "text": str(message)})
            if len(self._log) > 500:
                del self._log[:len(self._log) - 500]

    def get_log(self, since=0):
        try:
            since = int(since)
        except (TypeError, ValueError):
            since = 0
        with self._lock:
            lines = [l for l in self._log if l["seq"] > since]
            cursor = self._seq
        return {"ok": True, "cursor": cursor, "lines": lines,
                "running": self.running()}

    def clear_log(self):
        with self._lock:
            self._log = []
        self.add("info", "Log cleared.")
        return {"ok": True}

    # ------------------------------------------------------------ state

    def running(self):
        """Which targets still have a live child process."""
        alive = {}
        for key, proc in list(self._children.items()):
            if proc.poll() is None:
                alive[key] = True
            else:
                self._children.pop(key, None)
                self.add("info", f"{self.TARGETS[key][0]} exited "
                                 f"(code {proc.returncode}).")
        return alive

    def get_state(self):
        return {
            "ok": True,
            "python": self.python,
            "python_where": self.python_where,
            "folder": HERE,
            "running": self.running(),
            "targets": [
                {"id": key, "label": label, "terminal": term, "blurb": blurb}
                for key, (label, _args, term, blurb) in self.TARGETS.items()
            ],
        }

    # ----------------------------------------------------------- launch

    def launch(self, target):
        entry = self.TARGETS.get(target)
        if entry is None:
            return {"ok": False, "error": f"Unknown target '{target}'"}
        label, script_args, needs_terminal, _blurb = entry

        existing = self._children.get(target)
        if existing is not None and existing.poll() is None:
            self.add("warn", f"{label} is already running.")
            return {"ok": False, "error": f"{label} is already running",
                    "state": self.get_state()}

        if FROZEN:
            # No .py files exist in a bundle. Re-run the executable with a
            # subcommand; launcher.py routes it to the right interface.
            launch_with = sys.executable
            script_args = list(self.FROZEN_ARGS.get(target, []))
        else:
            launch_with = self.python
            # A missing script is a clearer message than whatever Python
            # would say about it three frames deep.
            if script_args and script_args[0].endswith(".py"):
                path = os.path.join(HERE, script_args[0])
                if not os.path.isfile(path):
                    self.add("error",
                             f"{script_args[0]} is missing from {HERE}")
                    return {"ok": False, "error": f"{script_args[0]} not found"}
                script_args = [path] + script_args[1:]

        if needs_terminal:
            command, shell_hint = terminal_command(launch_with, script_args,
                                                   f"Mangasurf {label}")
            if command is None:
                message = ("No terminal emulator found. Install one, or run "
                           "this by hand:\n    "
                           + " ".join([self.python] + script_args))
                self.add("error", message)
                return {"ok": False, "error": message}
        else:
            command, shell_hint = [launch_with] + script_args, False

        self.add("info", f"Starting {label}…")
        self.add("cmd", " ".join(command))
        try:
            proc = subprocess.Popen(
                command, cwd=HERE,
                # Terminal launchers exit immediately after spawning the
                # window, so their output is noise; graphical children are
                # detached the same way for consistency.
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=(os.name != "nt"))
        except Exception as exc:
            self.add("error", f"Could not start {label}: {exc}")
            return {"ok": False, "error": str(exc)}

        if not shell_hint and not needs_terminal:
            self._children[target] = proc

        # Give an instant failure a moment to surface, so the window can say
        # so rather than showing a launch that already died.
        time.sleep(0.6)
        if proc.poll() is not None and proc.returncode != 0 and not needs_terminal:
            self.add("error", f"{label} exited immediately "
                              f"(code {proc.returncode}). Check the venv.")
            return {"ok": False,
                    "error": f"{label} exited immediately", "state": self.get_state()}

        self.add("info", f"{label} started.")
        return {"ok": True, "state": self.get_state()}

    def open_folder(self):
        try:
            if platform.system() == "Windows":
                os.startfile(HERE)  # noqa: S606
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", HERE])
            else:
                subprocess.Popen(["xdg-open", HERE])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def run_landing():
    try:
        import webview
    except ImportError:
        print("The launcher window needs pywebview:\n\n"
              "    pip install pywebview\n\n"
              "Or start an interface directly:\n"
              "    python gui.py        python tui.py\n"
              "    python server.py     python -m mangasurf.cli menu")
        return 1

    # pywebview logs a full ImportError traceback for every backend it
    # tries, so on a machine with no GTK/Qt the useful message is buried
    # under two screens of noise. We report the failure ourselves below.
    logging.getLogger("pywebview").setLevel(logging.CRITICAL)

    launcher = Launcher()
    webview.create_window("Mangasurf", html=PAGE, js_api=launcher,
                          width=780, height=720, min_size=(600, 560),
                          background_color="#0b0a12")
    try:
        webview.start()
    except Exception as exc:
        # No display, or no GTK/Qt bindings. pywebview prints a wall of
        # import tracebacks on its way here, so end with something a person
        # can act on rather than leaving that as the last word -- and exit
        # non-zero, because nothing was launched.
        logger.debug("landing window failed", exc_info=True)
        print("\n" + "-" * 58)
        print("  The launcher window could not open.")
        print(f"  {exc}")
        print("-" * 58)
        print("  Start an interface directly instead:")
        for command in _direct_commands():
            print(f"    {command}")
        print("-" * 58 + "\n")
        return 1
    return 0


def _direct_commands():
    """How to reach each interface without the window.

    A frozen build has no .py files, so the advice has to differ -- telling
    someone to run `python gui.py` next to an exe is useless.
    """
    if FROZEN:
        name = os.path.basename(sys.executable)
        return [f"{name} gui", f"{name} menu", f"{name} tui",
                f"{name} server", f"{name} opds", f"{name} --help"]
    return ["python gui.py", "python -m mangasurf.cli menu",
            "python tui.py", "python server.py", "python opdsserve.py",
            "python -m mangasurf.cli --help"]


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Mangasurf — Desktop Manga Reader &amp; Downloader</title>
<link rel="icon" type="image/svg+xml" href="docs/icon.svg">
<link rel="alternate icon" href="docs/icon.ico">
<link rel="apple-touch-icon" href="docs/icon.png">
<style>
:root{
  --bg:#0b0a12; --panel:#16151f; --panel-2:#1c1b28; --line:#26243a;
  --ink:#f2f0ff; --ink-2:#a8a3c4; --ink-3:#6f6a90;
  --a:#ff5f8f; --b:#7c6bff; --c:#3ddad7; --d:#ffb648; --err:#ff6b6b;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg);color:var(--ink);padding:20px;
  font:14px/1.55 'Segoe UI',system-ui,-apple-system,sans-serif;
  display:flex;flex-direction:column;gap:14px;height:100vh;
}
header{display:flex;align-items:center;gap:11px}
.mark{width:34px;height:34px;border-radius:10px;flex:none;
      background:linear-gradient(135deg,var(--a),var(--b));
      display:grid;place-items:center;font-weight:800;color:#fff}
h1{font-size:18px;font-weight:750;letter-spacing:-.3px}
header .sub{font-size:11.5px;color:var(--ink-3)}
.env{
  background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:9px 12px;font:11.5px/1.5 'Consolas',monospace;color:var(--ink-3);
  display:flex;gap:8px;align-items:center;
}
.env b{color:var(--c);font-weight:600}
.env.warn{border-color:rgba(255,182,72,.35);background:rgba(255,182,72,.07)}
.env.warn b{color:var(--d)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.tile{
  background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:14px;text-align:left;cursor:pointer;color:inherit;font:inherit;
  transition:border-color .15s,transform .12s;position:relative;
}
.tile:hover{border-color:var(--b);transform:translateY(-2px)}
.tile:active{transform:none}
.tile:disabled{opacity:.55;cursor:default;transform:none}
.tile h3{font-size:14.5px;font-weight:700;margin-bottom:3px;
         display:flex;align-items:center;gap:7px}
.tile p{font-size:12px;color:var(--ink-3);line-height:1.45}
.tag{font-size:9.5px;font-weight:700;letter-spacing:.05em;padding:2px 6px;
     border-radius:5px;background:var(--panel-2);color:var(--ink-3);
     text-transform:uppercase}
.live{width:8px;height:8px;border-radius:50%;background:var(--c);
      box-shadow:0 0 0 3px rgba(61,218,215,.18)}
.logwrap{flex:1;display:flex;flex-direction:column;min-height:0}
.loghead{display:flex;align-items:center;gap:9px;cursor:pointer;
         user-select:none;padding:2px 0}
.loghead h2{font-size:11.5px;font-weight:700;letter-spacing:.08em;
            text-transform:uppercase;color:var(--ink-3);flex:1}
.chev{color:var(--ink-3);transition:transform .18s;font-size:12px}
.loghead.open .chev{transform:rotate(90deg)}
#log{
  flex:1;overflow-y:auto;background:#0e0d17;border:1px solid var(--line);
  border-radius:10px;padding:10px 12px;margin-top:8px;
  font:11.5px/1.65 'Consolas',monospace;min-height:100px;display:none;
}
#log.open{display:block}
.line{display:flex;gap:8px}
.line .t{color:#4f4a70;flex:none}
.line.info .m{color:var(--ink-2)}
.line.cmd  .m{color:var(--b)}
.line.warn .m{color:var(--d)}
.line.error .m{color:var(--err);white-space:pre-wrap}
button.mini{background:var(--panel-2);color:var(--ink-2);
            border:1px solid var(--line);border-radius:7px;
            padding:4px 10px;font-size:11.5px;cursor:pointer}
button.mini:hover{border-color:var(--b);color:var(--ink)}
</style>
</head>
<body>

<header>
  <div class="mark" style="background:none;padding:0"><img src="docs/icon.svg" style="width:34px;height:34px;border-radius:8px" alt="Mangasurf" onerror="this.outerHTML='M'"></div>
  <div>
    <h1>Mangasurf</h1>
    <div class="sub">High-Performance Manga Engine &amp; Reader</div>
  </div>
</header>

<div class="env" id="env">Checking environment…</div>

<div class="grid" id="grid"></div>

<div class="logwrap">
  <div class="loghead" id="loghead">
    <span class="chev">&#9654;</span>
    <h2>Log</h2>
    <button class="mini" id="clearBtn" style="display:none">Clear</button>
  </div>
  <div id="log"></div>
</div>

<script>
var api = null, cursor = 0, open_ = false;

function el(id){ return document.getElementById(id); }

function ready(fn){
  if (window.pywebview && window.pywebview.api) return fn();
  window.addEventListener('pywebviewready', fn, {once:true});
}

function paint(state){
  if (!state) return;
  var env = el('env');
  var warn = (state.python_where || '').indexOf('system') === 0;
  env.className = 'env' + (warn ? ' warn' : '');
  env.innerHTML = '';
  var b = document.createElement('b');
  b.textContent = warn ? 'No venv' : 'venv';
  var span = document.createElement('span');
  span.textContent = state.python + '  (' + state.python_where + ')';
  env.appendChild(b); env.appendChild(span);

  var grid = el('grid');
  grid.innerHTML = '';
  (state.targets || []).forEach(function(t){
    var live = state.running && state.running[t.id];
    var btn = document.createElement('button');
    btn.className = 'tile';
    btn.disabled = !!live;

    var h = document.createElement('h3');
    h.textContent = t.label;
    if (live) {
      var dot = document.createElement('span');
      dot.className = 'live';
      h.appendChild(dot);
    }
    var tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = t.terminal ? 'terminal' : 'window';
    h.appendChild(tag);

    var p = document.createElement('p');
    p.textContent = live ? 'Running.' : t.blurb;

    btn.appendChild(h); btn.appendChild(p);
    btn.addEventListener('click', function(){
      btn.disabled = true;
      /* Open the log on first launch: if something goes wrong this is
         where it will say so, and a collapsed panel would hide it. */
      if (!open_) toggleLog();
      api.launch(t.id).then(function(r){
        if (r && r.state) paint(r.state);
        else btn.disabled = false;
      });
    });
    grid.appendChild(btn);
  });
}

function toggleLog(){
  open_ = !open_;
  el('log').classList.toggle('open', open_);
  el('loghead').classList.toggle('open', open_);
  el('clearBtn').style.display = open_ ? '' : 'none';
}

function pump(){
  api.get_log(cursor).then(function(r){
    if (r && r.ok){
      cursor = r.cursor;
      var box = el('log');
      var stuck = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
      (r.lines || []).forEach(function(l){
        var d = document.createElement('div');
        d.className = 'line ' + l.level;
        d.innerHTML = '<span class="t"></span><span class="m"></span>';
        d.children[0].textContent = l.time;
        d.children[1].textContent = l.text;
        box.appendChild(d);
      });
      if (stuck) box.scrollTop = box.scrollHeight;
      while (box.children.length > 500) box.removeChild(box.firstChild);
    }
    setTimeout(pump, 900);
  }).catch(function(){ setTimeout(pump, 2500); });
}

ready(function(){
  api = window.pywebview.api;
  api.get_state().then(paint);
  pump();
  el('loghead').addEventListener('click', function(e){
    if (e.target.id === 'clearBtn') return;
    toggleLog();
  });
  el('clearBtn').addEventListener('click', function(){
    api.clear_log().then(function(){ el('log').innerHTML = ''; cursor = 0; });
  });
  /* Keep the running badges honest if something exits on its own. */
  setInterval(function(){ api.get_state().then(paint); }, 3000);
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(run_landing())
