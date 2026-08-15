"""Regression tests for v1.4.20 -- the CBZ cover rebuilder.

The tool walks a folder tree, recovers a series title from each ``.cbz``
filename, offers covers from every source, and writes the chosen one as
``cover.jpg`` **beside that archive**.

Two rules carry the risk, and both are tested hard here:

* a folder holding several different series is split so each cover lands in
  the right place -- and a folder that is already tidy is never touched;
* titles must survive every naming convention, ReaderM's own included, or
  the search matches nothing.
"""

import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def make(tmp_path, *relative):
    """Create empty files at the given relative paths."""
    for item in relative:
        path = tmp_path / item
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x")
    return str(tmp_path)


# ======================================================== title recovery


@pytest.mark.parametrize("filename,expected", [
    # ReaderM's own output -- these are the shapes downloader.py produces
    ("Afterlife Diner - Chapters 001.cbz", "Afterlife Diner"),
    ("Afterlife Diner - Chapters 001-050.cbz", "Afterlife Diner"),
    ("Afterlife Diner - Chapters 001-003, 007-008, 020.cbz", "Afterlife Diner"),
    ("Afterlife Diner - Chapter 005.cbz", "Afterlife Diner"),
    ("Martial God Chat Group - Chapters 001-027.cbz", "Martial God Chat Group"),
    # third-party conventions
    ("[Group] Solo Leveling - c045 (2024) [1080p].cbz", "Solo Leveling"),
    ("Solo Leveling v03.cbz", "Solo Leveling"),
    ("One Piece Ch. 1050.cbz", "One Piece"),
    ("Berserk #12.cbz", "Berserk"),
    ("Nano.Machine.Chapter.5.cbz", "Nano Machine"),
    ("Tower of God - 005.cbz", "Tower of God"),
    ("The Beginning After The End Vol 3.cbz", "The Beginning After The End"),
    ("Eleceed - Episode 200.cbz", "Eleceed"),
    ("Omniscient Reader [Official Colored] c001-c010.cbz", "Omniscient Reader"),
    # a number that is part of the title, not an index
    ("Series 2 - Chapters 001.cbz", "Series 2"),
    ("Kingdom 2.cbz", "Kingdom 2"),
    # non-latin titles must survive intact
    ("\u30ef\u30f3\u30d4\u30fc\u30b9 - Chapters 001.cbz", "\u30ef\u30f3\u30d4\u30fc\u30b9"),
])
def test_clean_title(filename, expected):
    from readerm.covers import clean_title

    assert clean_title(filename) == expected


def test_clean_title_never_returns_empty():
    """A title stripped to "" would search for nothing and match everything,
    so the least-stripped form is kept instead."""
    from readerm.covers import clean_title

    for name in ("Chapter 5.cbz", "v03.cbz", "[Group].cbz", "001.cbz"):
        assert clean_title(name), name


def test_clean_title_handles_junk():
    from readerm.covers import clean_title

    assert clean_title("") == ""
    assert clean_title(None) == ""


def test_series_key_groups_case_and_punctuation_variants():
    from readerm.covers import series_key

    assert series_key("Solo Leveling - Chapter 1.cbz") == \
        series_key("solo.leveling.c002.cbz")
    assert series_key("Nano Machine v1.cbz") != series_key("One Piece v1.cbz")


# ============================================================== scanning


def test_scan_finds_archives_recursively(tmp_path):
    from readerm.covers import scan

    root = make(tmp_path,
                "A/Series One - Chapters 001.cbz",
                "B/deep/nested/Series Two - Chapter 003.cbz")
    titles = {g["title"] for g in scan(root)}
    assert titles == {"Series One", "Series Two"}


def test_a_tidy_folder_is_never_reorganised(tmp_path):
    """One series alone in its folder must be left exactly where it is."""
    from readerm.covers import scan

    root = make(tmp_path,
                "Afterlife Diner/Afterlife Diner - Chapters 001.cbz",
                "Afterlife Diner/Afterlife Diner - Chapters 002.cbz")
    groups = scan(root)
    assert len(groups) == 1
    assert groups[0]["needs_move"] is False
    assert groups[0]["target_dir"] == groups[0]["directory"]


def test_mixed_folder_gives_each_series_its_own_target(tmp_path):
    """Several series loose in one folder: a single cover.jpg there would be
    wrong for all but one of them."""
    from readerm.covers import scan

    root = make(tmp_path,
                "Mixed/Solo Leveling - Chapters 001-010.cbz",
                "Mixed/Solo Leveling - Chapters 011-020.cbz",
                "Mixed/Nano Machine - Chapter 005.cbz",
                "Mixed/[Grp] Tower of God v03 (2024).cbz")
    groups = {g["title"]: g for g in scan(root)}

    assert set(groups) == {"Solo Leveling", "Nano Machine", "Tower of God"}
    assert all(g["needs_move"] for g in groups.values())
    assert groups["Solo Leveling"]["target_dir"].endswith("Solo Leveling")
    # the two Solo Leveling archives group together
    assert len(groups["Solo Leveling"]["archives"]) == 2


def test_scan_ignores_the_raw_page_folders(tmp_path):
    """The downloader leaves raw/ behind; it holds images, not archives."""
    from readerm.covers import scan

    root = make(tmp_path,
                "Series/Series - Chapters 001.cbz",
                "Series/raw/Chapter 1/001.jpg")
    assert len(scan(root)) == 1


def test_existing_cover_is_detected(tmp_path):
    from readerm.covers import existing_cover, scan

    root = make(tmp_path, "S/S - Chapters 001.cbz", "S/cover.jpg")
    assert existing_cover(os.path.join(root, "S"))
    assert scan(root)[0]["has_cover"] is True


def test_plan_skips_folders_that_already_have_a_cover(tmp_path):
    from readerm.covers import plan

    root = make(tmp_path,
                "Has/Has - Chapters 001.cbz", "Has/cover.jpg",
                "Needs/Needs - Chapters 001.cbz")
    assert [g["title"] for g in plan(root)] == ["Needs"]
    assert len(plan(root, overwrite=True)) == 2


def test_an_empty_cover_file_does_not_count(tmp_path):
    from readerm.covers import existing_cover

    root = make(tmp_path, "S/S - Chapters 001.cbz")
    open(os.path.join(root, "S", "cover.jpg"), "w").close()   # 0 bytes
    assert existing_cover(os.path.join(root, "S")) is None


def test_scan_of_a_missing_root_is_empty_not_an_error():
    from readerm.covers import scan

    assert scan("/no/such/place") == []
    assert scan("") == []


# =============================================================== moving


def test_isolate_moves_only_mixed_groups(tmp_path):
    from readerm.covers import isolate, scan

    root = make(tmp_path,
                "Mixed/Solo Leveling - Chapters 001.cbz",
                "Mixed/Nano Machine - Chapter 005.cbz",
                "Tidy/Tidy - Chapters 001.cbz")
    for group in scan(root):
        isolate(group)

    assert os.path.isfile(os.path.join(
        root, "Mixed", "Solo Leveling", "Solo Leveling - Chapters 001.cbz"))
    assert os.path.isfile(os.path.join(
        root, "Mixed", "Nano Machine", "Nano Machine - Chapter 005.cbz"))
    # the tidy one stayed put
    assert os.path.isfile(os.path.join(root, "Tidy", "Tidy - Chapters 001.cbz"))


def test_isolate_is_idempotent(tmp_path):
    """Running the tool twice must not nest folders inside folders."""
    from readerm.covers import isolate, scan

    root = make(tmp_path,
                "Mixed/A Series - Chapters 001.cbz",
                "Mixed/B Series - Chapters 001.cbz")
    for group in scan(root):
        isolate(group)
    second = scan(root)
    assert all(not g["needs_move"] for g in second)
    for group in second:
        isolate(group)
    assert not os.path.isdir(os.path.join(root, "Mixed", "A Series", "A Series"))


def test_isolate_never_overwrites_an_existing_file(tmp_path):
    from readerm.covers import isolate, scan

    root = make(tmp_path,
                "Mixed/A Series - Chapters 001.cbz",
                "Mixed/B Series - Chapters 001.cbz",
                "Mixed/A Series/A Series - Chapters 001.cbz")
    before = read(os.path.join(root, "Mixed", "A Series",
                               "A Series - Chapters 001.cbz"))
    for group in scan(root):
        if group["needs_move"]:
            isolate(group)
    # the original survives untouched...
    assert read(os.path.join(root, "Mixed", "A Series",
                             "A Series - Chapters 001.cbz")) == before
    # ...and the incoming file was renamed rather than clobbering it
    names = os.listdir(os.path.join(root, "Mixed", "A Series"))
    assert any("(2)" in n for n in names), names


def test_dry_run_moves_nothing(tmp_path):
    from readerm.covers import isolate, scan

    root = make(tmp_path,
                "Mixed/A Series - Chapters 001.cbz",
                "Mixed/B Series - Chapters 001.cbz")
    for group in scan(root):
        isolate(group, dry_run=True)
    assert sorted(os.listdir(os.path.join(root, "Mixed"))) == [
        "A Series - Chapters 001.cbz", "B Series - Chapters 001.cbz"]


# ============================================================== ranking


def test_candidates_rank_exact_titles_first():
    """A fuzzy hit on a big catalogue is usually a different series."""
    from readerm import covers

    rows = [
        {"title": "Something Else", "cover": "c1", "source": "a",
         "source_name": "A", "url": "u1"},
        {"title": "Solo Leveling", "cover": "c2", "source": "b",
         "source_name": "B", "url": "u2"},
        {"title": "Solo Leveling Ragnarok", "cover": "c3", "source": "c",
         "source_name": "C", "url": "u3"},
    ]
    covers.search_all = None            # ensure the stub below is used
    import readerm.sources as sources_module
    original = sources_module.search_all
    sources_module.search_all = lambda *a, **k: rows
    try:
        ranked = covers.candidates("Solo Leveling")
    finally:
        sources_module.search_all = original

    assert ranked[0]["title"] == "Solo Leveling"
    assert ranked[0]["score"] == 100
    assert [r["score"] for r in ranked] == sorted(
        (r["score"] for r in ranked), reverse=True)


def test_candidates_skip_results_with_no_cover():
    from readerm import covers
    import readerm.sources as sources_module

    original = sources_module.search_all
    sources_module.search_all = lambda *a, **k: [
        {"title": "X", "cover": "", "source": "a", "url": "u"},
        {"title": "X", "cover": None, "source": "b", "url": "u"},
    ]
    try:
        assert covers.candidates("X") == []
    finally:
        sources_module.search_all = original


def test_candidates_of_an_empty_title_is_empty():
    from readerm.covers import candidates

    assert candidates("") == []
    assert candidates(None) == []


def test_a_failing_search_does_not_raise():
    from readerm import covers
    import readerm.sources as sources_module

    original = sources_module.search_all

    def boom(*a, **k):
        raise RuntimeError("network down")

    sources_module.search_all = boom
    try:
        assert covers.candidates("X") == []
    finally:
        sources_module.search_all = original


# ============================================================ endpoints


def test_gui_exposes_the_three_endpoints():
    from readerm.gui import Api

    api = Api()
    for name in ("scan_covers", "cover_candidates", "apply_cover"):
        assert callable(getattr(api, name, None)), name


def test_scan_covers_is_read_only(tmp_path):
    from readerm.gui import Api

    root = make(tmp_path,
                "Mixed/A Series - Chapters 001.cbz",
                "Mixed/B Series - Chapters 001.cbz")
    before = sorted(os.listdir(os.path.join(root, "Mixed")))
    result = Api().scan_covers(root)
    assert result["ok"]
    assert len(result["groups"]) == 2
    assert sorted(os.listdir(os.path.join(root, "Mixed"))) == before


def test_apply_cover_refuses_an_empty_choice(tmp_path):
    from readerm.gui import Api

    root = make(tmp_path, "S/S - Chapters 001.cbz")
    result = Api().apply_cover(
        {"directory": os.path.join(root, "S"), "archives": []}, {})
    assert result["ok"] is False
    assert "No cover" in result["error"]


def test_apply_cover_refuses_a_group_with_no_folder():
    from readerm.gui import Api

    result = Api().apply_cover({}, {"cover": "https://example.com/c.jpg"})
    assert result["ok"] is False


def test_aggregate_member_ids_resolve_for_proxying():
    """Members like "madara.toonily" are real sources but not in the
    registry. Without a lookup for them, proxying their covers failed with
    "Unknown source" and 3 of 15 thumbnails rendered blank."""
    from readerm.gui import Api

    source = Api()._source("madara.toonily")
    assert source is not None
    assert "toonily.com" in " ".join(source.domains)


def test_every_preview_is_proxied_not_just_referer_gated_ones():
    """The embedded browser blocks cross-origin images
    (ERR_BLOCKED_BY_RESPONSE.NotSameOrigin). Picking a cover you cannot see
    is not a choice."""
    source = read(os.path.join(ROOT, "readerm", "gui", "__init__.py"))
    body = source[source.index("def _cover_preview"):]
    body = body[:body.index("def apply_cover")]
    assert "proxy_cover" in body
    assert "cover_needs_referer" not in body, \
        "previews must not be limited to Referer-gated sources"


# ================================================================== UI


# ================================ v1.4.21: folder choice, Ch. names, bulk sort


@pytest.mark.parametrize("filename,expected", [
    # the exact shape asked about, and its near neighbours
    ("Close Family Ch.001-036.cbz", "Close Family"),
    ("Close Family Ch. 001-036.cbz", "Close Family"),
    ("Close Family Ch001-036.cbz", "Close Family"),
    ("Close Family Chs.001-036.cbz", "Close Family"),
    ("Close Family Chapt. 5.cbz", "Close Family"),
    ("Close Family Cap.12.cbz", "Close Family"),
    ("Close Family Capitulo 12.cbz", "Close Family"),
    ("Close Family Ch.001~036.cbz", "Close Family"),
])
def test_ch_dot_range_titles(filename, expected):
    from readerm.covers import clean_title

    assert clean_title(filename) == expected


@pytest.mark.parametrize("filename,expected", [
    # Titles that start with, or contain, a chapter-marker word. The marker
    # only counts when a number follows it, so these must survive whole.
    ("Chainsaw Man Ch.100.cbz", "Chainsaw Man"),
    ("Cheese in the Trap Ch.5.cbz", "Cheese in the Trap"),
    ("Children of the Whales Ch.1.cbz", "Children of the Whales"),
    ("Case Closed Ch.1000.cbz", "Case Closed"),
    ("Cells at Work Ch.10.cbz", "Cells at Work"),
    ("Chi's Sweet Home Ch.2.cbz", "Chi's Sweet Home"),
    ("Eden's Zero Ch.100.cbz", "Eden's Zero"),
    ("Ex-Arm Ch.3.cbz", "Ex-Arm"),
    ("E-Rank Healer Ch.9.cbz", "E-Rank Healer"),
    ("Eleceed Ch.200.cbz", "Eleceed"),
])
def test_chapter_marker_does_not_eat_real_words(filename, expected):
    from readerm.covers import clean_title

    assert clean_title(filename) == expected


def test_longest_marker_spelling_wins():
    """Alternation order matters: with "ch" tried before "chs", the "s" is
    left behind and the title becomes "Close Family Chs 001"."""
    from readerm.covers import _CHAPTER_TAIL

    pattern = _CHAPTER_TAIL.pattern
    assert pattern.index("chapters?") < pattern.index("|ch|")
    assert pattern.index("chs") < pattern.index("|ch|")


def test_a_flat_folder_of_loose_archives_splits_by_title(tmp_path):
    """The "300 CBZs in one directory" case: every archive gets a folder
    named after its series, and multi-volume sets group together."""
    from readerm.covers import scan

    root = make(tmp_path,
                "Close Family Ch.001-036.cbz",
                "Close Family Ch.037-072.cbz",
                "Solo Leveling Ch.001-050.cbz",
                "Eleceed Ch.200.cbz")
    groups = {g["title"]: g for g in scan(root)}

    assert set(groups) == {"Close Family", "Solo Leveling", "Eleceed"}
    assert len(groups["Close Family"]["archives"]) == 2
    assert all(g["needs_move"] for g in groups.values())


def test_organise_covers_sorts_without_downloading(tmp_path):
    """Sorting must not require a network call -- it is a filesystem job."""
    import readerm.sources as sources_module
    from readerm.gui import Api

    root = make(tmp_path,
                "Close Family Ch.001-036.cbz",
                "Close Family Ch.037-072.cbz",
                "Solo Leveling Ch.001-050.cbz")

    original = sources_module.search_all

    def boom(*a, **k):
        raise AssertionError("organise must not search for covers")

    sources_module.search_all = boom
    try:
        result = Api().organise_covers(root)
    finally:
        sources_module.search_all = original

    assert result["ok"] is True
    assert result["folders"] == 2
    assert result["moved"] == 3
    assert os.path.isfile(os.path.join(
        root, "Close Family", "Close Family Ch.001-036.cbz"))
    assert os.path.isfile(os.path.join(
        root, "Solo Leveling", "Solo Leveling Ch.001-050.cbz"))


def test_organise_covers_leaves_tidy_folders_alone(tmp_path):
    from readerm.gui import Api

    root = make(tmp_path, "Series/Series Ch.001.cbz")
    result = Api().organise_covers(root)
    assert result["moved"] == 0
    assert os.path.isfile(os.path.join(root, "Series", "Series Ch.001.cbz"))


def test_organise_covers_is_idempotent(tmp_path):
    from readerm.gui import Api

    root = make(tmp_path, "A Series Ch.001.cbz", "B Series Ch.001.cbz")
    Api().organise_covers(root)
    second = Api().organise_covers(root)
    assert second["moved"] == 0
    assert not os.path.isdir(os.path.join(root, "A Series", "A Series"))


def test_scan_covers_honours_an_explicit_root(tmp_path):
    """The tool must scan the folder you choose, not only the configured
    downloads directory."""
    from readerm.gui import Api

    chosen = make(tmp_path / "elsewhere", "Picked Ch.001.cbz")
    result = Api().scan_covers(chosen)
    assert result["ok"]
    assert result["root"] == chosen
    assert [g["title"] for g in result["groups"]] == ["Picked"]


def test_cli_has_dedicated_cover_flags():
    """Overloading --sort broke: it has a fixed choice list, so
    "--sort folders" was rejected by argparse before the command ran."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "readerm.cli", "--help"],
        capture_output=True, text=True, cwd=ROOT, timeout=180)
    for flag in ("--dry-run", "--sort-only", "--replace"):
        assert flag in result.stdout, flag


# ============================================ v1.4.22: smart search auto-pick


def _rows(*specs):
    """Build candidate rows: (source, score, title)."""
    return [{"title": t, "cover": f"http://x/{s}.jpg", "source": s,
             "source_name": s, "url": f"http://x/{s}", "score": sc}
            for s, sc, t in specs]


def test_auto_pick_prefers_an_exact_title_over_a_bigger_image():
    """A cover for the wrong series is a failure however pretty it is."""
    from readerm.covers import auto_pick

    rows = _rows(("a", 30, "Something Else"), ("b", 100, "Real Title"))
    chosen, _ = auto_pick(rows, measure=False)
    assert chosen["source"] == "b"


def test_auto_pick_follows_the_settings_ranking():
    """The whole point: the button uses the order set in Settings."""
    from readerm.config import reorder
    from readerm.covers import auto_pick

    rows = _rows(("mangadex", 100, "T"), ("natomanga", 100, "T"))

    reorder(["mangadex", "natomanga"])
    first, _ = auto_pick(rows, measure=False)
    reorder(["natomanga", "mangadex"])
    second, _ = auto_pick(rows, measure=False)

    assert first["source"] == "mangadex"
    assert second["source"] == "natomanga"


def test_auto_pick_skips_list_thumbnails():
    """Measured across three titles, the rank-1 candidate was 6x-15x smaller
    in pixels than the best available -- often a 175x238 list thumbnail."""
    from readerm.config import reorder
    from readerm.covers import MIN_GOOD_PIXELS, auto_pick

    # The thumbnail source is ranked FIRST, so only the size rule can save us.
    reorder(["natomanga", "mangadex"])
    rows = _rows(("natomanga", 100, "T"), ("mangadex", 100, "T"))
    measurements = {
        "http://x/natomanga.jpg": {"width": 175, "height": 238,
                                   "pixels": 175 * 238, "bytes": 9000},
        "http://x/mangadex.jpg": {"width": 800, "height": 1164,
                                  "pixels": 800 * 1164, "bytes": 64000},
    }
    # Patch in measurements without hitting the network.
    import readerm.covers as covers_module

    original = covers_module.measure_cover
    covers_module.measure_cover = lambda url, *a, **k: (
        measurements[url]["width"], measurements[url]["height"],
        measurements[url]["bytes"], b"")
    try:
        chosen, _ = auto_pick(rows)
    finally:
        covers_module.measure_cover = original

    assert 175 * 238 < MIN_GOOD_PIXELS <= 800 * 1164
    assert chosen["source"] == "mangadex", "picked a list thumbnail"


def test_ranking_still_wins_between_two_good_covers():
    """Resolution separates artwork from thumbnails; it must not override
    the user's ranking when both are real covers."""
    from readerm.config import reorder
    from readerm.covers import auto_pick
    import readerm.covers as covers_module

    # Real source ids: rank_of() returns the default 100 for anything not in
    # the registry, so invented names all tie and resolution decides -- which
    # would make this test pass for the wrong reason.
    reorder(["natomanga", "mangadex"])
    rows = _rows(("natomanga", 100, "T"), ("mangadex", 100, "T"))
    sizes = {"http://x/natomanga.jpg": (600, 900),
             "http://x/mangadex.jpg": (2000, 3000)}
    original = covers_module.measure_cover
    covers_module.measure_cover = lambda url, *a, **k: (
        sizes[url][0], sizes[url][1], 1000, b"")
    try:
        chosen, _ = auto_pick(rows)
    finally:
        covers_module.measure_cover = original

    assert chosen["source"] == "natomanga", \
        "resolution overrode the user's ranking between two good covers"


def test_auto_pick_of_nothing_is_none():
    from readerm.covers import auto_pick

    chosen, measurements = auto_pick([], measure=False)
    assert chosen is None and measurements == {}


def test_auto_pick_survives_unmeasurable_covers():
    """A source that blocks the fetch must not crash the picker, and must
    not be treated as worst -- it may simply be strict."""
    import readerm.covers as covers_module
    from readerm.covers import auto_pick

    rows = _rows(("a", 100, "T"), ("b", 100, "T"))
    original = covers_module.measure_cover
    covers_module.measure_cover = lambda *a, **k: None
    try:
        chosen, measurements = auto_pick(rows)
    finally:
        covers_module.measure_cover = original
    assert chosen is not None
    assert measurements == {}


def test_smart_covers_endpoint_exists_and_is_async():
    from readerm.gui import Api

    api = Api()
    assert callable(getattr(api, "smart_covers", None))
    assert callable(getattr(api, "stop_smart_covers", None))


def test_smart_covers_reports_progress_and_saves(tmp_path):
    """End to end with the network stubbed: one call sorts a flat folder and
    writes a cover per series."""
    import readerm.covers as covers_module
    from readerm.gui import Api

    root = make(tmp_path,
                "Close Family Ch.001-036.cbz",
                "Close Family Ch.037-072.cbz",
                "Eleceed Ch.200.cbz")

    def fake_auto_cover(title, directory, **kwargs):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "cover.jpg"), "wb") as handle:
            handle.write(b"\xff\xd8\xff\xe0fake")
        return {"ok": True, "cover": os.path.join(directory, "cover.jpg"),
                "chosen": {"source": "stub", "source_name": "Stub"},
                "width": 800, "height": 1200}

    original = covers_module.auto_cover
    covers_module.auto_cover = fake_auto_cover
    api = Api()
    events = []
    api._push = events.append
    api._flush = lambda: None
    try:
        assert api.smart_covers(root)["ok"] is True
        api._smart_thread.join(timeout=60)
    finally:
        covers_module.auto_cover = original

    kinds = [e["type"] for e in events]
    assert "smart_start" in kinds and "smart_done" in kinds
    done = [e for e in events if e["type"] == "smart_done"][0]
    assert done["done"] == 2          # Close Family + Eleceed
    assert done["moved"] == 3         # all three archives sorted
    assert os.path.isfile(os.path.join(root, "Close Family", "cover.jpg"))
    assert os.path.isfile(os.path.join(root, "Eleceed", "cover.jpg"))


def test_smart_covers_refuses_to_run_twice(tmp_path):
    import threading

    import readerm.covers as covers_module
    from readerm.gui import Api

    root = make(tmp_path, "A Series Ch.001.cbz")
    gate = threading.Event()

    original = covers_module.auto_cover
    covers_module.auto_cover = lambda *a, **k: (
        gate.wait(10), {"ok": False, "error": "stub"})[1]
    api = Api()
    api._push = lambda e: None
    api._flush = lambda: None
    try:
        assert api.smart_covers(root)["ok"] is True
        second = api.smart_covers(root)
        assert second["ok"] is False
        assert "already running" in second["error"]
    finally:
        gate.set()
        if api._smart_thread:
            api._smart_thread.join(timeout=30)
        covers_module.auto_cover = original
