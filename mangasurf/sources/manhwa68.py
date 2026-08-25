"""Manhwa68 (manhwa68.com) source scraper for Mangasurf.

Runs the Madara WordPress theme, so it reuses the shared
:class:`mangasurf.sources.madara.MadaraSource` engine. Only the handful of
things that genuinely differ per install are declared here. Verified live
(2026-08) against manhwa68.com:
- search ``?s=<q>&post_type=wp-manga`` -> ``.page-item-detail`` cards
- browse ``/manga/?m_orderby=latest`` -> 12 ``.page-item-detail`` cards
- genres ``/manga-genre/<slug>/``
- chapters are server-rendered in ``li.wp-manga-chapter`` (no AJAX needed)
- pages come from ``.reading-content img[data-src]`` on ``cdn.manhwa68.com``
"""

import logging

from .madara import MadaraSource

logger = logging.getLogger(__name__)

SITE = "https://manhwa68.com"


class Manhwa68Source(MadaraSource):
    id = "manhwa68"
    name = "Manhwa68"
    base_url = SITE
    domains = ("manhwa68.com", "cdn.manhwa68.com")
    default_series_type = None

    series_prefix = "/manga/"
    genre_prefix = "manga-genre"
    browse_path = "/manga/"

    GENRES = (
        "action", "adult", "adventure", "comedy", "cooking", "drama", "ecchi",
        "fantasy", "gender-bender", "harem", "historical", "horror", "isekai",
        "josei", "magic", "manhua", "manhwa", "martial-arts", "mature", "mecha",
        "military", "mystery", "one-shot", "psychological", "reincarnation",
        "romance", "school-life", "sci-fi", "seinen", "shoujo", "shounen",
        "slice-of-life", "smut", "sports", "supernatural", "thriller", "tragedy",
        "webtoon", "yaoi", "yuri",
    )
