"""Shared base for sites running the **Madara WordPress theme**.

.. warning::

   This is **engine code, not a source**. It is not registered and never
   appears in Settings, the CLI ``sources`` list or anywhere else in the UI.

   It is easy to confuse with :mod:`readerm.sources.madarascans`, which is
   *Madara Scans* -- an actual scanlation site you can search and download
   from. The two are unrelated: Madara Scans does not even run this theme.
   (A user reported "Madara doesn't show in settings" for exactly this
   reason; the answer was that the theme engine is not a site, and the site
   they meant had not been added yet.)


Madara ("A powerful manga, novel theme from Mangabooth.com") powers a large
slice of the manhwa/manhua aggregator web. Six of the sources in this package
run it, so the scraping lives here once and each site becomes a ~40 line
subclass that only declares the handful of things that genuinely differ:
the series path prefix, the genre path prefix, and the browse listing path.

This class is **not registered**; only its subclasses are.

Everything below was measured against the live sites in 2026-07 -- Madara is
customised heavily per install, and several "obvious" URL shapes are wrong on
at least one of them.

Search
    ``/?s=<term>&post_type=wp-manga``. Page two is ``&paged=2``.

    Do *not* use ``/page/2/?s=...``: it works on Manhua Plus and Manhua Top
    but silently returns page **one** on Toonily (measured: 18 results, all 18
    identical to page one), so a "next page" would loop forever. ``paged=``
    returned 0 overlap with page one on all five sites tested.

Browse
    ``<browse_path>?m_orderby=<key>``, page two ``<browse_path>page/2/?m_orderby=``.
    Verified 0 overlap between pages on all five sites. Order keys the theme
    accepts: ``latest``, ``alphabet``, ``rating``, ``trending``, ``views``,
    ``new-manga``.

Genres
    The prefix is **not** the same everywhere and the wrong one is a hard 404:

        manhuaplus.com  /manga-genre/<slug>/     (/manhua-genre/ -> 404)
        manhuatop.org   /manhua-genre/<slug>/    (/manga-genre/  -> 404)
        mangaread.org   /genres/<slug>/          (/manga-genre/  -> 404)
        manhwatop.com   /manga-genre/<slug>/
        toonily.com     /webtoon-genre/<slug>/

    Genre slugs are read off the site's own advanced-search form
    (``input[name="genre[]"]``) rather than guessed, because installs rename
    them freely -- Manhwa Top ships ``genre-action-new-genre`` and
    ``adventure-genre-hot``, which no amount of guessing would produce.

Cards
    ``.page-item-detail`` on listings, ``.c-tabs-item__content`` on search
    (some installs use the first shape for both). The title link is
    ``.post-title a`` -- except on Manhua Top, whose child theme drops that
    class entirely and leaves only ``h3 a`` (measured: 0 vs 12 matches). Both
    are tried, in that order.

Chapters
    ``POST <series_url>ajax/chapters/``. The request **must carry a body**,
    even an empty one: with ``Content-Length: 0`` it answers 200 and the full
    list, without it a bare POST answers **400 with zero bytes**. A Referer
    makes no difference. ``/wp-admin/admin-ajax.php`` with
    ``action=manga_get_chapters`` -- the older Madara route -- answers 400 on
    every site tested, so it is not used.

    Series pages render the list server-side too on some installs, so the
    embedded ``li.wp-manga-chapter`` is used as a fallback.

Images
    ``.reading-content img``, lazy-loaded through ``data-src``.
"""

import logging
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from .base import ScrapeError, Source, classify_type

logger = logging.getLogger(__name__)


class MadaraSource(Source):
    """Scraper for the Madara WordPress **theme**. Subclass; never register.

    Not a site. See the module docstring for why this is worth saying twice.
    """

    @classmethod
    def is_engine(cls):
        """True for this class only, not for the sites that subclass it.

        A plain class attribute would inherit, so every Madara-based site
        would claim to be engine code. Comparing the class identity keeps the
        answer correct for subclasses.
        """
        return cls is MadaraSource

    # -- per-site knobs -------------------------------------------------
    #: Path that series live under, e.g. "/manga/" or "/serie/".
    series_prefix = "/manga/"
    #: Genre archive prefix, without slashes, e.g. "manga-genre".
    genre_prefix = "manga-genre"
    #: Listing path used for browsing, e.g. "/manga/" or "/search/".
    browse_path = "/manga/"
    #: Fallback genre slugs, used when the live form cannot be read.
    GENRES = ()

    supports_search = True
    supports_browse = True
    supports_genres = True

    search_sorts = ("Best Match",)
    browse_sorts = ("Trending", "Popularity", "Latest Updates", "Rating",
                    "Title", "New")

    #: UI sort label -> the theme's ``m_orderby`` value.
    _ORDER = {
        "Trending": "trending",
        "Popularity": "views",
        "Latest Updates": "latest",
        "Rating": "rating",
        "Title": "alphabet",
        "New": "new-manga",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._genre_cache = None

    # ---------------------------------------------------------- helpers

    def _page_url(self, base: str, page: int, query: str = "") -> str:
        """Madara paginates listings with a /page/N/ path segment."""
        page = max(1, int(page or 1))
        url = base if page == 1 else f"{base.rstrip('/')}/page/{page}/"
        return f"{url}?{query}" if query else url

    def _cards(self, soup, limit):
        """Parse a Madara result grid into search results."""
        blocks = soup.select(".page-item-detail") or \
            soup.select(".c-tabs-item__content")
        results, seen = [], set()

        for card in blocks:
            # .post-title is absent on Manhua Top's child theme; h3 a is the
            # only link there, so both shapes are tried.
            link = (card.select_one(".post-title a")
                    or card.select_one("h3 a")
                    or card.select_one(".item-title a"))
            if link is None or not link.get("href"):
                continue
            href = urljoin(self.base_url, link["href"])
            if href in seen:
                continue

            title = (link.get("title") or "").strip()
            if not title:
                title = link.get_text(" ", strip=True)
            # Listing badges ("HOT", "NEW") are rendered inside the heading,
            # not the anchor, but a couple of installs put them inside it.
            title = re.sub(r"^(HOT|NEW|UP)\s*(?=[A-Z0-9])", "", title).strip()
            if not title:
                continue

            cover = None
            img = card.select_one("img")
            if img is not None:
                cover = (img.get("data-src") or img.get("src") or "").strip()
                # the theme ships a transparent placeholder for lazy images
                if cover and "dflazy" in cover:
                    cover = (img.get("data-srcset") or "").split(" ")[0].strip()
                if cover:
                    cover = urljoin(self.base_url, cover)

            latest = None
            chapter = card.select_one(".chapter-item a, .list-chapter a")
            if chapter is not None:
                latest = chapter.get_text(" ", strip=True) or None

            seen.add(href)
            results.append(self._result(
                title, href, cover=cover,
                latest=latest,
                series_type=self.default_series_type,
            ))
            if len(results) >= limit:
                break
        return results

    # ----------------------------------------------------------- search

    def search(self, query: str, limit: int = 32, page: int = 1, **_):
        query = (query or "").strip()
        if not query:
            return self.browse(limit=limit, page=page)

        page = max(1, int(page or 1))
        # &paged=N, never /page/N/ -- see the module docstring.
        url = f"{self.base_url}/?s={quote(query)}&post_type=wp-manga"
        if page > 1:
            url += f"&paged={page}"
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("%s search failed: %s", self.id, e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def browse(self, sort: str = "Trending", genre: str = None,
               page: int = 1, limit: int = 32, **_):
        order = self._ORDER.get(sort or "", "trending")
        if genre:
            slug = self.genre_slug(genre)
            if slug is None:
                # This install does not carry the genre. Returning nothing is
                # right; guessing a slug would 404 and, before the base class
                # learned to fail fast on 404, cost 30s of retries.
                return []
            base = f"{self.base_url}/{self.genre_prefix}/{quote(slug)}/"
            url = self._page_url(base, page)
        else:
            url = self._page_url(f"{self.base_url}{self.browse_path}",
                                 page, f"m_orderby={order}")
        try:
            response = self.fetch(url)
        except ScrapeError as e:
            logger.error("%s browse failed: %s", self.id, e)
            return []
        return self._cards(BeautifulSoup(response.content, "html.parser"), limit)

    def genres(self) -> list:
        """Read the genre slugs off the site's own advanced-search form.

        Falls back to the hardcoded list when the site is unreachable, so a
        dead site degrades to "fewer genres" rather than an empty picker.
        """
        if self._genre_cache is not None:
            return self._genre_cache

        slugs = []
        try:
            response = self.fetch(f"{self.base_url}/?s=&post_type=wp-manga",
                                  max_retries=2)
            soup = BeautifulSoup(response.content, "html.parser")
            for box in soup.select('input[name="genre[]"]'):
                value = (box.get("value") or "").strip()
                if value and value not in slugs:
                    slugs.append(value)
        except Exception as e:      # network, parse, anything
            logger.debug("%s genre discovery failed: %s", self.id, e)

        if not slugs:
            slugs = list(self.GENRES)
        self._genre_cache = [{"id": s, "name": self._genre_label(s)}
                             for s in slugs]
        return self._genre_cache

    @classmethod
    def genre_slug(cls, genre):
        """Map a genre *name* to this install's own slug, or ``None``.

        Necessary because the same genre is spelled differently per install:
        "Action" is ``action`` on most Madara sites and
        ``genre-action-new-genre`` on Manhwa Top. The aggregate source hands
        every member a display name, so each has to translate it back.

        Returns ``None`` when the site does not offer the genre at all, which
        the caller must treat as "no results here" rather than guessing.
        """
        wanted = str(genre or "").strip().lower()
        if not wanted:
            return None
        for slug in cls.GENRES:
            if wanted == slug.lower():
                return slug
            if wanted == cls._genre_label(slug).lower():
                return slug
        # Not in the declared list: fall back to slugifying, so a genre read
        # live off the site (which genres() prefers) still works.
        return wanted.replace(" ", "-") if cls.GENRES else \
            wanted.replace(" ", "-")

    @staticmethod
    def _genre_label(slug: str) -> str:
        """Human label for a slug, undoing the SEO noise some installs add."""
        text = slug.replace("-", " ")
        # manhwatop ships "genre-action-new-genre", "adventure-genre-hot", ...
        text = re.sub(r"\b(new|hot|genres?)\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text.title() or slug

    # ------------------------------------------------------------- info

    def get_manga_info(self, manga_url: str) -> dict:
        manga_url = self.normalize_url(manga_url)
        response = self.fetch(manga_url)
        soup = BeautifulSoup(response.content, "html.parser")

        heading = soup.select_one(".post-title h1, .post-title h3, h1")
        title = heading.get_text(" ", strip=True) if heading else "Unknown"

        cover = None
        img = soup.select_one(".summary_image img, .tab-summary img")
        if img is not None:
            cover = (img.get("data-src") or img.get("src") or "").strip()
            if cover:
                cover = urljoin(self.base_url, cover)

        description = None
        block = soup.select_one(".description-summary .summary__content, "
                                ".description-summary, .summary__content, "
                                ".manga-excerpt")
        if block is not None:
            description = re.sub(r"\s+", " ",
                                 block.get_text(" ", strip=True)) or None

        tags = [a.get_text(strip=True) for a in soup.select(".genres-content a")
                if a.get_text(strip=True)]
        authors = [a.get_text(strip=True) for a in soup.select(".author-content a")
                   if a.get_text(strip=True)]
        artists = [a.get_text(strip=True) for a in soup.select(".artist-content a")
                   if a.get_text(strip=True)]

        fields = {}
        for row in soup.select(".post-content_item"):
            key = row.select_one(".summary-heading")
            value = row.select_one(".summary-content")
            if key is not None and value is not None:
                fields[key.get_text(strip=True).rstrip(":").lower()] = \
                    value.get_text(" ", strip=True)

        # .post-status holds Release then Status, in that order.
        status = None
        statuses = [x.get_text(" ", strip=True)
                    for x in soup.select(".post-status .summary-content")]
        for candidate in reversed(statuses):
            if re.fullmatch(r"(on\s*going|ongoing|completed|canceled|"
                            r"cancelled|on hold|hiatus|dropped)", candidate,
                            re.I):
                status = "Ongoing" if candidate.lower().replace(" ", "") \
                    == "ongoing" else candidate.title()
                break

        year = None
        match = re.search(r"\b(19|20)\d{2}\b", " ".join(statuses))
        if match:
            year = int(match.group(0))

        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": description,
            "tags": tags[:20],
            "status": status,
            "year": year,
            "authors": authors[:5],
            "artists": artists[:5],
            "alt_titles": [t for t in [fields.get("alternative"),
                                       fields.get("alt name(s)")] if t],
            "series_type": classify_type(tags=tags,
                                         text=fields.get("type"))
            or self.default_series_type,
            "source": self.id,
            "source_name": self.name,
        }

    # --------------------------------------------------------- chapters

    def get_chapters(self, manga_url: str) -> list:
        manga_url = self.normalize_url(manga_url)
        soup = self._chapter_soup(manga_url)

        chapters, seen = [], set()
        for item in soup.select("li.wp-manga-chapter"):
            link = item.select_one("a[href]")
            if link is None:
                continue
            href = urljoin(self.base_url, link["href"])
            if href in seen:
                continue
            name = link.get_text(" ", strip=True)
            if not name:
                name = href.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()
            seen.add(href)
            chapters.append({
                "url": href,
                "name": name,
                # Some page CDNs (Toonily's data.tnlycdn.com) answer 403
                # without a Referer; the engine forwards this to every image.
                "referer": manga_url,
                "locked": bool(item.select_one(".premium-block, .c-btn-premium")),
                "source": self.id,
            })

        # Madara renders newest first.
        chapters.reverse()
        return chapters

    def _chapter_soup(self, manga_url: str):
        """Chapter markup, from the AJAX route with the page as a fallback."""
        ajax = manga_url.rstrip("/") + "/ajax/chapters/"
        try:
            # An empty *body* is required: a bare POST answers 400 with zero
            # bytes, the same POST with Content-Length: 0 answers 200.
            response = self.session.post(
                ajax, data=b"", timeout=25,
                headers={"X-Requested-With": "XMLHttpRequest",
                         "Referer": manga_url},
            )
            if response.status_code == 200 and response.content:
                soup = BeautifulSoup(response.content, "html.parser")
                if soup.select("li.wp-manga-chapter"):
                    return soup
        except Exception as e:
            logger.debug("%s ajax chapters failed: %s", self.id, e)

        return BeautifulSoup(self.fetch(manga_url).content, "html.parser")

    # ----------------------------------------------------------- images

    def get_chapter_images(self, chapter) -> list:
        chapter_url = self.normalize_url(self._chapter_url(chapter))
        response = self.fetch(chapter_url)
        soup = BeautifulSoup(response.content, "html.parser")

        images = []
        for img in soup.select(".reading-content img, .read-container img"):
            src = (img.get("data-src") or img.get("src") or "").strip()
            if not src:
                continue
            src = urljoin(self.base_url, src)
            if src not in images:
                images.append(src)
        return images
