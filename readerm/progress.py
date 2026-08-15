"""Live transfer metrics: bytes/second, ETA and queue depth.

Used by the system-tray context menu and the GUI. Nothing else in the app
measured throughput before this -- the engine only recorded a byte total
*after* a job finished, which is useless while one is running.

Design notes
------------
**Rolling window, not a lifetime average.** A cumulative
``bytes / elapsed`` figure is dominated by history: pause a download for a
minute and the reported speed stays high, resume on a slow link and it stays
high for minutes more. The rate here is measured over the last
:data:`WINDOW` seconds only, so it tracks what is happening now.

**ETA from pages, not bytes.** The total byte size of a download is not known
until it finishes -- image sizes vary by an order of magnitude and no source
reports them up front. Pages, though, are known as soon as each chapter's
image list is fetched. So the ETA is ``pages remaining / pages per second``,
which is both computable and stable. Where the page total is not yet known
the ETA is reported as ``None`` rather than guessed.

Everything is thread-safe: the download engine calls into this from its image
worker threads, and the tray reads it from the tray thread.
"""

import threading
import time

#: Seconds of history used for the rate calculation.
WINDOW = 8.0

#: Samples older than this are discarded outright; a job that has produced
#: nothing for this long is reported as stalled (0 B/s) rather than showing
#: a stale rate.
STALE_AFTER = 30.0


def human_bytes(count):
    """Format a byte count. Returns e.g. ``"4.2 MB"``."""
    try:
        value = float(count or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def human_rate(bytes_per_second):
    """Format a transfer rate. Returns e.g. ``"1.8 MB/s"``."""
    try:
        value = float(bytes_per_second or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return "0 KB/s"
    if value < 1024:
        return f"{value:.0f} B/s"
    if value < 1024 * 1024:
        return f"{value / 1024:.0f} KB/s"
    return f"{value / (1024 * 1024):.1f} MB/s"


def human_eta(seconds):
    """Format a duration as an ETA. ``None`` becomes ``"--"``."""
    if seconds is None:
        return "--"
    try:
        total = int(max(0, seconds))
    except (TypeError, ValueError):
        return "--"
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m {total % 60:02d}s"
    hours, rest = divmod(total, 3600)
    if hours < 24:
        return f"{hours}h {rest // 60:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


class RateMeter:
    """Rolling-window throughput meter.

    Samples are ``(timestamp, amount)`` pairs trimmed to :data:`WINDOW`
    seconds on every read, so memory stays bounded regardless of runtime.
    """

    def __init__(self, window=WINDOW):
        self.window = float(window)
        self._samples = []
        self._total = 0
        self._lock = threading.Lock()

    def add(self, amount):
        """Record ``amount`` units transferred just now."""
        if not amount:
            return
        now = time.time()
        with self._lock:
            self._samples.append((now, amount))
            self._total += amount
            self._trim(now)

    def _trim(self, now):
        cutoff = now - self.window
        samples = self._samples
        # Samples are appended in time order, so a prefix drop is enough.
        index = 0
        for index, (stamp, _amount) in enumerate(samples):
            if stamp >= cutoff:
                break
        else:
            index = len(samples)
        if index:
            del samples[:index]

    @property
    def total(self):
        with self._lock:
            return self._total

    def rate(self):
        """Units per second over the window, or ``0.0`` when stalled."""
        now = time.time()
        with self._lock:
            self._trim(now)
            if not self._samples:
                return 0.0
            moved = sum(amount for _stamp, amount in self._samples)
            oldest = self._samples[0][0]
            # Divide by the window, not by the span between first and last
            # sample: with two samples 10ms apart the span is tiny and the
            # computed rate is absurd. Early on, use the elapsed time so the
            # first seconds are not divided by a window that has not passed.
            span = max(min(self.window, now - oldest), 0.5)
            if now - self._samples[-1][0] > STALE_AFTER:
                return 0.0
            return moved / span


class JobProgress:
    """Live metrics for one download job."""

    def __init__(self, job_id, title=""):
        self.job_id = job_id
        self.title = title
        self.bytes = RateMeter()
        self.pages = RateMeter()
        self._lock = threading.Lock()
        self.pages_done = 0
        self.pages_total = 0
        self.chapters_done = 0
        self.chapters_total = 0
        self.started = time.time()
        self.finished = None
        #: Recent bytes/sec samples for the queue sparkline. Bounded, and
        #: appended by snapshot() so it costs nothing when nobody is looking.
        self.history = []
        self._last_sample = 0.0

    # -- updates ------------------------------------------------------

    def add_bytes(self, amount):
        self.bytes.add(amount)

    def add_page(self, count=1):
        self.pages.add(count)
        with self._lock:
            self.pages_done += count

    def set_pages(self, done=None, total=None):
        with self._lock:
            if done is not None:
                self.pages_done = done
            if total is not None:
                self.pages_total = total

    def set_chapters(self, done=None, total=None):
        with self._lock:
            if done is not None:
                self.chapters_done = done
            if total is not None:
                self.chapters_total = total

    def finish(self):
        self.finished = time.time()

    # -- reads --------------------------------------------------------

    def eta_seconds(self):
        """Seconds remaining, or ``None`` when it cannot be known.

        The page total only becomes known chapter by chapter -- a source does
        not report page counts up front, they arrive as each chapter's image
        list is fetched. Reporting an ETA purely off ``pages_total`` therefore
        showed "--" for most of a run and then jumped straight to a few
        seconds, which is useless.

        So when chapter counts are known, the remaining chapters are
        projected using the average page count of the chapters seen so far.
        That is an estimate and is treated as one: it is only used when at
        least one chapter has completed, so the average is grounded in real
        data rather than a guess.

        Still returns ``None`` when nothing is known yet -- an honest "--"
        beats a fabricated number.
        """
        with self._lock:
            done, total = self.pages_done, self.pages_total
            chapters_done, chapters_total = self.chapters_done, self.chapters_total

        rate = self.pages.rate()
        if rate <= 0:
            return None

        remaining = max(0, total - done)

        # Project the chapters whose page lists have not been fetched yet.
        if chapters_total and chapters_done and total:
            unseen = chapters_total - chapters_done
            if unseen > 0:
                average = total / max(1, chapters_done)
                # Only count chapters not already included in `total`.
                counted = total / average if average else 0
                extra = max(0.0, (chapters_total - counted)) * average
                remaining += extra

        if remaining <= 0:
            return None
        return remaining / rate

    #: How many rate samples the sparkline keeps.
    HISTORY = 40

    def _sample(self, rate):
        """Append to the rate history, at most a few times a second."""
        now = time.time()
        if now - self._last_sample < 0.4:
            return
        self._last_sample = now
        with self._lock:
            self.history.append(round(rate))
            if len(self.history) > self.HISTORY:
                del self.history[:len(self.history) - self.HISTORY]

    def snapshot(self, sample=False):
        rate = self.bytes.rate()
        if sample and self.finished is None:
            self._sample(rate)
        with self._lock:
            done, total = self.pages_done, self.pages_total
            chapters_done, chapters_total = self.chapters_done, self.chapters_total
            history = list(self.history)
        eta = self.eta_seconds()
        return {
            "job_id": self.job_id,
            "title": self.title,
            "bytes": self.bytes.total,
            "bytes_per_second": rate,
            "pages_done": done,
            "pages_total": total,
            "chapters_done": chapters_done,
            "chapters_total": chapters_total,
            "eta_seconds": eta,
            "elapsed": (self.finished or time.time()) - self.started,
            "running": self.finished is None,
            # Pre-formatted so the UI never has to reimplement the units.
            "speed_text": human_rate(rate),
            "eta_text": human_eta(eta),
            "downloaded_text": human_bytes(self.bytes.total),
            "history": history,
        }


class ProgressRegistry:
    """All jobs' progress, aggregated.

    The tray needs one combined figure -- total speed, total queue depth,
    soonest completion -- across however many jobs are running.
    """

    def __init__(self):
        self._jobs = {}
        self._lock = threading.RLock()
        self._queued = 0

    def job(self, job_id, title=""):
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                entry = JobProgress(job_id, title)
                self._jobs[job_id] = entry
            elif title and not entry.title:
                entry.title = title
            return entry

    def drop(self, job_id):
        with self._lock:
            self._jobs.pop(job_id, None)

    def set_queued(self, count):
        """How many jobs are waiting to start (not yet running)."""
        with self._lock:
            self._queued = max(0, int(count or 0))

    def clear_finished(self):
        with self._lock:
            for job_id in [k for k, v in self._jobs.items()
                           if v.finished is not None]:
                del self._jobs[job_id]

    def active(self):
        with self._lock:
            return [j for j in self._jobs.values() if j.finished is None]

    def summary(self):
        """Combined metrics for the tray tooltip and menu."""
        with self._lock:
            running = [j for j in self._jobs.values() if j.finished is None]
            queued = self._queued

        # One snapshot per job: calling it four times also sampled the
        # history four times, which made the sparkline advance too fast.
        snapshots = [j.snapshot(sample=True) for j in running]
        rate = sum(s["bytes_per_second"] for s in snapshots)
        total_bytes = sum(s["bytes"] for s in snapshots)
        pages_done = sum(s["pages_done"] for s in snapshots)
        pages_total = sum(s["pages_total"] for s in snapshots)
        chapters_done = sum(s["chapters_done"] for s in snapshots)
        chapters_total = sum(s["chapters_total"] for s in snapshots)

        # Overall ETA is the longest of the running jobs, since they finish
        # in parallel -- not the sum, which would overstate it badly, and not
        # the shortest, which would promise a finish that has not happened.
        etas = [s["eta_seconds"] for s in snapshots]
        etas = [e for e in etas if e is not None]
        eta = max(etas) if etas else None

        return {
            "active": len(running),
            "queued": queued,
            "chapters_done": chapters_done,
            "chapters_total": chapters_total,
            "chapters_remaining": max(0, chapters_total - chapters_done),
            "pages_done": pages_done,
            "pages_total": pages_total,
            "bytes": total_bytes,
            "bytes_per_second": rate,
            "eta_seconds": eta,
            "speed_text": human_rate(rate),
            "eta_text": human_eta(eta),
            "downloaded_text": human_bytes(total_bytes),
            "jobs": snapshots,
        }


#: Process-wide registry. The engine writes to it, the tray reads from it.
REGISTRY = ProgressRegistry()
