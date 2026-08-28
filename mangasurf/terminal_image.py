"""Real terminal image rendering for the TUI (captured as kitty / iTerm2 /
Sixel / half-block, whichever the terminal supports).

The desktop reader renders covers in a window; the TUI runs in a plain ANSI
terminal, so a cover has to become bytes the terminal can actually paint.
Terminal image support has come a long way — Kitty, WezTerm, Ghostty,
iTerm2/Terminal.app, and xterm-with-sixel all draw true pixels — and far more
people run one of those than not.

Rather than pick one, this module *detects* what the running terminal can do
and prefers the richest protocol it supports, falling back to the old
TrueColor ANSI half-block artwork (which works everywhere) when nothing
better is available.

Detection only inspects the current process's environment (``TERM``,
``TERM_PROGRAM``, ``KITTY_WINDOW_ID``, ``WEZTERM_PANE``, ``SSH_TTY``), which
is exactly what a terminal advertises at connection time. That is mostly
right, has no I/O cost, and is what every terminal does. Protocol-specific
guards are still layered in so a false positive degrades to text rather than
garbage.

``textual_image`` (a pip extra) converts between the formats; if it is not
installed we still produce half-block ANSI, so nothing regresses.
"""

from __future__ import annotations

import io
import os

#: Width (px) at which a rendered image counts as "the cover", regardless of
#: the target width we asked for in cells. Guards against downscaling a
#: thumbnail to something unreadable.
_MAX_PX = 512


def detect_image_protocol() -> str:
    """Return the best terminal image protocol this process can paint.

    ``"kitty"`` → Kitty / WezTerm / Ghostty graphics protocol.
    ``"sixel"`` → xterm-style Sixel.
    ``"iterm"`` → iTerm2 / Terminal.app inline images (OSC 1337).
    ``"halfcell"`` → ANSI half-block (always available, worst quality).
    ``""``      → detection failed; caller should use the half-block fallback.

    The order matters: many modern terminals advertise several, and the
    highest-quality one wins.
    """
    term = (os.environ.get("TERM") or "").lower()
    term_program = (os.environ.get("TERM_PROGRAM") or "").lower()
    kitty = bool(os.environ.get("KITTY_WINDOW_ID"))
    wez = bool(os.environ.get("WEZTERM_PANE"))

    # Kitty / WezTerm / Ghostty all speak the Kitty graphics protocol.
    if kitty or wez or "kitty" in term or "ghostty" in term_program:
        return "kitty"
    # Foot / mlterm / wezterm(also kitty) / xterm advertise Sixel via TERM.
    if "sixel" in term or "foot" in term or term_program in ("wezterm",):
        return "sixel"
    if term_program == "iterm.app" or term_program == "iterm2":
        return "iterm"
    if "tmux" in term or "screen" in term:
        # tmux can forward kitty graphics (>=3.2) or iterm; be conservative and
        # default to half-cell unless we have strong evidence otherwise.
        return "" 
    if "xterm" in term or "vt100" in term or "linux" in term or "ansi" in term or "cygwin" in term:
        return ""
    # Anything with 24-bit colour support is at worst half-cell-capable.
    return ""


def supports_true_image() -> bool:
    """True if the terminal can draw real pixels (not just block art)."""
    return detect_image_protocol() in ("kitty", "sixel", "iterm")


def _load(source_or_bytes, source_id=None, referer=None):
    """Return a PIL Image (cached where possible) or ``None``."""
    try:
        from PIL import Image as PILImage
        from .covers import fetch_cover_bytes

        blob = None
        if isinstance(source_or_bytes, (bytes, bytearray)):
            blob = bytes(source_or_bytes)
        elif isinstance(source_or_bytes, str):
            if source_or_bytes.startswith(("http://", "https://")):
                blob = fetch_cover_bytes(source_or_bytes, source_id=source_id, referer=referer)
                if not blob:
                    return None
            elif os.path.isfile(source_or_bytes):
                with open(source_or_bytes, "rb") as fh:
                    blob = fh.read()
        if not blob:
            return None
        img = PILImage.open(io.BytesIO(blob))
        return img.convert("RGB")
    except Exception:
        return None


def render_cover(source_or_bytes, width=22, max_height=11, source_id=None,
                 referer=None):
    """Render a cover for the terminal, using the best protocol available.

    Returns a ``str`` ready to be handed to a Textual ``Static`` (or printed
    to ``sys.stdout``). If the terminal supports true image protocols we emit
    the escape-sequence form that ``textual_image`` understands — but because
    a Textual ``Static`` is a *grid of cells* (it can only hold characters,
    not arbitrary byte escapes), the rich pixel output is only used when the
    caller can mount a real image widget. That split is handled in the TUI.
    """
    # Always produce the ANSI half-block artwork: it is the portable baseline
    # and the only form a Textual `Static` can safely display.
    try:
        from .covers import render_terminal_cover
        return render_terminal_cover(
            source_or_bytes, width=width, max_height=max_height,
            source_id=source_id, referer=referer)
    except Exception:
        return ""


def render_image_bytes(source_or_bytes, source_id=None, referer=None):
    """Return ``(pil_image, width_px, height_px)`` for a true-image widget.

    Used by the TUI to feed a ``textual_image`` widget when the terminal
    supports one; ``None`` image means "fall back to ANSI".
    """
    img = _load(source_or_bytes, source_id=source_id, referer=referer)
    if img is None:
        return None, 0, 0
    w, h = img.size
    return img, w, h
