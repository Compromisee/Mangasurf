"""Regression tests for v1.4.18.

* the ten Madara-theme sites became **one** source, ``madaranet``
* the dedupe key was rewritten: it destroyed every CJK title and merged
  unrelated series, while missing obvious duplicates
* 404/410 stopped being retried
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ======================================================== the aggregate


def test_madaranet_is_the_only_madara_entry():
    """Ten sites, one row in Settings."""
    from mangasurf.sources import SOURCES
    from mangasurf.sources.madaranet import MEMBERS

    assert "madaranet" in SOURCES
    assert len(MEMBERS) == 10
    # None of the members may be registered in their own right.
    for cls in MEMBERS:
        assert cls.id not in SOURCES, cls.id
    # ...and the old standalone ids are gone.
    for gone in ("toonily", "manhuaplus", "manhuatop", "manhwatop",
                 "mangaread", "setsuscans"):
        assert gone not in SOURCES, gone


def test_aggregate_id_is_not_the_engine_name():
    """Calling it "madara" would collide with the theme engine in madara.py --
    the exact confusion v1.4.17 had to untangle."""
    from mangasurf.sources import SOURCES
    from mangasurf.sources.madaranet import MadaraNetSource

    assert MadaraNetSource.id == "madaranet"
    assert "madara" not in SOURCES


def test_aggregate_claims_every_member_domain():
    """Pasting any member's URL has to resolve to the aggregate."""
    from mangasurf.sources import detect_source
    from mangasurf.sources.madaranet import MEMBERS

    for cls in MEMBERS:
        for domain in cls.domains:
            assert detect_source(f"https://{domain}/x/") == "madaranet", domain


def test_member_ids_are_namespaced_and_unique():
    from mangasurf.sources.madaranet import MEMBERS

    ids = [cls.id for cls in MEMBERS]
    assert len(ids) == len(set(ids))
    for member_id in ids:
        assert member_id.startswith("madara."), member_id


def test_member_lookup_by_url():
    from mangasurf.sources import get_source

    source = get_source("madaranet")
    try:
        member = source.member_for_url("https://toonily.com/serie/x/")
        assert member is not None
        assert member.id == "madara.toonily"
        assert source.member_for_url("https://example.com/x/") is None
    finally:
        source.close()


def test_delegation_raises_a_useful_error_for_a_foreign_url():
    from mangasurf.sources import get_source
    from mangasurf.sources.base import ScrapeError

    source = get_source("madaranet")
    try:
        with pytest.raises(ScrapeError) as excinfo:
            source.get_chapters("https://example.com/nope/")
        assert "No Madara site recognises" in str(excinfo.value)
    finally:
        source.close()


def test_genre_names_map_back_to_each_installs_own_slug():
    """"Action" is `action` on most installs and `genre-action-new-genre` on
    Manhwa Top. Passing the display name straight through 404s -- measured at
    31.0s of retries before the fail-fast fix."""
    from mangasurf.sources.madaranet import _ManhwaTop, _Toonily

    assert _ManhwaTop.genre_slug("Action") == "genre-action-new-genre"
    assert _ManhwaTop.genre_slug("Romance") == "romance-genre-hot"
    assert _Toonily.genre_slug("Action") == "action"
    # A slug that is already correct must pass through unchanged.
    assert _Toonily.genre_slug("action") == "action"


def test_aggregate_genres_are_display_names_not_slugs():
    """Members translate names back themselves, so the aggregate must not
    leak one install's slug to the others."""
    from mangasurf.sources import get_source

    source = get_source("madaranet")
    try:
        names = [g["name"] for g in source.genres()]
    finally:
        source.close()

    assert "Action" in names
    assert not any("-genre" in n for n in names), \
        [n for n in names if "-genre" in n]


def test_aggregate_offline_genres_need_no_network():
    """genres_all() falls back to this when a source times out; an aggregate
    has no GENRES attribute, so it publishes the hook instead."""
    from mangasurf.sources import _offline_genres

    rows = _offline_genres("madaranet")
    assert rows
    assert any(r["name"] == "Action" for r in rows)


def test_aggregate_is_not_flagged_cloudflare():
    """Only one member needs a solver; flagging the whole source would imply
    none of it works without FlareSolverr, which is false."""
    from mangasurf.sources import SOURCES
    from mangasurf.sources.madaranet import _SetsuScans

    assert SOURCES["madaranet"].needs_flaresolverr is False
    assert _SetsuScans.needs_flaresolverr is True


def test_rejected_members_are_documented_not_shipped():
    """Two candidates were tested and left out; the reasons must be recorded
    so nobody re-adds them."""
    from mangasurf.sources.madaranet import MEMBERS

    hosts = {d for cls in MEMBERS for d in cls.domains}
    assert not any("manhwafull" in h for h in hosts)
    assert not any("zinmanga" in h for h in hosts)

    doc = read(os.path.join(ROOT, "readerm", "sources", "madaranet.py"))
    assert "manhwafull" in doc and "zinmanga" in doc


def test_members_keep_their_measured_quirks():
    """Folding the sites into one source must not lose the per-install
    findings from v1.4.15."""
    from mangasurf.sources.madaranet import (_MangaGG, _MangaOwl, _MangaRead,
                                           _ManhuaTop, _Toonily)

    assert _ManhuaTop.series_prefix == "/manhua/"
    assert _ManhuaTop.browse_path == "/manga/"      # /manhua/ returns 0 cards
    assert _Toonily.series_prefix == "/serie/"
    assert _MangaRead.genre_prefix == "genres"      # /manga-genre/ is a 404
    assert _MangaOwl.series_prefix == "/read-1/"    # /manga/ answers 410
    assert _MangaGG.genre_prefix == "genre"         # singular here


# ================================================ 404 is not retried


def test_fetch_does_not_retry_a_404():
    """A 404/410 is definitive. Retrying it five times with exponential
    backoff cost 31.0s (Manhwa Top) and 36.4s (MangaOwl, which answers 410),
    dragging a genre browse to 25.0s. After: 1.4s."""
    import time

    from mangasurf.sources.base import ScrapeError
    from mangasurf.sources.witchscans import WitchScansSource

    class Missing:
        status_code = 404
        text = ""
        content = b""
        headers = {}
        request = None

        def raise_for_status(self):
            raise AssertionError("should not reach raise_for_status")

    source = WitchScansSource()
    calls = []
    source.session.get = lambda url, **kw: (calls.append(url), Missing())[1]
    try:
        started = time.time()
        with pytest.raises(ScrapeError):
            source.fetch("https://witchscans.com/nope/", max_retries=5)
        elapsed = time.time() - started
    finally:
        source.close()

    assert len(calls) == 1, f"retried {len(calls)} times"
    assert elapsed < 2, elapsed


def test_a_500_is_still_retried():
    """Only 404/410 are definitive; a server error may well be transient."""
    from mangasurf.sources.base import ScrapeError
    from mangasurf.sources.witchscans import WitchScansSource

    import requests

    class Broken:
        status_code = 500
        text = ""
        content = b""
        headers = {}
        request = None

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("500")

    source = WitchScansSource()
    calls = []
    source.session.get = lambda url, **kw: (calls.append(url), Broken())[1]
    source._backoff = lambda *a, **k: 0.0        # keep the test quick
    try:
        with pytest.raises(ScrapeError):
            source.fetch("https://witchscans.com/x/", max_retries=3)
    finally:
        source.close()
    assert len(calls) == 3, calls


# ==================================================== dedupe rewritten


def test_cjk_titles_are_not_destroyed():
    """The old key ended with [^a-z0-9]+ -> " ", which deletes every
    non-ASCII character, so EVERY CJK title normalised to "" and they all
    landed in one group. Measured live: a search for ワンピース merged three
    unrelated doujinshi into one row and silently dropped two."""
    from mangasurf.features import _normalise_title

    for title in ("ワンピース", "나 혼자만 레벨업", "进击的巨人"):
        assert _normalise_title(title), title
    assert _normalise_title("ワンピース") != _normalise_title("进击的巨人")


def test_distinct_cjk_series_are_not_merged():
    from readerm import features

    rows = [{"title": "ワンピース", "url": "a", "source": "x"},
            {"title": "進撃の巨人", "url": "b", "source": "y"},
            {"title": "나 혼자만 레벨업", "url": "c", "source": "z"}]
    assert len(features.dedupe(rows)) == 3


def test_untitled_rows_are_not_lumped_together():
    """"(Oneshot)" and "[Artist]" both normalised to "" and merged."""
    from readerm import features

    rows = [{"title": "(Oneshot)", "url": "a", "source": "x"},
            {"title": "[Artist]", "url": "b", "source": "y"},
            {"title": "", "url": "c", "source": "z"}]
    assert len(features.dedupe(rows)) == 3


def test_editions_of_the_same_work_still_merge():
    from mangasurf.features import _normalise_title as key

    assert key("Berserk") == key("Berserk (Official Colored)")
    assert key("Naruto") == key("Naruto (Digital Colored Comics)")
    assert key("Bleach") == key("Bleach [Fan Colored]")


def test_different_works_are_kept_apart():
    """Stripping every parenthetical merged genuinely different series."""
    from mangasurf.features import _normalise_title as key

    assert key("Solo Leveling") != key("Solo Leveling (Pre-serialization)")
    assert key("Tower of God") != key("Tower of God (Season 2)")


def test_word_break_variants_merge():
    """Reported as "it merges too little"."""
    from readerm import features

    rows = [{"title": "Nano Machine", "url": "a", "source": "x"},
            {"title": "Nanomachine", "url": "b", "source": "y"}]
    merged = features.dedupe(rows)
    assert len(merged) == 1
    assert len(merged[0]["also_on"]) == 1


def test_leading_article_is_ignored():
    from mangasurf.features import _normalise_title as key

    assert key("The Beginning After The End") == key("Beginning After the End")


def test_a_title_that_is_only_stopwords_survives():
    """Dropping stopwords must never empty a title outright."""
    from mangasurf.features import _normalise_title as key

    assert key("The End")
    assert key("A")


def test_short_keys_are_never_grouped():
    """A one- or two-character key is too weak to merge on."""
    from readerm import features

    rows = [{"title": "X", "url": "a", "source": "p"},
            {"title": "Y", "url": "b", "source": "q"},
            {"title": "II", "url": "c", "source": "r"}]
    assert len(features.dedupe(rows)) == 3


def test_merge_backfills_missing_metadata():
    """The best-ranked copy is not always the most complete: MangaDex often
    wins on rank while reporting no chapter count, and the copy it displaced
    had both a count and a cover."""
    from readerm import features

    rows = [{"title": "Solo Leveling", "url": "a", "source": "mangadex",
             "cover": None, "chapters": None},
            {"title": "Solo Leveling", "url": "b", "source": "asurascans",
             "cover": "c.jpg", "chapters": 200}]
    best = features.dedupe(rows, {"mangadex": 0, "asurascans": 1})[0]

    assert best["source"] == "mangadex"      # rank still decides the winner
    assert best["cover"] == "c.jpg"          # ...but the data is kept
    assert best["chapters"] == 200


def test_backfill_never_overwrites_the_winners_own_data():
    from readerm import features

    rows = [{"title": "X Series", "url": "a", "source": "one",
             "cover": "good.jpg"},
            {"title": "X Series", "url": "b", "source": "two",
             "cover": "worse.jpg"}]
    best = features.dedupe(rows, {"one": 0, "two": 1})[0]
    assert best["cover"] == "good.jpg"


def test_dedupe_preserves_every_row_it_does_not_merge():
    """Nothing may vanish: total in == total across all groups out."""
    from readerm import features

    rows = [{"title": t, "url": str(i), "source": "s"}
            for i, t in enumerate(["ワンピース", "One Piece", "(Oneshot)",
                                   "Nano Machine", "Nanomachine", "",
                                   "Solo Leveling", "Solo Leveling"])]
    groups = features.group_duplicates(rows)
    assert sum(len(g) for g in groups) == len(rows)
