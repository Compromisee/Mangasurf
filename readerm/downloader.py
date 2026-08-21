"""Download engine: orchestrates scraping, image downloads and packaging.

Emits structured events through a callback so both the CLI and the GUI can
render progress however they like.
"""
import sys

# Allow running this file directly (python readerm/downloader.py, or an IDE's
# "Run file"). Without this the relative imports below have no parent package
# and raise ImportError before the module can do anything.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"



import logging
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from threading import Lock

from .packager import EXTENSIONS, PACKAGERS
from .sources import get_source, source_for_url
from . import library
from .utils import (
    chapter_bounds,
    chapter_number,
    chapter_range_label,
    chunk,
    format_chapter_number,
    parse_selection,
    sanitize,
)

logger = logging.getLogger(__name__)


@dataclass
class DownloadOptions:
    url: str = ""
    selection: str = "all"          # chapter selection string, see utils.parse_selection
    output_dir: str = "downloads"
    format: str = "cbz"             # cbz | pdf | epub | images
    bundle: int = 0                 # 0 = everything in one file, N = N chapters per file
    chapter_workers: int = 3        # concurrent chapters
    image_workers: int = 6          # concurrent images per chapter
    delay: float = 0.5              # polite delay between chapters (seconds)
    keep_images: bool = False       # keep raw images after packaging
    retries: int = 5                # retries per image download
    extra_formats: list = field(default_factory=list)  # additional formats to produce
    # naming templates; placeholders: {title} {chapter} {start} {end}
    name_single: str = "{title} - Chapters {chapters}"
    name_chapter: str = "{title} - Chapter {chapter}"
    name_range: str = "{title} - Chapters {chapters}"
    # multi-source options
    source: str = ""                # source id; "" = auto-detect from the URL
    language: str = "en"            # translation language (MangaDex)
    scanlator: str = ""             # preferred scanlation group (MangaDex)
    data_saver: bool = False        # smaller compressed pages (MangaDex)


class DownloadEngine:
    """Runs one manga download job."""

    def __init__(self, options: DownloadOptions, on_event=None, job_id=None):
        self.opt = options
        self.on_event = on_event or (lambda event: None)
        self.source = self._make_source()
        self._image_pool = None
        # kept as `scraper` too so older integrations keep working
        self.scraper = self.source
        self._stop = False
        self.failed = []

        # Live throughput, for the tray menu and the GUI. Registered under a
        # stable id so concurrent jobs are tracked separately.
        from .progress import REGISTRY
        self.job_id = job_id or f"job-{id(self):x}"
        self.progress = REGISTRY.job(self.job_id)
        # Feed the meter from the source's byte stream.
        self.source.on_bytes = self.progress.add_bytes

    # -------------------------------------------------------------- source

    def _make_source(self):
        """Build the source for this job, auto-detecting from the URL."""
        kwargs = {
            "delay": self.opt.delay,
            "language": self.opt.language or "en",
            "scanlator": self.opt.scanlator or None,
            "data_saver": bool(self.opt.data_saver),
        }
        if self.opt.source:
            return get_source(self.opt.source, **kwargs)
        return source_for_url(self.opt.url, **kwargs)

    # ----------------------------------------------------------------- api

    def stop(self):
        self._stop = True

    def emit(self, type_, **data):
        try:
            self.on_event({"type": type_, **data})
        except Exception:
            pass

    # ----------------------------------------------------------------- run

    def run(self) -> dict:
        """Execute the job. Returns a result summary dict."""
        opt = self.opt
        started_at = time.time()
        self.emit("status", message="Fetching manga information")

        info = self.source.get_manga_info(opt.url)
        title = sanitize(info["title"])
        # Name the job so the tray menu shows the series, not "Untitled".
        # CLI runs have no title until this point; the GUI sets one up front.
        if not self.progress.title:
            self.progress.title = info.get("title") or opt.url
        self.emit("manga", info=info)

        chapters = self.source.get_chapters(opt.url)
        if not chapters:
            self.emit("error", message="No chapters found")
            return {"ok": False, "error": "No chapters found"}

        try:
            selected = parse_selection(opt.selection, chapters)
        except ValueError as e:
            self.emit("error", message=str(e))
            return {"ok": False, "error": str(e)}

        if not selected:
            self.emit("error", message="Selection matched no chapters")
            return {"ok": False, "error": "Selection matched no chapters"}

        manga_dir = os.path.join(opt.output_dir, title)
        raw_dir = os.path.join(manga_dir, "raw")
        os.makedirs(manga_dir, exist_ok=True)

        self.emit("plan", title=title, total=len(selected),
                  chapters=[c["name"] for c in selected], directory=manga_dir,
                  source=self.source.id, source_name=self.source.name)

        # Cover
        if info.get("cover"):
            ext = self.source.guess_extension(info["cover"])
            cover_path = os.path.join(manga_dir, f"cover{ext}")
            if not os.path.exists(cover_path):
                self.source.download_file(info["cover"], cover_path, referer=opt.url)

        # Checkpoint of completed chapters (crash-safe resume).
        # v2 format: "name<TAB>pages"; legacy lines (name only) still accepted.
        checkpoint = os.path.join(manga_dir, ".checkpoint")
        done_pages = {}   # chapter name -> expected page count (0 = unknown)
        if os.path.exists(checkpoint):
            with open(checkpoint, encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue
                    name, _, pages = line.partition("\t")
                    try:
                        done_pages[name] = int(pages)
                    except ValueError:
                        done_pages[name] = 0

        def chapter_complete_on_disk(name):
            """True if a previous run fully downloaded this chapter."""
            expected = done_pages.get(name)
            if expected is None:
                return False
            target = os.path.join(raw_dir, sanitize(name))
            if not os.path.isdir(target):
                return False
            have = [f for f in os.listdir(target)
                    if not f.endswith(".part") and os.path.getsize(
                        os.path.join(target, f)) > 0]
            return len(have) >= expected > 0

        # Journal: mark this job as in progress so a crash can offer resume
        from . import logs as _logs
        _logs.write_journal(asdict(opt), {
            "title": info["title"], "directory": manga_dir,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, job_id=self.job_id)

        # ------------------------------------------------------- download
        # Total in-flight requests are bounded by this single pool, sized so
        # concurrent chapters cannot multiply it.
        total_image_workers = max(1, min(16, opt.chapter_workers * opt.image_workers))
        self._image_pool = ThreadPoolExecutor(
            max_workers=total_image_workers,
            thread_name_prefix="readerm-img",
        )

        chapter_dirs = {}  # chapter name -> images dir
        completed = 0
        checkpoint_lock = Lock()

        def worker(chapter):
            if self._stop:
                return chapter, 0, None
            name = chapter["name"]
            target = os.path.join(raw_dir, sanitize(name))

            # Fast path: fully present from a previous (crashed) run
            if chapter_complete_on_disk(name):
                pages = done_pages.get(name, 0)
                self.emit("chapter_start", chapter=name)
                self.emit("chapter_progress", chapter=name, done=pages, total=pages)
                logger.info("Resuming: '%s' already complete (%d pages)", name, pages)
                return chapter, pages, target

            os.makedirs(target, exist_ok=True)
            self.emit("chapter_start", chapter=name)

            try:
                urls = self.source.get_chapter_images(chapter)
            except Exception as e:
                logger.error("Could not list pages for '%s': %s", name, e)
                return chapter, 0, None
            if not urls:
                logger.warning("Chapter '%s' has no pages", name)
                return chapter, 0, None

            got = 0
            # One shared image pool for the whole job. Previously a new pool
            # was created per chapter on top of the chapter pool, so live
            # thread count churned and peaked at chapter_workers x
            # image_workers.
            pool = self._image_pool
            futures = {}
            referer = chapter.get("referer") or chapter.get("url")
            extra_headers = chapter.get("headers")

            # Now that the page list is known, fold it into the ETA total.
            self.progress.set_pages(total=self.progress.pages_total + len(urls))

            for i, url in enumerate(urls, 1):
                ext = self.source.guess_extension(url)
                path = os.path.join(target, f"{i:03d}{ext}")
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    got += 1
                    self.emit("chapter_progress", chapter=name,
                              done=got, total=len(urls))
                    continue
                futures[pool.submit(
                    self.source.download_file, url, path, referer,
                    self.opt.retries, extra_headers,
                )] = url

            for future in as_completed(futures):
                if self._stop:
                    break
                if future.result():
                    got += 1
                    self.progress.add_page()
                    self.emit("chapter_progress", chapter=name,
                              done=got, total=len(urls))

            # Only a COMPLETE chapter counts; partial ones will be resumed
            # next run (existing images are skipped, missing ones refetched).
            if got == len(urls):
                return chapter, got, target
            if got:
                logger.warning("Chapter '%s' incomplete: %d/%d pages "
                               "(will resume next run)", name, got, len(urls))
            return chapter, 0, None

        with ThreadPoolExecutor(max_workers=max(1, opt.chapter_workers)) as pool:
            futures = [pool.submit(worker, c) for c in selected]
            for future in as_completed(futures):
                if self._stop:
                    break
                chapter, got, target = future.result()
                name = chapter["name"]
                if target:
                    chapter_dirs[name] = target
                    completed += 1
                    if done_pages.get(name, 0) < got:
                        with checkpoint_lock:
                            done_pages[name] = got
                            with open(checkpoint, "a", encoding="utf-8") as f:
                                f.write(f"{name}\t{got}\n")
                                f.flush()
                                os.fsync(f.fileno())
                    try:
                        library.record_chapter(
                            opt.url, info["title"], name, pages=got,
                            cover=info.get("cover"), directory=manga_dir,
                            source=self.source.id,
                        )
                    except Exception:
                        logger.debug("Failed to record chapter in library", exc_info=True)
                    self.progress.set_chapters(done=completed,
                                               total=len(selected))
                    self.emit("chapter_done", chapter=name, pages=got,
                              completed=completed, total=len(selected))
                elif not self._stop:
                    self.failed.append(chapter)
                    self.emit("chapter_failed", chapter=name)
                time.sleep(opt.delay)

        self._image_pool.shutdown(wait=True)

        if self._stop:
            self.progress.finish()
            self.emit("stopped")
            _logs.clear_journal(self.job_id)
            return {"ok": False, "stopped": True}

        # -------------------------------------------------------- package
        ordered = [
            (chapter_dirs[c["name"]], c["name"])
            for c in sorted(selected, key=lambda c: chapter_number(c["name"]))
            if c["name"] in chapter_dirs
        ]

        outputs = []
        formats = [opt.format] + [f for f in opt.extra_formats if f != opt.format]
        formats = [f for f in dict.fromkeys(formats) if f in PACKAGERS or f == "images"]

        for fmt in formats:
            if fmt == "images":
                continue
            outputs += self._package(fmt, ordered, manga_dir, title)

        keep = opt.keep_images or "images" in formats or not outputs
        if not keep and os.path.isdir(raw_dir):
            shutil.rmtree(raw_dir, ignore_errors=True)
            try:
                os.remove(checkpoint)
            except OSError:
                pass

        # statistics
        try:
            from . import features
            total_pages = sum(done_pages.get(c["name"], 0) for c in selected)
            byte_total = 0
            for out in outputs:
                try:
                    byte_total += os.path.getsize(out)
                except OSError:
                    pass
            features.record_stat(
                self.source.id, chapters=completed, pages=total_pages,
                bytes_=byte_total, seconds=time.time() - started_at,
                failed=len(self.failed),
            )
        except Exception:
            logger.debug("Failed to record statistics", exc_info=True)

        if outputs:
            try:
                library.record_outputs(opt.url, outputs)
            except Exception:
                logger.debug("Failed to record outputs in library", exc_info=True)

        # Write metadata JSON file into the series folder
        try:
            meta = {
                "title": title,
                "url": opt.url,
                "description": info.get("description") or "",
                "source": self.source.id,
                "source_name": self.source.name,
                "provider": self.source.name,
                "status": info.get("status") or "Ongoing",
                "authors": info.get("authors") or [],
                "artists": info.get("artists") or [],
                "tags": info.get("tags") or [],
                "format": opt.format,
                "cover": info.get("cover") or "",
                "total_chapters": completed,
                "total_pages": total_pages,
                "size_bytes": byte_total,
                "outputs": outputs,
                "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            meta_path = os.path.join(manga_dir, "manga.json")
            with open(meta_path, "w", encoding="utf-8") as mf:
                json.dump(meta, mf, indent=2, ensure_ascii=False)
        except Exception:
            logger.debug("Failed to write manga.json metadata", exc_info=True)

        # Only this job's record -- a sibling job may still be running.
        _logs.clear_journal(self.job_id)
        self.progress.finish()

        self.emit("done", downloaded=completed, failed=len(self.failed),
                  outputs=outputs, directory=manga_dir)
        return {
            "ok": True,
            "source": self.source.id,
            "title": title,
            "directory": manga_dir,
            "downloaded": completed,
            "failed": [c["name"] for c in self.failed],
            "outputs": outputs,
        }

    # ------------------------------------------------------------- helpers

    def _package(self, fmt, ordered, manga_dir, title):
        """Package chapters into one or more volume files. Returns output paths."""
        if not ordered:
            return []
        packager = PACKAGERS[fmt]
        ext = EXTENSIONS[fmt]
        outputs = []

        def render(template, fallback, **kw):
            try:
                name = template.format(**kw).strip()
                return name or fallback.format(**kw)
            except (KeyError, IndexError, ValueError):
                return fallback.format(**kw)

        groups = chunk(ordered, self.opt.bundle)
        for group in groups:
            names = [name for _dir, name in group]
            # what this file actually contains, e.g. "001-050" or
            # "001-003, 007-008, 020" for a non-contiguous selection
            chapters_label = chapter_range_label(names)
            lo, hi = chapter_bounds(names)
            count = len(group)

            fields = {
                "title": title,
                "chapters": chapters_label,
                "start": lo,
                "end": hi,
                "count": count,
                "chapter": lo,
            }

            if len(groups) == 1:
                # A single file still says which chapters are inside it,
                # rather than carrying only the series title.
                label = render(self.opt.name_single,
                               "{title} - Chapters {chapters}", **fields)
            elif count == 1:
                fields["chapter"] = format_chapter_number(
                    chapter_number(group[0][1]))
                label = render(self.opt.name_chapter,
                               "{title} - Chapter {chapter}", **fields)
            else:
                label = render(self.opt.name_range,
                               "{title} - Chapters {chapters}", **fields)

            out_path = os.path.join(manga_dir, sanitize(label) + ext)
            self.emit("packaging", format=fmt, file=os.path.basename(out_path))
            result = packager(group, out_path, label)
            if result:
                outputs.append(result)
                self.emit("packaged", format=fmt, file=result)
        return outputs
