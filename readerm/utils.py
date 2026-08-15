"""Shared helpers: sorting, sanitising, chapter parsing."""

import re


def natural_sort_key(text):
    """Key for natural sorting: '2.jpg' < '10.jpg'."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", str(text))]


def sanitize(name: str) -> str:
    """Make a string safe for use as a file / directory name."""
    name = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    return re.sub(r"\s+", " ", name) or "untitled"


def chapter_number(chapter_name: str) -> float:
    """Extract a numeric chapter number from a chapter name (supports decimals)."""
    match = re.search(r"(?:chapter|episode|ch\.?|ep\.?)?\s*(\d+(?:\.\d+)?)", chapter_name, re.I)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def format_chapter_number(value: float) -> str:
    """Format a chapter number as a zero padded label, e.g. 5 -> '005', 23.5 -> '023.5'."""
    if value == int(value):
        return f"{int(value):03d}"
    whole = int(value)
    frac = str(value).split(".", 1)[1]
    return f"{whole:03d}.{frac}"


def parse_selection(spec: str, chapters: list) -> list:
    """Parse a chapter selection string against a chapter list.

    Supported syntax (chapter numbers, not indices):
        ""            -> all chapters
        "all"         -> all chapters
        "5"           -> chapter 5
        "23.5"        -> chapter 23.5
        "1-20"        -> chapters 1 through 20 (inclusive)
        "1,5,10-20"   -> combination
        "50-"         -> chapter 50 to the end
        "-10"         -> start to chapter 10
        "latest"      -> the newest chapter
        "first"       -> the oldest chapter

    Returns the selected chapter dicts in reading order.
    """
    spec = (spec or "").strip().lower()
    if not spec or spec == "all":
        return list(chapters)
    if spec == "latest":
        return [chapters[-1]] if chapters else []
    if spec == "first":
        return [chapters[0]] if chapters else []

    numbered = [(chapter_number(c["name"]), c) for c in chapters]
    selected, seen = [], set()

    def add(chapter):
        key = id(chapter)
        if key not in seen:
            seen.add(key)
            selected.append(chapter)

    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, _, right = part.partition("-")
            try:
                lo = float(left) if left.strip() else float("-inf")
                hi = float(right) if right.strip() else float("inf")
            except ValueError:
                raise ValueError(f"Invalid range: '{part}'")
            if lo > hi:
                lo, hi = hi, lo
            for num, chapter in numbered:
                if lo <= num <= hi:
                    add(chapter)
        else:
            try:
                target = float(part)
            except ValueError:
                raise ValueError(f"Invalid chapter: '{part}'")
            hit = False
            for num, chapter in numbered:
                if num == target:
                    add(chapter)
                    hit = True
            if not hit:
                raise ValueError(f"Chapter {part} not found")

    selected.sort(key=lambda c: chapter_number(c["name"]))
    return selected


def chunk(items: list, size: int) -> list:
    """Split a list into consecutive chunks of `size`. size <= 0 -> one chunk."""
    if size <= 0:
        return [list(items)] if items else []
    return [items[i:i + size] for i in range(0, len(items), size)]


def chapter_range_label(names, max_list: int = 4) -> str:
    """Human label describing the chapters a package contains.

    Used to name output files so a CBZ/PDF/EPUB says what is inside it
    rather than just carrying the series title.

        ["Chapter 1"]                      -> "001"
        ["Chapter 1", "Chapter 2"]         -> "001-002"
        1..50 with no gaps                 -> "001-050"
        1,2,3, 7,8, 20                     -> "001-003, 007-008, 020"

    Non-contiguous selections are collapsed into runs, and a selection with
    many separate runs is truncated so the filename stays a sane length.
    """
    numbers = sorted({chapter_number(n) for n in (names or [])})
    if not numbers:
        return ""
    if len(numbers) == 1:
        return format_chapter_number(numbers[0])

    # Group into runs. A step of at most 1 continues the run, so half
    # chapters (10 -> 10.5 -> 11) stay part of "010-011" instead of being
    # spelled out individually.
    runs, start, previous = [], numbers[0], numbers[0]
    for value in numbers[1:]:
        if value - previous > 1.0001:
            runs.append((start, previous))
            start = value
        previous = value
    runs.append((start, previous))

    def render(lo, hi):
        low, high = format_chapter_number(lo), format_chapter_number(hi)
        return low if low == high else f"{low}-{high}"

    if len(runs) <= max_list:
        return ", ".join(render(lo, hi) for lo, hi in runs)

    # too fragmented to spell out: show the span plus how many are included
    return f"{format_chapter_number(numbers[0])}-" \
           f"{format_chapter_number(numbers[-1])} ({len(numbers)} chapters)"


def chapter_bounds(names):
    """``(lowest, highest)`` chapter labels for a set of chapter names."""
    numbers = sorted({chapter_number(n) for n in (names or [])})
    if not numbers:
        return "", ""
    return format_chapter_number(numbers[0]), format_chapter_number(numbers[-1])
