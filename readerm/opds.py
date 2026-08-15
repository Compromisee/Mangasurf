"""An OPDS 1.2 catalog for the downloaded library.

Point Readest, Panels, KyBook, Chunky, Aldiko or any other OPDS reader at
this and your downloaded manga shows up as a browsable catalog, with covers,
straight from the machine that downloaded it.

    python opdsserve.py                  # http://<this-pc>:8578/opds

Why a separate server from ``readerm.server``
---------------------------------------------
They answer different questions. ``readerm/server.py`` serves the *app* to a
phone browser -- it is the whole UI over HTTP. This serves *files* to a
dedicated reader over a standardised protocol, so the reader handles
downloading, shelving and reading. They can run at once on different ports,
and they share the library and the settings file.

What the spec actually requires
-------------------------------
Checked against https://specs.opds.io/opds-1.2.html rather than copied from
another implementation, because OPDS clients are strict in ways that are
easy to get subtly wrong:

* every feed needs ``id``, ``title``, ``updated`` and a ``self`` link;
* navigation and acquisition feeds carry **different** ``type`` parameters
  on their links (``kind=navigation`` vs ``kind=acquisition``) -- a client
  that follows a mislabelled link often shows an empty shelf rather than an
  error;
* every catalog entry needs at least one acquisition link, with a ``type``
  telling the client what it will get;
* ``atom:updated`` must be RFC 3339, and entries in an acquisition feed are
  ordered newest first.

Facets and search are included because they are what make a catalog usable
once it holds more than a screenful.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import sys
import time
from xml.sax.saxutils import escape, quoteattr

# Allow running this file directly (python readerm/opds.py, or an IDE's
# "Run file"). Without this the relative imports below have no parent
# package and raise ImportError before anything else happens.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"

from . import library

#: Atom namespaces used in every feed.
NS = ('xmlns="http://www.w3.org/2005/Atom" '
      'xmlns:dc="http://purl.org/dc/terms/" '
      'xmlns:opds="http://opds-spec.org/2010/catalog" '
      'xmlns:thr="http://purl.org/syndication/thread/1.0"')

#: Link types the spec defines. Getting these wrong is the single most
#: common reason a reader shows an empty catalog.
NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
ENTRY_TYPE = "application/atom+xml;type=entry;profile=opds-catalog"
SEARCH_TYPE = "application/opensearchdescription+xml"

REL_ACQUISITION = "http://opds-spec.org/acquisition"
REL_IMAGE = "http://opds-spec.org/image"
REL_THUMB = "http://opds-spec.org/image/thumbnail"
REL_FACET = "http://opds-spec.org/facet"

#: Media types per output format. A reader filters on these, so a wrong one
#: makes the book invisible rather than merely mislabelled.
MEDIA_TYPES = {
    ".cbz": "application/vnd.comicbook+zip",
    ".cbr": "application/vnd.comicbook-rar",
    ".cb7": "application/vnd.comicbook+7z",
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".mobi": "application/x-mobipocket-ebook",
}

#: Image types allowed by the spec for cover links.
IMAGE_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif",
    ".webp": "image/webp",
}

DEFAULT_PORT = 8578

#: Entries per page. Enough that a phone scrolls rather than paginates,
#: small enough that a 2000-book library does not build one enormous XML
#: document on every request.
PAGE_SIZE = 60


def _now_rfc3339():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _to_rfc3339(stamp):
    """Convert the library's ``YYYY-MM-DD HH:MM:SS`` to RFC 3339.

    Readers sort on this. A malformed value makes some of them drop the
    entry entirely, so anything unparseable falls back to now.
    """
    if not stamp:
        return _now_rfc3339()
    text = str(stamp).strip().replace(" ", "T")
    if text.endswith("Z"):
        return text
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", text):
        return text + "Z"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return text + "T00:00:00Z"
    return _now_rfc3339()


def stable_id(*parts):
    """A deterministic urn for an entry.

    Must not change between runs: readers use it to decide whether a book is
    already on the shelf, so a random id re-downloads everything every sync.
    """
    digest = hashlib.sha1("\u0000".join(str(p) for p in parts).encode(
        "utf-8", "replace")).hexdigest()
    return f"urn:uuid:{digest[:8]}-{digest[8:12]}-{digest[12:16]}-" \
           f"{digest[16:20]}-{digest[20:32]}"


def media_type_for(path):
    ext = os.path.splitext(path or "")[1].lower()
    if ext in MEDIA_TYPES:
        return MEDIA_TYPES[ext]
    guessed = mimetypes.guess_type(path or "")[0]
    return guessed or "application/octet-stream"


def image_type_for(path):
    ext = os.path.splitext(path or "")[1].lower()
    return IMAGE_TYPES.get(ext, "image/jpeg")


# ------------------------------------------------------------ XML building


def _attrs(**kwargs):
    out = []
    for key, value in kwargs.items():
        if value is None:
            continue
        out.append(f'{key.replace("_", ":")}={quoteattr(str(value))}')
    return " ".join(out)


def link(rel, href, type_=None, title=None, **extra):
    parts = _attrs(rel=rel, href=href, type=type_, title=title, **extra)
    return f"  <link {parts}/>"


def element(name, text, **attrs):
    if text is None:
        return ""
    rendered = _attrs(**attrs)
    space = " " + rendered if rendered else ""
    return f"<{name}{space}>{escape(str(text))}</{name}>"


def feed(feed_id, title, entries, links, updated=None, extra=""):
    """Assemble one Atom feed document."""
    body = "\n".join(entries)
    joined = "\n".join(links)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<feed {NS}>\n"
        f"  {element('id', feed_id)}\n"
        f"  {element('title', title)}\n"
        f"  {element('updated', updated or _now_rfc3339())}\n"
        "  <author><name>ReaderM</name>"
        "<uri>https://github.com/Compromisee/ReaderM</uri></author>\n"
        f"{joined}\n{extra}\n{body}\n"
        "</feed>\n"
    )


# ------------------------------------------------------------- the library


def _entry_formats(entry):
    """Downloaded files for one series that still exist on disk.

    A library entry records what was *produced*; the file may since have
    been moved or deleted. Offering a link to a missing file gives the
    reader a 404 mid-download, so they are filtered here.
    """
    out = []
    for path in entry.get("outputs") or []:
        try:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                out.append(path)
        except OSError:
            continue
    return out


def _cover_for(entry):
    """A local cover image for this series, or None.

    Prefers a real file on disk over the remote URL the library recorded:
    the remote one may be hotlink-protected, and an OPDS reader sends no
    Referer, so those render as broken images.
    """
    from . import covers as covers_mod

    directory = entry.get("directory")
    if directory and os.path.isdir(directory):
        found = covers_mod.existing_cover(directory)
        if found:
            return found
    # Fall back to a cover sitting beside the first output file.
    for path in _entry_formats(entry):
        found = covers_mod.existing_cover(os.path.dirname(path))
        if found:
            return found
    return None


def library_rows():
    """Every downloaded series with at least one file still present.

    Returns dicts, not raw library entries, so the feed builders and the
    tests share one shape.
    """
    rows = []
    for entry in library.load_library().values():
        formats = _entry_formats(entry)
        if not formats:
            continue
        title = (entry.get("title") or "Untitled").strip()
        rows.append({
            "id": stable_id("series", entry.get("url") or title),
            "title": title,
            "url": entry.get("url") or "",
            "source": entry.get("source") or "",
            "directory": entry.get("directory") or "",
            "files": formats,
            "cover": _cover_for(entry),
            "chapters": len(entry.get("chapters", {}) or {}),
            "pages": sum(c.get("pages", 0)
                         for c in (entry.get("chapters", {}) or {}).values()),
            "updated": _to_rfc3339(entry.get("last_download")
                                   or entry.get("added")),
            "added": _to_rfc3339(entry.get("added")),
            "bytes": sum(_safe_size(p) for p in formats),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows


def _safe_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def group_by_source(rows):
    groups = {}
    for row in rows:
        groups.setdefault(row["source"] or "unknown", []).append(row)
    return groups


def group_by_letter(rows):
    """A-Z shelves. Anything not starting with a letter lands under '#'."""
    groups = {}
    for row in rows:
        first = (row["title"][:1] or "#").upper()
        groups.setdefault(first if first.isalpha() else "#", []).append(row)
    return dict(sorted(groups.items()))


def search_rows(rows, query):
    """Substring match on the title, case-insensitively.

    Deliberately not fuzzy: an OPDS search box is used to find a known book,
    and a fuzzy match that returns forty things is worse than none.
    """
    needle = (query or "").strip().lower()
    if not needle:
        return []
    return [r for r in rows if needle in r["title"].lower()]


# ------------------------------------------------------------ feed builders


def navigation_feed(base, rows):
    """The catalog root: the shelves a reader can browse into."""
    counts = {
        "all": len(rows),
        "recent": min(len(rows), PAGE_SIZE),
        "sources": len(group_by_source(rows)),
        "letters": len(group_by_letter(rows)),
    }
    shelves = [
        ("All titles", "/opds/all", ACQ_TYPE,
         f"Everything you have downloaded ({counts['all']})."),
        ("Recently added", "/opds/recent", ACQ_TYPE,
         "Newest downloads first."),
        ("By source", "/opds/sources", NAV_TYPE,
         f"Grouped by the site it came from ({counts['sources']})."),
        ("Alphabetical", "/opds/letters", NAV_TYPE,
         f"A-Z shelves ({counts['letters']})."),
    ]
    entries = []
    for title, path, type_, blurb in shelves:
        entries.append(
            "  <entry>\n"
            f"    {element('title', title)}\n"
            f"    {element('id', stable_id('nav', path))}\n"
            f"    {element('updated', _now_rfc3339())}\n"
            f"    {element('content', blurb, type='text')}\n"
            f"  {link('subsection', base + path, type_)}\n"
            "  </entry>"
        )
    return feed(
        stable_id("root", base), "ReaderM Library", entries,
        [
            link("self", base + "/opds", NAV_TYPE),
            link("start", base + "/opds", NAV_TYPE),
            link("search", base + "/opds/search.xml", SEARCH_TYPE,
                 title="Search the library"),
        ],
    )


def _facet_links(base, active=None):
    """Facets let a reader re-slice the current shelf without going back.

    Only valid in acquisition feeds -- the spec is explicit, and at least
    one reader refuses the whole feed if they appear in a navigation one.
    """
    out = []
    for label, path in (("All titles", "/opds/all"),
                        ("Recently added", "/opds/recent")):
        extra = {"opds_facetGroup": "Sort"}
        if active == path:
            extra["opds_activeFacet"] = "true"
        out.append(link(REL_FACET, base + path, ACQ_TYPE, title=label,
                        **extra))
    return out


def acquisition_feed(base, rows, title, path, page=0, facets=True):
    """A shelf of books, paginated."""
    total = len(rows)
    start = max(0, page) * PAGE_SIZE
    window = rows[start:start + PAGE_SIZE]

    links = [
        link("self", f"{base}{path}", ACQ_TYPE),
        link("start", base + "/opds", NAV_TYPE),
        link("up", base + "/opds", NAV_TYPE),
        link("search", base + "/opds/search.xml", SEARCH_TYPE),
    ]
    if facets:
        links += _facet_links(base, path)

    # Pagination links, so a reader can page rather than load 2000 entries.
    joiner = "&" if "?" in path else "?"
    if start + PAGE_SIZE < total:
        links.append(link("next", f"{base}{path}{joiner}page={page + 1}",
                          ACQ_TYPE))
    if page > 0:
        links.append(link("previous", f"{base}{path}{joiner}page={page - 1}",
                          ACQ_TYPE))

    extra = (f"  {element('opensearch:totalResults', total)}\n"
             if False else "")
    entries = [publication_entry(base, row) for row in window]
    return feed(stable_id("feed", path), title, entries, links, extra=extra)


def publication_entry(base, row):
    """One book. Must carry at least one acquisition link to be usable."""
    parts = [
        f"    {element('title', row['title'])}",
        f"    {element('id', row['id'])}",
        f"    {element('updated', row['updated'])}",
    ]
    if row["source"]:
        parts.append(f"    <author>{element('name', row['source'])}</author>")

    summary = f"{row['chapters']} chapters"
    if row["pages"]:
        summary += f", {row['pages']} pages"
    if row["bytes"]:
        summary += f" ({_human_size(row['bytes'])})"
    parts.append(f"    {element('summary', summary, type='text')}")
    parts.append(f"    {element('dc:issued', row['added'][:10])}")

    if row["cover"]:
        cover_url = f"{base}/opds/cover/{row['id'].split(':')[-1]}"
        image_type = image_type_for(row["cover"])
        parts.append(f"  {link(REL_IMAGE, cover_url, image_type)}")
        parts.append(f"  {link(REL_THUMB, cover_url + '?thumb=1', image_type)}")

    for index, path in enumerate(row["files"]):
        href = f"{base}/opds/download/{row['id'].split(':')[-1]}/{index}"
        parts.append(
            f"  {link(REL_ACQUISITION, href, media_type_for(path), title=os.path.basename(path), length=_safe_size(path))}"
        )

    return "  <entry>\n" + "\n".join(parts) + "\n  </entry>"


def _human_size(value):
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def opensearch_document(base):
    """Tells the reader how to build a search URL."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OpenSearchDescription '
        'xmlns="http://a9.com/-/spec/opensearch/1.1/">\n'
        "  <ShortName>ReaderM</ShortName>\n"
        "  <Description>Search your downloaded library</Description>\n"
        "  <InputEncoding>UTF-8</InputEncoding>\n"
        f'  <Url type="{ACQ_TYPE}" '
        f'template="{escape(base)}/opds/search?q={{searchTerms}}"/>\n'
        "</OpenSearchDescription>\n"
    )
