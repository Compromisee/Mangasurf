"""Cover rebuilder: give every CBZ folder a ``cover.jpg``.

What it does
------------
Walk a folder tree, find every ``.cbz``, work out the series each one belongs
to, search the enabled sources for a cover, and write ``cover.jpg`` **next to
the CBZ** -- not in the parent.

Two rules make that harder than it sounds, and both come straight from how
real libraries look:

**1. One series per folder.** If several different series sit loose in the
same directory, writing one ``cover.jpg`` there would be wrong for all but
one of them. So those archives are first moved into a subfolder each, named
after the series, and the cover goes in with its archive. Archives that are
already alone with their own series are left exactly where they are -- this
never reorganises a library that is already tidy.

**2. Titles have to be recovered from filenames.** A CBZ is named for what is
inside it, not for the series alone::

    Afterlife Diner - Chapters 001.cbz
    Afterlife Diner - Chapters 001-050.cbz
    Afterlife Diner - Chapters 001-003, 007-008, 020.cbz
    Afterlife Diner - Chapter 005.cbz

...and third-party libraries add their own noise: ``[Group]`` prefixes,
``(2024)`` years, ``v03``, ``c045``, scanlator suffixes, resolution tags.
:func:`clean_title` strips all of it so the search actually matches.

Nothing is destructive
----------------------
* Planning and applying are separate: :func:`plan` only reads.
* An existing ``cover.jpg`` is skipped unless ``overwrite`` is set.
* Moving a file never overwrites another; a clashing name gets a suffix.
* Every failure is collected and reported rather than aborting the run.
"""

import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

#: Archive types worth covering.
ARCHIVE_EXTENSIONS = (".cbz", ".cbr", ".cb7", ".zip")

#: Cover filenames already understood by comic readers, in preference order.
COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp",
               "folder.jpg", "poster.jpg")

# --------------------------------------------------------------- cleaning
#
# Each pattern removes one naming convention. Order matters: bracketed groups
# go first so their contents cannot be mistaken for chapter markers.

#: "[Group]", "(2024)", "{v2}" -- anywhere in the name.
_BRACKETED = re.compile(r"[\[\(\{][^\]\)\}]*[\]\)\}]")

#: ReaderM's own suffixes, and the usual third-party equivalents.
#: Handles "Chapter 5", "Chapters 001-050", "Ch. 3-9", "c045", "#12".
_CHAPTER_TAIL = re.compile(
    r"""[\s._-]*                       # separator before the marker
        (?:-\s*)?                      # ReaderM writes " - Chapters ..."
        (?:chapters?|chapts?|chaps?|chs|ch|cap(?:itulo)?s?|
           episodes?|eps?|c|e|\#)      # longest spellings first, or "ch"
                                       # would match inside "chs" and leave
                                       # an orphan "s" in the title
        [\s._]*                        # "Chapter 5", "Ch.5", "c045"
        \d+(?:\.\d+)?                  # the number
        (?:\s*[-–—~]\s*\d+(?:\.\d+)?)? # an inclusive range: 001-036
        (?:\s*,\s*\d+(?:\.\d+)?        # further comma-separated runs
           (?:\s*[-–—~]\s*\d+(?:\.\d+)?)?)*
        .*$                            # and anything after it
    """, re.I | re.X)

#: Volume markers: "Vol 3", "v03", "Volume 12".
_VOLUME_TAIL = re.compile(
    r"[\s._-]*(?:-\s*)?(?:vol(?:ume)?|v)[\s._]*\d+(?:\.\d+)?.*$", re.I)

#: A trailing bare number that is clearly an index, e.g. "Series - 005".
#: Requires a dash separator OR zero-padding: plain "Series 2" is a title
#: ("Kingdom 2", "Overlord 3"), whereas "Series - 005" and "Series 005" are
#: indexes. Getting this wrong truncates real titles.
_TRAILING_INDEX = re.compile(
    r"(?:[\s._]*-[\s._]*\d{1,4}(?:\.\d+)?"      # " - 5", " - 005"
    r"|[\s._]+0\d{1,3}(?:\.\d+)?)$")            # " 005" (zero padded)

#: Quality/format noise some releases carry.
_QUALITY = re.compile(
    r"\b(?:\d{3,4}p|hd|fhd|uhd|4k|web[\s-]?rip|digital|scan(?:s|ned)?|"
    r"colou?red|official|raw|complete[d]?|repack|fixed|v\d)\b", re.I)

#: Separators that stand in for spaces in filenames.
_SEPARATORS = re.compile(r"[._]+")


def clean_title(name):
    """Recover a searchable series title from a file or folder name.

    ``"[Group] Afterlife Diner - Chapters 001-050 (2024) [1080p].cbz"``
    becomes ``"Afterlife Diner"``.

    Never returns an empty string when the input had any word characters:
    if stripping removes everything, the least-stripped form is kept. A
    title reduced to "" would search for nothing and match everything.
    """
    text = str(name or "")
    text = os.path.splitext(text)[0]

    stages = [text]
    text = _BRACKETED.sub(" ", text)
    stages.append(text)
    text = _SEPARATORS.sub(" ", text)
    stages.append(text)
    text = _QUALITY.sub(" ", text)
    stages.append(text)
    text = _CHAPTER_TAIL.sub("", text)
    stages.append(text)
    text = _VOLUME_TAIL.sub("", text)
    stages.append(text)
    text = _TRAILING_INDEX.sub("", text)
    stages.append(text)

    # Walk back to the last stage that still held something.
    for candidate in reversed(stages):
        cleaned = re.sub(r"\s+", " ", candidate).strip(" -–—_,.")
        if cleaned:
            return cleaned
    return ""


def series_key(name):
    """Case/punctuation-insensitive identity for grouping archives."""
    return re.sub(r"[^a-z0-9]+", " ", clean_title(name).lower()).strip()


# ---------------------------------------------------------------- scanning


def _archives_in(directory):
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    return sorted(
        name for name in entries
        if name.lower().endswith(ARCHIVE_EXTENSIONS)
        and os.path.isfile(os.path.join(directory, name))
    )


def existing_cover(directory):
    """Path of a cover already in this folder, or ``None``."""
    for name in COVER_NAMES:
        path = os.path.join(directory, name)
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


def scan(root, overwrite=False):
    """Plan the work for one tree, without changing anything.

    Returns a list of *groups*, each describing one series found in one
    directory::

        {"title", "key", "directory", "archives", "needs_move",
         "target_dir", "has_cover"}

    ``needs_move`` is True when the directory holds more than one distinct
    series, so this group's archives must be given a folder of their own.
    """
    groups = []
    # An empty root must mean "nowhere", not "here". os.path.abspath("")
    # returns the current working directory, so scan("") quietly walked
    # whatever folder the process happened to be in -- picking up build
    # output when run from a checkout, and the user's home when packaged.
    if not (root or "").strip():
        return groups
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return groups

    for directory, subdirs, _files in os.walk(root):
        # Skip the raw page folders the downloader leaves behind.
        subdirs[:] = [d for d in subdirs if d not in ("raw", ".raw")]

        archives = _archives_in(directory)
        if not archives:
            continue

        by_series = {}
        for archive in archives:
            key = series_key(archive) or "unknown"
            by_series.setdefault(key, []).append(archive)

        # Several series loose in one folder: each needs its own home, or a
        # single cover.jpg here would be wrong for all but one of them.
        mixed = len(by_series) > 1

        for key, names in sorted(by_series.items()):
            title = clean_title(names[0])
            target = os.path.join(directory, title) if mixed else directory
            groups.append({
                "title": title,
                "key": key,
                "directory": directory,
                "archives": names,
                "needs_move": mixed,
                "target_dir": target,
                "has_cover": existing_cover(target) is not None,
            })

    return groups


def plan(root, overwrite=False):
    """Groups that still need a cover (or all of them when overwriting)."""
    return [g for g in scan(root) if overwrite or not g["has_cover"]]


# ----------------------------------------------------------------- moving


def _unique_path(path):
    """A path that does not exist yet, by adding ' (2)', ' (3)', ..."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    index = 2
    while os.path.exists(f"{stem} ({index}){ext}"):
        index += 1
    return f"{stem} ({index}){ext}"


def isolate(group, dry_run=False):
    """Move a group's archives into their own folder when they share one.

    Returns the directory the cover belongs in. Existing files are never
    overwritten -- a clash is renamed.
    """
    if not group.get("needs_move"):
        return group["directory"]

    target = group["target_dir"]
    if dry_run:
        return target

    os.makedirs(target, exist_ok=True)
    for name in list(group["archives"]):
        source = os.path.join(group["directory"], name)
        if not os.path.isfile(source):
            continue
        destination = _unique_path(os.path.join(target, name))
        try:
            shutil.move(source, destination)
        except OSError as e:
            logger.warning("could not move %s: %s", source, e)
            raise
    return target


# ---------------------------------------------------------------- covers


def candidates(title, sources=None, limit=6, timeout=None):
    """Cover candidates for a title, from every enabled source.

    Returns ``[{"title", "cover", "source", "source_name", "url", "score"}]``
    ranked best-first. Scoring favours an exact title match, because a fuzzy
    hit on a long catalogue is usually a different series entirely.
    """
    from .features import _normalise_title
    from .sources import search_all

    title = (title or "").strip()
    if not title:
        return []

    try:
        results = search_all(title, source_ids=sources, limit=limit,
                             use_config=sources is None)
    except Exception as e:
        logger.warning("cover search failed for %r: %s", title, e)
        return []

    wanted = _normalise_title(title)
    ranked = []
    for row in results:
        cover = (row.get("cover") or "").strip()
        if not cover:
            continue
        found = _normalise_title(row.get("title"))
        if found == wanted:
            score = 100
        elif wanted and (wanted in found or found in wanted):
            score = 70
        else:
            # Weak match: keep it, but rank it below anything better. The
            # user picks, so a wrong-but-plausible option is not harmful --
            # silently applying it would be.
            score = 30
        ranked.append({
            "title": row.get("title"),
            "cover": cover,
            "source": row.get("source"),
            "source_name": row.get("source_name") or row.get("source"),
            "url": row.get("url"),
            "score": score,
        })

    ranked.sort(key=lambda r: -r["score"])
    return ranked


def save_cover(url, directory, source_id=None, referer=None,
               filename="cover.jpg"):
    """Download one cover into ``directory``.

    Goes through the owning source so its Referer rules apply -- several
    cover CDNs answer 403 to a bare request.
    """
    from .sources import get_source, source_for_url

    os.makedirs(directory, exist_ok=True)
    destination = os.path.join(directory, filename)

    source = None
    try:
        source = (get_source(source_id) if source_id
                  else source_for_url(url))
    except Exception:
        try:
            source = source_for_url(url)
        except Exception:
            source = None

    if source is None:
        from .sources import get_source as _get
        source = _get()          # default source: plain requests session

    try:
        ok = source.download_file(url, destination, referer=referer)
    finally:
        try:
            source.close()
        except Exception:
            pass

    if not ok:
        return None
    return destination

# ------------------------------------------------------------ auto-pick
#
# "Smart search": one button that scans, chooses and applies, without the
# user picking each cover by hand.

#: Below this many pixels a cover is a list thumbnail, not artwork. Measured
#: across sources: the same series ships at 175x238 on one site and
#: 800x1164 on another, so rank alone picks a thumbnail surprisingly often.
MIN_GOOD_PIXELS = 300 * 400


def measure_cover(url, source_id=None, referer=None, timeout=20):
    """``(width, height, bytes)`` for a cover, or ``None`` if unreadable.

    Downloads the image once. Callers cache the result rather than fetching
    twice, since the auto-picker measures every candidate.
    """
    from io import BytesIO

    from .sources import get_source, source_for_url

    source = None
    try:
        source = get_source(source_id) if source_id else source_for_url(url)
    except Exception:
        try:
            source = source_for_url(url)
        except Exception:
            source = None
    if source is None:
        from .sources import get_source as _default
        source = _default()

    try:
        headers = {"Referer": referer} if referer else None
        response = source.fetch(url, max_retries=2, headers=headers,
                                timeout=timeout)
        blob = response.content
    except Exception as e:
        logger.debug("could not measure %s: %s", url, e)
        return None
    finally:
        try:
            source.close()
        except Exception:
            pass

    try:
        from PIL import Image

        with Image.open(BytesIO(blob)) as image:
            width, height = image.size
    except Exception:
        return None
    return width, height, len(blob), blob


def auto_pick(rows, measure=True, limit=8):
    """Choose the best cover from ranked candidates.

    Ordering, most significant first:

    1. **title match** -- an exact match always beats a fuzzy one; a cover
       for the wrong series is a failure however pretty it is;
    2. **source rank** -- the order set in Settings, which is the user
       saying which sites they trust;
    3. **resolution** -- but only to separate a real cover from a list
       thumbnail, not to override the ranking.

    Rank is honoured *within* each quality tier rather than globally,
    because the alternative is silently ignoring the ranking whenever a
    lower-ranked site happens to serve a bigger JPEG. Measured across three
    titles, the rank-1 candidate was 6x-15x smaller in pixels than the best
    available, so ignoring size entirely is equally wrong.

    Returns ``(chosen, measurements)``; ``chosen`` is ``None`` when nothing
    usable was found.
    """
    from .config import rank_of

    if not rows:
        return None, {}

    measurements = {}
    considered = rows[:max(1, int(limit))]

    if measure:
        for row in considered:
            result = measure_cover(row.get("cover"), row.get("source"),
                                   row.get("url"))
            if result:
                width, height, size, blob = result
                measurements[row["cover"]] = {
                    "width": width, "height": height, "bytes": size,
                    "pixels": width * height, "blob": blob,
                }

    def sort_key(row):
        info = measurements.get(row.get("cover"))
        pixels = info["pixels"] if info else 0
        # Unmeasured covers are treated as "probably fine" rather than
        # worst: a source that blocks a HEAD is not necessarily low quality.
        good = 1 if (not measurements or pixels >= MIN_GOOD_PIXELS
                     or (not info and measure)) else 0
        return (
            -int(row.get("score", 0)),        # exact title first
            -good,                            # real artwork before thumbnails
            rank_of(row.get("source") or ""),  # then the Settings order
            -pixels,                          # then simply the biggest
        )

    ordered = sorted(considered, key=sort_key)
    return ordered[0], measurements


def auto_cover(title, directory, sources=None, limit=6, measure=True):
    """Search, choose and save a cover in one call.

    Returns ``{"ok", "cover"|"error", "chosen"}``. Reuses the bytes fetched
    while measuring, so a cover is never downloaded twice.
    """
    rows = candidates(title, sources=sources, limit=limit)
    if not rows:
        return {"ok": False, "error": "No cover found", "chosen": None}

    chosen, measurements = auto_pick(rows, measure=measure)
    if chosen is None:
        return {"ok": False, "error": "No usable cover", "chosen": None}

    info = measurements.get(chosen.get("cover")) or {}
    blob = info.get("blob")
    if blob:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "cover.jpg")
        try:
            with open(path + ".part", "wb") as handle:
                handle.write(blob)
            os.replace(path + ".part", path)
        except OSError as e:
            return {"ok": False, "error": str(e), "chosen": chosen}
    else:
        path = save_cover(chosen["cover"], directory,
                          source_id=chosen.get("source"),
                          referer=chosen.get("url"))
        if not path:
            return {"ok": False, "error": "Download failed",
                    "chosen": chosen}

    return {"ok": True, "cover": path, "chosen": chosen,
            "width": info.get("width"), "height": info.get("height")}


# ======================================================= cover propagation
#
# A folder full of loose page images (an unpacked chapter, a "raw" dump, an
# imported scan) has no cover.jpg, so file managers, Kavita, Komga and OPDS
# readers all show it as a blank tile. The images are right there -- one of
# them is the cover.

#: Page images we will consider using as a cover.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

#: Folders that never want a cover of their own: they hold intermediate
#: pages that belong to the series folder above them.
SKIP_DIRS = {"raw", ".raw", "__pycache__", ".git", ".thumbnails"}


def images_in(directory):
    """Page images directly in this folder, sorted naturally.

    Sorted with the same numeric-aware key the packager uses, so "10.jpg"
    does not sort before "2.jpg" and hand us the wrong page as the cover.
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = [n for n in names
             if n.lower().endswith(IMAGE_EXTENSIONS)
             and not _is_cover_name(n)
             and os.path.isfile(os.path.join(directory, n))]
    return sorted(found, key=_natural_key)


def _is_cover_name(name):
    stem = os.path.splitext(name)[0].lower()
    return stem in ("cover", "folder", "poster", "thumbnail", "default")


def _natural_key(name):
    """Split digits out so page 2 sorts before page 10."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", name)]


def scan_image_folders(root, overwrite=False):
    """Folders holding page images that have no cover yet.

    Returns ``[{directory, images, first, has_cover, count}]``. Nothing is
    written -- this is the preview the UI shows before you commit.
    """
    found = []
    if not (root or "").strip():
        return found
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(root):
        return found

    for directory, subdirs, _files in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
        images = images_in(directory)
        if not images:
            continue
        existing = existing_cover(directory)
        if existing and not overwrite:
            continue
        found.append({
            "directory": directory,
            "images": images,
            "first": os.path.join(directory, images[0]),
            "count": len(images),
            "has_cover": existing is not None,
        })
    return found


def propagate_covers(root, overwrite=False, dry_run=False, source="first",
                     name="cover.jpg"):
    """Give every image folder under ``root`` a cover file.

    ``source``
        ``"first"``   use the first page (the usual cover);
        ``"parent"``  copy the nearest cover from a parent folder, falling
                      back to the first page when there is none.

    The cover is **copied**, never moved or converted: the original page is
    still part of the chapter, and re-encoding it would lose quality for no
    reason. The extension follows the source image, so a PNG page produces
    ``cover.png`` rather than a JPEG-named PNG that some readers reject.
    """
    import shutil

    plan_rows = scan_image_folders(root, overwrite=overwrite)
    results = {"created": [], "skipped": [], "failed": [], "dry_run": dry_run}

    for row in plan_rows:
        directory = row["directory"]
        chosen = row["first"]

        if source == "parent":
            inherited = _nearest_parent_cover(directory, root)
            if inherited:
                chosen = inherited

        # Keep the real extension: a .png written as cover.jpg is a file
        # whose bytes disagree with its name, and strict readers skip it.
        ext = os.path.splitext(chosen)[1].lower()
        if ext not in IMAGE_EXTENSIONS:
            ext = ".jpg"
        stem = os.path.splitext(name)[0] or "cover"
        target = os.path.join(directory, stem + ext)

        if os.path.abspath(chosen) == os.path.abspath(target):
            results["skipped"].append(directory)
            continue

        if dry_run:
            results["created"].append({"directory": directory,
                                       "cover": target, "from": chosen})
            continue

        try:
            shutil.copy2(chosen, target)
            results["created"].append({"directory": directory,
                                       "cover": target, "from": chosen})
        except OSError as exc:
            results["failed"].append({"directory": directory,
                                      "error": str(exc)})
    return results


def _nearest_parent_cover(directory, root):
    """Walk up to ``root`` looking for a cover to inherit."""
    root = os.path.abspath(root)
    current = os.path.abspath(directory)
    while True:
        parent = os.path.dirname(current)
        if parent == current or not parent.startswith(root):
            return None
        found = existing_cover(parent)
        if found:
            return found
        current = parent


def set_cover(directory, image_path, name="cover.jpg"):
    """Replace one folder's cover with a chosen image.

    Used by "change cover" in the UI. Any existing cover under a *different*
    extension is removed, or the folder ends up with both cover.jpg and
    cover.png and readers disagree about which wins.
    """
    import shutil

    if not os.path.isdir(directory):
        return {"ok": False, "error": "No such folder"}
    if not os.path.isfile(image_path):
        return {"ok": False, "error": "No such image"}

    ext = os.path.splitext(image_path)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        return {"ok": False, "error": f"Not an image type: {ext or '?'}"}

    stem = os.path.splitext(name)[0] or "cover"
    target = os.path.join(directory, stem + ext)

    for existing in COVER_NAMES:
        path = os.path.join(directory, existing)
        if os.path.isfile(path) and os.path.abspath(path) != os.path.abspath(target):
            try:
                os.remove(path)
            except OSError:
                pass

    try:
        if os.path.abspath(image_path) != os.path.abspath(target):
            shutil.copy2(image_path, target)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "cover": target}
