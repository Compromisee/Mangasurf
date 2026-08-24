"""ReaderM 1.0.1 — the rebindable keymap.

The reader dispatched keys from a `switch (e.key)` with the bindings written
into the case labels, so the binding, the action and the help text lived in
three places that had to be edited together. They had already drifted: the
help sheet advertised keys the switch did not handle.

keys.js holds one ACTIONS list that feeds the defaults, the settings page, the
help sheet and the dispatcher.

Two bugs found while building it, both caught here:

* `normalise(' ')` returned `'+'`. Splitting on "+" and dropping empty parts
  destroyed the spacebar, so Space and the auto-scroll-faster key became the
  same binding and the default map shipped with a conflict.
* `pretty('b')` and `pretty('B')` both rendered "B", so bookmark and
  show-bookmarks showed an identical keycap and looked broken.
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "mangasurf", "reader", "app")


def node(script):
    """Run a snippet against the real keys.js, as a module."""
    if not shutil.which("node"):
        pytest.skip("node is not available")
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=APP, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


IMPORT = ("import { ACTIONS, PRESETS, PRESET_ORDER, normalise, pretty, "
          "defaults, resolve, conflicts, index, bindingFor } "
          "from './keys.js';\n")


@pytest.mark.parametrize("raw,expected", [
    (" ", " "),                 # the spacebar, not "+"
    ("Space", " "),
    ("+", "+"),
    ("-", "-"),
    ("_", "_"),
    ("ArrowLeft", "arrowleft"),
    ("arrowleft", "arrowleft"),
    ("?", "?"),
    ("b", "b"),
    ("B", "B"),                 # case is meaningful: b and B differ
    ("ctrl+=", "ctrl+="),
    ("shift+ctrl+k", "ctrl+shift+k"),   # modifier order is canonical
    ("ctrl+shift+k", "ctrl+shift+k"),
    ("", ""),
])
def test_bindings_normalise_to_one_spelling(raw, expected):
    got = node(IMPORT + f"console.log(JSON.stringify(normalise({json.dumps(raw)})))")
    assert got == expected


def test_the_spacebar_is_not_the_plus_key():
    """`filter(Boolean)` dropped the space, so " " normalised to "+" and
    silently merged Space with auto-scroll-faster."""
    got = node(IMPORT + "console.log(JSON.stringify("
                        "[normalise(' '), normalise('+')]))")
    assert got[0] != got[1], "Space and + collapsed to the same binding"


def test_the_default_map_has_no_conflicts():
    """A default layout that ships with two actions on one key is a bug the
    user sees the first time they open the settings page."""
    got = node(IMPORT + "console.log(JSON.stringify(conflicts(defaults())))")
    assert got == [], got


@pytest.mark.parametrize("preset", ["default", "vim", "wasd", "oneHand"])
def test_every_preset_is_usable(preset):
    """No conflicts, and nothing left unbound -- a preset only overrides part
    of the map, so a missing fallback would silently disable an action."""
    got = node(IMPORT + f"""
        const map = resolve(PRESETS[{json.dumps(preset)}].keys);
        console.log(JSON.stringify({{
            conflicts: conflicts(map),
            unbound: ACTIONS.filter(a => !(map[a.id] || []).length).map(a => a.id),
        }}));
    """)
    assert got["conflicts"] == [], got["conflicts"]
    assert got["unbound"] == [], got["unbound"]


@pytest.mark.parametrize("raw,expected", [
    ("b", "B"),
    ("B", "Shift + B"),         # or the two rows look identical
    (" ", "Space"),
    ("arrowleft", "←"),
    ("escape", "Esc"),
    ("ctrl+=", "Ctrl + ="),
    ("shift+arrowleft", "Shift + ←"),
    ("+", "+"),
])
def test_keycaps_read_the_way_they_are_pressed(raw, expected):
    got = node(IMPORT + f"console.log(JSON.stringify(pretty({json.dumps(raw)})))")
    assert got == expected


def test_lower_and_upper_case_letters_look_different():
    """Bookmark is `b` and show-bookmarks is `B`; both rendered "B" and the
    settings page looked like it had duplicated a row."""
    got = node(IMPORT + "console.log(JSON.stringify([pretty('b'), pretty('B')]))")
    assert got[0] != got[1]


def test_a_saved_map_only_records_what_changed():
    """So a later release can improve a default without every existing user
    being pinned to the old one."""
    got = node(IMPORT + """
        const base = defaults();
        const saved = { mode: ['q'] };
        const map = resolve(saved);
        console.log(JSON.stringify({
            changed: map.mode,
            untouched: map.fullscreen,
            same_as_default: JSON.stringify(map.fullscreen) === JSON.stringify(base.fullscreen),
        }));
    """)
    assert got["changed"] == ["q"]
    assert got["same_as_default"] is True


def test_an_action_dropped_in_a_later_version_is_ignored():
    got = node(IMPORT + """
        const map = resolve({ thisActionNoLongerExists: ['z'] });
        console.log(JSON.stringify(Object.keys(map).includes('thisActionNoLongerExists')));
    """)
    assert got is False


def test_an_action_added_later_still_gets_its_default():
    """A saved map from an older version must not leave a new action unbound."""
    got = node(IMPORT + """
        const map = resolve({ mode: ['q'] });   // an old, small saved map
        console.log(JSON.stringify(ACTIONS.filter(a => !(map[a.id] || []).length)
                                          .map(a => a.id)));
    """)
    assert got == []


def test_events_map_onto_bindings():
    got = node(IMPORT + """
        const ev = (key, mods = {}) => ({ key, ctrlKey: !!mods.ctrl,
            altKey: !!mods.alt, shiftKey: !!mods.shift, metaKey: !!mods.meta });
        console.log(JSON.stringify([
            bindingFor(ev('w')),
            bindingFor(ev('W', { shift: true })),
            bindingFor(ev('ArrowLeft')),
            bindingFor(ev('ArrowLeft', { shift: true })),
            bindingFor(ev('=', { ctrl: true })),
            bindingFor(ev('Control', { ctrl: true })),
            bindingFor(ev(' ')),
        ]));
    """)
    assert got == ["w", "W", "arrowleft", "shift+arrowleft", "ctrl+=", "", " "]


def test_a_lone_modifier_is_never_a_binding():
    """Otherwise pressing Ctrl on the way to Ctrl+K would capture "ctrl"."""
    got = node(IMPORT + """
        const ev = k => ({ key: k, ctrlKey: true, altKey: false,
                           shiftKey: false, metaKey: false });
        console.log(JSON.stringify(['Control', 'Shift', 'Alt', 'Meta']
            .map(k => bindingFor(ev(k)))));
    """)
    assert got == ["", "", "", ""]


def test_two_actions_on_one_key_are_reported():
    got = node(IMPORT + """
        const map = { ...defaults(), mode: ['q'], theme: ['q'] };
        console.log(JSON.stringify(conflicts(map)));
    """)
    assert len(got) == 1
    assert got[0]["key"] == "q"
    assert sorted(got[0]["actions"]) == ["mode", "theme"]


# ─────────────────────────────────────────────── wiring, not just the module


def read(name):
    with open(os.path.join(APP, name), encoding="utf-8") as handle:
        return handle.read()


def test_the_help_sheet_is_generated_not_hand_written():
    """It had already drifted from the dispatcher once."""
    html = read("index.html")
    assert '<dl id="r-shortcuts-list"></dl>' in html
    assert "renderShortcutSheet" in read("app.js")


def test_the_dispatcher_no_longer_hard_codes_keys():
    source = read("app.js")
    assert "keymap.handle(e)" in source
    assert "case 'ArrowLeft':" not in source


def test_the_theme_tab_is_gone_from_the_rail_but_the_shortcut_is_not():
    """The user asked for the rail entry to go because Settings already has a
    full palette. Cutting the *feature* was never the request."""
    html = read("index.html")
    assert 'id="theme-cycle"' not in html
    source = read("app.js")
    assert "cycleTheme" in source
    assert ".on('theme'" in source


# ───────────────────────────────────────────────── the window titlebar


def test_the_titlebar_is_hidden_until_python_says_there_is_a_window():
    """In a browser -- the LAN server, or a test harness -- there is no
    native window. Drawing minimise/maximise/close buttons that silently do
    nothing is worse than not drawing them, so the markup ships hidden and
    only `window_state.available` reveals it."""
    html = read("index.html")
    assert '<div id="titlebar" hidden>' in html
    source = read("app.js")
    block = source[source.index("async function setupTitlebar"):]
    block = block[:block.index("\n}\n")]
    assert "window_state" in block
    assert "available" in block


def test_every_window_control_reaches_python():
    source = read("app.js")
    for method in ("window_minimize", "window_maximize", "window_close"):
        assert method in source, method


def test_the_drag_region_excludes_the_buttons():
    """A button inside a -webkit-app-region: drag area never receives the
    click -- the OS takes the press as the start of a window move."""
    css = read("style.css")
    block = css[css.index("/* ── custom window titlebar"):]
    assert "-webkit-app-region: drag" in block
    assert "-webkit-app-region: no-drag" in block
    controls = block[block.index(".tb-controls {"):]
    controls = controls[:controls.index("}")]
    assert "no-drag" in controls


def test_the_shell_is_shortened_not_just_padded():
    """#shell is height:100% of a full-height body, so padding-top pushed the
    content down but left the element at y=0 and made the page 34px too
    tall. Measured. It has to be shortened as well as moved."""
    css = read("style.css")
    block = css[css.index("body.has-titlebar #shell"):]
    block = block[:block.index("}")]
    assert "margin-top" in block
    assert "calc(100% - var(--titlebar-h))" in block


def test_the_reader_overlay_clears_the_titlebar():
    """#reader is fixed to the viewport, so without its own offset it would
    sit underneath the window controls."""
    css = read("style.css")
    assert "body.has-titlebar #reader { top: var(--titlebar-h); }" in css


def test_a_frameless_window_is_draggable():
    """pywebview needs easy_drag as well: without it a frameless window
    cannot be moved at all on backends that ignore -webkit-app-region."""
    gui = open(os.path.join(ROOT, "mangasurf", "gui", "__init__.py"),
               encoding="utf-8").read()
    assert "frameless=chrome" in gui
    assert "easy_drag=chrome" in gui


def test_the_native_frame_can_be_put_back():
    """Some Linux window managers handle frameless windows badly, so there
    has to be a way back that is not editing JSON by hand."""
    from mangasurf.gui import DEFAULT_SETTINGS

    assert "custom_titlebar" in DEFAULT_SETTINGS


def test_closing_honours_minimise_to_tray():
    """That setting exists so a 300-chapter download survives the window
    being closed. Our own close button must not bypass it."""
    gui = open(os.path.join(ROOT, "mangasurf", "gui", "__init__.py"),
               encoding="utf-8").read()
    block = gui[gui.index("def window_close"):]
    block = block[:block.index("\n    def ")]
    assert "minimize_to_tray" in block
    assert "window.hide()" in block


def test_window_controls_degrade_without_a_native_window():
    """The LAN server shares this Api object. A phone pressing "close" must
    not take down the host's application."""
    from mangasurf.gui import Api

    api = Api()
    api.window = None
    for method in ("window_minimize", "window_maximize", "window_close",
                   "window_restore", "window_fullscreen"):
        result = getattr(api, method)()
        assert result["ok"] is False, method
    assert api.window_state()["available"] is False
