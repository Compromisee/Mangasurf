"""System-tray icon: keep downloading with the window closed.

What this provides
------------------
* Closing the window **hides** it instead of quitting, so downloads carry on.
* A tray icon whose tooltip and context menu show live progress:
  transfer rate, ETA, how many chapters are queued, and each running job.
* Menu actions to reopen the window, pause/resume the queue, and quit for
  real.

Optional, and quiet about it
----------------------------
``pystray`` is an optional dependency and **importing it can fail outright**:
on a machine with no display it raises ``Xlib.error.DisplayNameError`` at
import time, not at first use. Reproduced here -- ``import pystray`` on a
headless box exits with a traceback before any of our code runs. So the
import is guarded, kept out of module scope, and every entry point degrades
to "no tray, window behaves normally" rather than taking the app down.

The same applies at runtime: some Linux desktops have no StatusNotifier host,
in which case ``icon.run()`` raises. That is caught too, and
:meth:`TrayController.start` reports failure so the caller can fall back to
the ordinary close-quits behaviour.
"""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

#: Tray icon size in pixels. 64 is large enough for HiDPI trays to downscale
#: cleanly and small enough to build in a millisecond.
ICON_SIZE = 64


def tray_available():
    """Whether a tray can be created here, without importing at module scope.

    Importing pystray has side effects -- it opens an X display connection on
    Linux and raises if there is none -- so this is deliberately a function
    and deliberately cheap to call.
    """
    try:
        import pystray  # noqa: F401
    except Exception as e:              # ImportError, Xlib errors, anything
        logger.debug("tray unavailable: %s", e)
        return False
    return True


def _build_icon_image(active=False):
    """Draw the Mangasurf tray icon, tinted/badged when downloads are running."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    size = ICON_SIZE
    
    # Try loading high-res custom icon if available
    icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "icon.png")
    if os.path.isfile(icon_path):
        try:
            base = Image.open(icon_path).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            if active:
                draw = ImageDraw.Draw(base)
                draw.ellipse((size - 20, size - 20, size - 4, size - 4), fill=(255, 107, 122, 255), outline=(255, 255, 255, 255), width=1)
            return base
        except Exception:
            pass

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Rounded plate so the glyph reads on both light and dark trays.
    plate = (18, 18, 28, 255)
    accent = (56, 189, 248, 255) if active else (140, 146, 170, 255)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=14, fill=plate)

    # Stylized wave / surf curves
    draw.arc([8, 8, size - 8, size - 8], start=45, end=270, fill=accent, width=4)
    draw.line([(size // 2 - 4, size // 2), (size // 2 + 12, size // 2 - 10)], fill=(244, 63, 94, 255), width=3)

    if active:
        # A dot in the corner marks "work in progress" at a glance.
        draw.ellipse((size - 22, size - 22, size - 6, size - 6),
                     fill=(255, 107, 122, 255))
    return image


class TrayController:
    """Owns the tray icon and the menu built from live progress.

    ``callbacks`` supplies the host application's behaviour so this class
    stays testable without a GUI:

        show_window()     bring the window back
        quit_app()        really exit
        toggle_pause()    pause/resume the queue, returns the new state
        is_paused()       current queue state
        summary()         a mangasurf.progress-style summary dict
    """

    #: Do not repeat the same notification text inside this many seconds.
    DEDUPE_SECONDS = 30.0

    def __init__(self, callbacks=None, title="Mangasurf"):
        self.callbacks = callbacks or {}
        self.title = title
        self.icon = None
        self._thread = None
        self._stop = threading.Event()
        self._last_active = None
        #: Set once Quit has been chosen, so :meth:`wait` can return.
        self._quit = threading.Event()
        # Notification bookkeeping -- see notify().
        self._notify_lock = threading.Lock()
        self._notified = {}          # message -> monotonic time last shown
        self._notified_once = set()  # messages flagged once=True
        self._last_notify_at = 0.0

    # ------------------------------------------------------------ data

    def summary(self):
        getter = self.callbacks.get("summary")
        if getter is None:
            from .progress import REGISTRY
            return REGISTRY.summary()
        try:
            return getter() or {}
        except Exception:
            logger.debug("tray summary failed", exc_info=True)
            return {}

    def tooltip(self):
        """Hover text. Kept short -- some trays truncate hard."""
        data = self.summary()
        active = data.get("active", 0)
        queued = data.get("queued", 0)
        if not active and not queued:
            return f"{self.title} — idle"
        parts = [f"{data.get('speed_text', '0 KB/s')}"]
        if data.get("eta_text", "--") != "--":
            parts.append(f"ETA {data['eta_text']}")
        remaining = data.get("chapters_remaining", 0)
        if remaining:
            parts.append(f"{remaining} ch left")
        if queued:
            parts.append(f"{queued} queued")
        return f"{self.title} — " + "  ·  ".join(parts)

    # ------------------------------------------------------------ menu

    def _menu_lines(self):
        """The dynamic part of the context menu, as display strings.

        Split out so the exact text can be unit-tested without pystray.
        """
        data = self.summary()
        active = data.get("active", 0)
        queued = data.get("queued", 0)
        lines = []

        if active:
            lines.append(f"↓  {data.get('speed_text', '0 KB/s')}"
                         f"     ETA {data.get('eta_text', '--')}")
            done = data.get("chapters_done", 0)
            total = data.get("chapters_total", 0)
            if total:
                lines.append(f"Chapters:  {done}/{total}"
                             f"  ({data.get('chapters_remaining', 0)} left)")
            pages_total = data.get("pages_total", 0)
            if pages_total:
                lines.append(f"Pages:  {data.get('pages_done', 0)}/{pages_total}")
            lines.append(f"Downloaded:  {data.get('downloaded_text', '0 B')}")
        else:
            lines.append("No active downloads")

        if queued:
            lines.append(f"Queued:  {queued} waiting")

        # One line per running job, so several downloads are distinguishable.
        for job in (data.get("jobs") or [])[:5]:
            title = (job.get("title") or "Untitled")[:34]
            chapters_total = job.get("chapters_total") or 0
            if chapters_total:
                lines.append(f"   • {title} "
                             f"({job.get('chapters_done', 0)}/{chapters_total})")
            else:
                lines.append(f"   • {title}")
        extra = len(data.get("jobs") or []) - 5
        if extra > 0:
            lines.append(f"   • …and {extra} more")
        return lines

    def _build_menu(self):
        from pystray import Menu, MenuItem

        def status_items():
            # Rebuilt every time the menu opens, so the numbers are current.
            for line in self._menu_lines():
                yield MenuItem(line, None, enabled=False)
            yield Menu.SEPARATOR
            yield MenuItem("Open Mangasurf", self._on_open, default=True)
            yield MenuItem(
                "Resume queue" if self._is_paused() else "Pause queue",
                self._on_pause)
            yield Menu.SEPARATOR
            yield MenuItem("Quit", self._on_quit)

        return Menu(status_items)

    # --------------------------------------------------------- actions

    def _call(self, name, *args):
        fn = self.callbacks.get(name)
        if fn is None:
            return None
        try:
            return fn(*args)
        except Exception:
            logger.exception("tray callback '%s' failed", name)
            return None

    def _is_paused(self):
        return bool(self._call("is_paused"))

    def _on_open(self, _icon=None, _item=None):
        self._call("show_window")

    def _on_pause(self, _icon=None, _item=None):
        self._call("toggle_pause")
        self.refresh()

    def _on_quit(self, _icon=None, _item=None):
        self._quit.set()
        self.stop()
        self._call("quit_app")

    # ------------------------------------------------------- lifecycle

    def start(self):
        """Create and run the tray icon on a background thread.

        Returns True when the icon is running, False when a tray is not
        available here -- the caller must then keep the ordinary
        close-quits-the-app behaviour.
        """
        if not tray_available():
            return False
        try:
            from pystray import Icon
        except Exception:
            return False

        try:
            self.icon = Icon(
                "readerm",
                icon=_build_icon_image(False),
                title=self.tooltip(),
                menu=self._build_menu(),
            )
        except Exception:
            logger.exception("could not construct the tray icon")
            return False

        started = threading.Event()

        def run():
            try:
                # run_detached would hand the loop to the host toolkit; we
                # want our own thread so this works alongside pywebview.
                started.set()
                self.icon.run()
            except Exception:
                logger.exception("tray icon stopped")
                started.set()

        self._thread = threading.Thread(target=run, name="readerm-tray",
                                        daemon=True)
        self._thread.start()
        started.wait(timeout=5)

        # A tray that dies immediately (no StatusNotifier host, for one) is
        # not a working tray; report failure so the caller can fall back.
        if not self._thread.is_alive():
            return False

        self._start_refresh_loop()
        return True

    def _start_refresh_loop(self, interval=2.0):
        """Keep the tooltip and icon in step with what is happening."""
        def loop():
            while not self._stop.wait(interval):
                try:
                    self.refresh()
                except Exception:
                    logger.debug("tray refresh failed", exc_info=True)

        threading.Thread(target=loop, name="readerm-tray-refresh",
                         daemon=True).start()

    def refresh(self):
        """Update the tooltip, and the icon when the active state flips."""
        if self.icon is None:
            return
        try:
            self.icon.title = self.tooltip()
        except Exception:
            pass

        active = bool(self.summary().get("active"))
        if active != self._last_active:
            self._last_active = active
            try:
                image = _build_icon_image(active)
                if image is not None:
                    self.icon.icon = image
            except Exception:
                logger.debug("tray icon repaint failed", exc_info=True)
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def notify(self, message, title=None, dedupe_seconds=None, once=False):
        """Desktop notification, where the platform supports one.

        Rate limited and de-duplicated, because a tray balloon is one of the
        few things in the app a bug can fire hundreds of times.

        Reported as "repeated notifications over and over like a loop", and
        reproduced: a window manager that delivers the close event more than
        once (minimise/restore, a taskbar "Close window", a WebView2 hiccup,
        or the backend-retry path in ``run_gui`` which closes the window once
        per attempt) produced **one balloon per event** -- 20 events in 0.4s
        gave 20 balloons. Nothing here checked whether the same message had
        just been shown.

        Two guards, both cheap:

        ``dedupe_seconds``
            The same text is not shown twice inside this window. Defaults to
            :attr:`DEDUPE_SECONDS`.
        ``once``
            The message is shown at most once for the lifetime of this tray,
            for things like "still running in the background" that are only
            news the first time.

        Deliberately keyed on the message **text**, not on a global rate
        limit. Five books finishing in quick succession are five different
        events and all five deserve a balloon; the same sentence arriving
        five times is one event reported five times. A first attempt at this
        fix used a blanket floor between any two notifications and silently
        ate 4 of 5 genuine "download finished" messages -- caught by the
        job-completion harness, which is why that distinction is now tested.
        """
        if self.icon is None or not message:
            return False

        now = time.monotonic()
        window = (self.DEDUPE_SECONDS if dedupe_seconds is None
                  else float(dedupe_seconds))

        with self._notify_lock:
            if once and message in self._notified_once:
                return False
            last = self._notified.get(message)
            if last is not None and (now - last) < window:
                logger.debug("suppressed duplicate notification: %s", message)
                return False
            self._notified[message] = now
            self._last_notify_at = now
            if once:
                self._notified_once.add(message)
            # Keep the seen-map from growing without bound in a long session.
            if len(self._notified) > 64:
                cutoff = now - window
                self._notified = {k: v for k, v in self._notified.items()
                                  if v > cutoff}

        try:
            self.icon.notify(message, title or self.title)
            return True
        except Exception:
            logger.debug("tray notification failed", exc_info=True)
            return False

    def reset_notifications(self):
        """Forget what has been shown, so a real new event can notify again."""
        with self._notify_lock:
            self._notified.clear()
            self._notified_once.clear()
            self._last_notify_at = 0.0

    # ------------------------------------------------- keeping alive

    def quit_requested(self):
        """Whether Quit has been chosen from the tray menu."""
        return self._quit.is_set()

    def wait_for_quit(self, poll=0.5, still_working=None):
        """Block the *main thread* until Quit, or until work runs out.

        Why this exists
        ---------------
        ``start()`` runs the icon on a **daemon** thread, and every worker
        thread in the app is a daemon too. Python kills daemon threads at
        interpreter exit, so the moment ``webview.start()`` returned the
        whole process went with it -- measured directly: with a tray running
        and downloads active, the child process exited in **0.06s** with
        rc=0. "Minimise to tray" set the flag, hid the window, and the app
        died anyway, which is exactly the reported symptom.

        The window closing is a UI event; the *process* has to be held open
        by something non-daemon, and only the main thread can do that after
        the GUI loop returns.

        ``still_working`` is an optional predicate. When given, the wait also
        ends once it returns False, so a tray whose icon failed to appear
        cannot strand a headless process forever -- it exits when the queue
        drains rather than lingering invisibly.
        """
        while not self._quit.wait(poll):
            if self.icon is None and not self._thread_alive():
                return False            # the tray died; do not hang on it
            if still_working is not None:
                try:
                    if not still_working():
                        return False
                except Exception:
                    logger.debug("still_working check failed", exc_info=True)
                    return False
        return True

    def _thread_alive(self):
        return bool(self._thread is not None and self._thread.is_alive())

    def stop(self):
        self._stop.set()
        self._quit.set()             # release anyone in wait_for_quit()
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
