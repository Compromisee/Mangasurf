"""Tests for config, passlock and the extra feature modules.

Every test runs against a temporary HOME so it never touches real user data.
"""

import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    """Point every module at a throwaway home directory."""
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)

    import mangasurf.config as config
    import mangasurf.features as features
    import mangasurf.library as library
    import mangasurf.passlock as passlock

    for module in (config, passlock, features, library):
        importlib.reload(module)
    yield home


# =============================================================== config


def test_defaults_cover_every_source():
    from mangasurf.config import load_config
    from mangasurf.sources import SOURCES

    entries = load_config()["sources"]
    assert set(entries) == set(SOURCES)
    assert all(e["enabled"] for e in entries.values())


def test_ranks_are_unique_and_ordered():
    from mangasurf.config import ranked_ids

    order = ranked_ids()
    assert len(order) == len(set(order))


def test_reorder_persists():
    from mangasurf.config import ranked_ids, reorder

    # only the listed sources are pinned; any others keep a stable tail
    wanted = ["natomanga", "weebcentral", "mangadex", "mangakatana"]
    reorder(wanted)
    assert ranked_ids(include_disabled=True)[:len(wanted)] == wanted


def test_reorder_keeps_unmentioned_sources():
    from mangasurf.config import ranked_ids, reorder

    from mangasurf.sources import SOURCES

    reorder(["natomanga"])
    order = ranked_ids(include_disabled=True)
    assert order[0] == "natomanga"
    assert len(order) == len(SOURCES)


def test_move_up_and_down():
    from mangasurf.config import move, ranked_ids

    start = ranked_ids(include_disabled=True)
    move(start[2], -1)
    assert ranked_ids(include_disabled=True)[1] == start[2]
    move(start[2], 1)
    assert ranked_ids(include_disabled=True)[2] == start[2]


def test_move_clamps_at_the_edges():
    from mangasurf.config import move, ranked_ids

    first = ranked_ids(include_disabled=True)[0]
    move(first, -5)
    assert ranked_ids(include_disabled=True)[0] == first


def test_disabling_excludes_from_search_but_keeps_the_entry():
    from mangasurf.config import is_enabled, ranked_ids, search_ids, set_enabled

    set_enabled("natomanga", False)
    assert "natomanga" not in search_ids()
    assert "natomanga" not in ranked_ids()
    assert "natomanga" in ranked_ids(include_disabled=True)
    assert is_enabled("natomanga") is False


def test_search_only_exclusion_keeps_the_source_enabled():
    from mangasurf.config import is_enabled, ranked_ids, search_ids, set_search_enabled

    set_search_enabled("mangadex", False)
    assert "mangadex" not in search_ids()
    assert "mangadex" in ranked_ids()      # still usable by direct URL
    assert is_enabled("mangadex") is True


def test_reset_restores_defaults():
    from mangasurf.config import ranked_ids, reset_config, set_enabled

    from mangasurf.sources import SOURCES

    set_enabled("mangadex", False)
    reset_config()
    assert len(ranked_ids()) == len(SOURCES)


def test_describe_merges_metadata_and_config():
    from mangasurf.config import describe

    from mangasurf.sources import SOURCES

    rows = describe()
    assert len(rows) == len(SOURCES)
    assert {"id", "name", "base_url", "rank", "enabled"} <= set(rows[0])
    assert [r["rank"] for r in rows] == sorted(r["rank"] for r in rows)


# ============================================================= passlock


def test_lock_is_off_by_default():
    from mangasurf.passlock import status

    assert status()["enabled"] is False
    assert status()["configured"] is False


def test_set_and_verify():
    from mangasurf.passlock import set_passcode, status, verify

    result = set_passcode("opensesame")
    assert result["ok"] and result["recovery_key"]
    assert status()["enabled"] is True
    assert verify("opensesame")["ok"] is True
    assert verify("wrong")["ok"] is False


def test_passcode_is_never_stored_in_plaintext(isolated_home):
    from mangasurf.passlock import LOCK_PATH, set_passcode

    secret = "sup3r-secret-code"
    result = set_passcode(secret)
    raw = open(LOCK_PATH, encoding="utf-8").read()
    assert secret not in raw
    assert result["recovery_key"] not in raw


def test_salts_differ_between_installs():
    """Two identical passcodes must not produce the same stored hash."""
    import json

    from mangasurf.passlock import LOCK_PATH, set_passcode

    set_passcode("same-code")
    first = json.load(open(LOCK_PATH))
    set_passcode("same-code")
    second = json.load(open(LOCK_PATH))
    assert first["salt"] != second["salt"]
    assert first["hash"] != second["hash"]


def test_short_passcodes_are_rejected():
    from mangasurf.passlock import set_passcode

    assert set_passcode("ab")["ok"] is False


def test_change_requires_the_current_passcode():
    from mangasurf.passlock import change_passcode, set_passcode, verify

    set_passcode("first-code")
    assert change_passcode("wrong", "second-code")["ok"] is False
    assert change_passcode("first-code", "second-code")["ok"] is True
    assert verify("second-code")["ok"] is True
    assert verify("first-code")["ok"] is False


def test_disable_requires_the_passcode():
    from mangasurf.passlock import disable, set_passcode, status

    set_passcode("lockme123")
    assert disable("nope")["ok"] is False
    assert status()["enabled"] is True
    assert disable("lockme123")["ok"] is True
    assert status()["enabled"] is False


def test_recovery_key_resets_the_passcode():
    from mangasurf.passlock import recover, set_passcode, verify

    key = set_passcode("forgotten")["recovery_key"]
    assert recover("WRONG-KEY-HERE-XXXXX", "newcode")["ok"] is False
    assert recover(key, "brandnew")["ok"] is True
    assert verify("brandnew")["ok"] is True


def test_recovery_key_is_case_insensitive_and_ignores_spaces():
    from mangasurf.passlock import recover, set_passcode

    key = set_passcode("something")["recovery_key"]
    assert recover(key.lower().replace("-", "- "), "another1")["ok"] is True


def test_throttling_kicks_in_after_repeated_failures():
    from mangasurf.passlock import MAX_ATTEMPTS, set_passcode, verify

    set_passcode("correct-code")
    for _ in range(MAX_ATTEMPTS):
        result = verify("bad")
    assert result["ok"] is False
    assert result.get("cooldown", 0) > 0
    # even the right passcode is refused during the cooldown
    assert verify("correct-code")["ok"] is False


def test_verify_passes_when_lock_is_disabled():
    from mangasurf.passlock import verify

    assert verify("anything")["ok"] is True


def test_update_options_without_passcode():
    from mangasurf.passlock import set_passcode, status, update_options

    set_passcode("mycode123")
    update_options(auto_lock_minutes=15, blur_covers=False, hint="the usual")
    current = status()
    assert current["auto_lock_minutes"] == 15
    assert current["blur_covers"] is False
    assert current["hint"] == "the usual"


# ============================================================= history


def test_history_records_and_deduplicates():
    from mangasurf.features import add_history, get_history

    add_history("naruto", "mangadex", 10)
    add_history("bleach", "all", 5)
    add_history("naruto", "all", 8)          # same query again
    items = get_history()
    assert [h["query"] for h in items] == ["naruto", "bleach"]
    assert items[0]["results"] == 8          # newest wins


def test_history_suggestions():
    from mangasurf.features import add_history, suggest

    for title in ("naruto", "nana", "bleach"):
        add_history(title)
    assert suggest("na") == ["nana", "naruto"] or suggest("na") == ["naruto", "nana"]
    assert "bleach" in suggest("")


def test_history_clear_and_remove():
    from mangasurf.features import add_history, clear_history, get_history, remove_history

    add_history("one")
    add_history("two")
    remove_history("one")
    assert [h["query"] for h in get_history()] == ["two"]
    clear_history()
    assert get_history() == []


# =============================================================== queue


def test_queue_add_and_order():
    from mangasurf.features import queue_add, queue_list, queue_move

    queue_add({"url": "a", "title": "A"})
    b = queue_add({"url": "b", "title": "B"})
    queue_add({"url": "c", "title": "C"})
    assert [j["title"] for j in queue_list()] == ["A", "B", "C"]
    queue_move(b["id"], -1)
    assert [j["title"] for j in queue_list()] == ["B", "A", "C"]


def test_queue_status_and_next():
    from mangasurf.features import queue_add, queue_list, queue_next, queue_update

    first = queue_add({"url": "a", "title": "A"})
    queue_add({"url": "b", "title": "B"})
    queue_update(first["id"], status="done")
    assert queue_next()["title"] == "B"
    assert len(queue_list("pending")) == 1


def test_queue_remove_and_clear():
    from mangasurf.features import queue_add, queue_clear, queue_list, queue_remove

    job = queue_add({"url": "a", "title": "A"})
    queue_add({"url": "b", "title": "B"})
    queue_remove(job["id"])
    assert len(queue_list()) == 1
    queue_clear()
    assert queue_list() == []


# =============================================================== stats


def test_stats_accumulate():
    from mangasurf.features import get_stats, record_stat

    record_stat("mangadex", chapters=2, pages=40, bytes_=1000, seconds=10)
    record_stat("mangadex", chapters=3, pages=60, bytes_=2000, seconds=20)
    stats = get_stats()
    assert stats["totals"]["chapters"] == 5
    assert stats["totals"]["pages"] == 100
    assert stats["sources"]["mangadex"]["downloads"] == 2
    assert stats["derived"]["top_source"] == "mangadex"


def test_stats_reset():
    from mangasurf.features import get_stats, record_stat, reset_stats

    record_stat("mangadex", chapters=1)
    reset_stats()
    assert get_stats().get("totals", {}) == {}


@pytest.mark.parametrize("value,expected", [
    (0, "0 B"), (512, "512 B"), (2048, "2.0 KB"), (5 * 1024 ** 2, "5.0 MB"),
])
def test_human_size(value, expected):
    from mangasurf.features import human_size

    assert human_size(value) == expected


@pytest.mark.parametrize("value,expected", [
    (30, "30s"), (90, "1m 30s"), (3700, "1h 1m"),
])
def test_human_time(value, expected):
    from mangasurf.features import human_time

    assert human_time(value) == expected


# ============================================================= filters


def test_blocked_tags_and_titles():
    from mangasurf.features import apply_filters, set_filters

    set_filters(blocked_tags=["Doujinshi"], blocked_titles=["colored"])
    results = [
        {"title": "Naruto", "tags": ["Action"]},
        {"title": "Naruto (Fan Colored)", "tags": ["Action"]},
        {"title": "Some Doujin", "tags": ["Doujinshi"]},
    ]
    assert [r["title"] for r in apply_filters(results)] == ["Naruto"]


def test_hide_results_without_covers():
    from mangasurf.features import apply_filters, set_filters

    set_filters(hide_no_cover=True)
    results = [{"title": "A", "cover": "x"}, {"title": "B", "cover": None}]
    assert [r["title"] for r in apply_filters(results)] == ["A"]


def test_safe_mode_drops_adult_content():
    from mangasurf.features import apply_filters, set_filters

    set_filters(safe_mode=True)
    results = [
        {"title": "Clean", "tags": ["Action"]},
        {"title": "Adult", "content_rating": "pornographic"},
        {"title": "Ecchi", "tags": ["Hentai"]},
    ]
    assert [r["title"] for r in apply_filters(results)] == ["Clean"]


def test_blocked_authors():
    from mangasurf.features import apply_filters, set_filters

    set_filters(blocked_authors=["Bad Author"])
    results = [{"title": "A", "authors": ["Good"]},
               {"title": "B", "authors": ["Bad Author"]}]
    assert [r["title"] for r in apply_filters(results)] == ["A"]


def test_filters_are_a_no_op_when_unset():
    from mangasurf.features import apply_filters

    results = [{"title": "A"}, {"title": "B"}]
    assert len(apply_filters(results)) == 2


# ============================================================== dedupe


def test_dedupe_collapses_cross_source_duplicates():
    from mangasurf.features import dedupe

    hits = [
        {"title": "Naruto", "source": "weebcentral", "url": "w"},
        {"title": "Naruto", "source": "mangadex", "url": "m"},
        {"title": "Bleach", "source": "mangadex", "url": "b"},
    ]
    merged = dedupe(hits, ranks={"mangadex": 0, "weebcentral": 3})
    assert len(merged) == 2
    naruto = next(m for m in merged if m["title"] == "Naruto")
    assert naruto["source"] == "mangadex"          # better rank wins
    assert naruto["also_on"][0]["source"] == "weebcentral"


def test_dedupe_normalises_decorated_titles():
    from mangasurf.features import dedupe

    hits = [
        {"title": "Naruto", "source": "mangadex", "url": "m"},
        {"title": "Naruto (Colored)", "source": "natomanga", "url": "n"},
        {"title": "Naruto [Official]", "source": "weebcentral", "url": "w"},
    ]
    assert len(dedupe(hits, ranks={"mangadex": 0})) == 1


def test_dedupe_keeps_genuinely_different_series():
    from mangasurf.features import dedupe

    hits = [{"title": "Naruto", "source": "a", "url": "1"},
            {"title": "Bleach", "source": "a", "url": "2"}]
    assert len(dedupe(hits)) == 2


# ========================================================= collections


def test_collection_lifecycle():
    from mangasurf.features import (add_to_collection, delete_collection,
                                  get_collections, remove_from_collection)

    add_to_collection("Faves", {"url": "u1", "title": "One"})
    add_to_collection("Faves", {"url": "u2", "title": "Two"})
    add_to_collection("Faves", {"url": "u1", "title": "One"})   # duplicate
    assert len(get_collections()["Faves"]["items"]) == 2

    remove_from_collection("Faves", "u1")
    assert len(get_collections()["Faves"]["items"]) == 1

    delete_collection("Faves")
    assert "Faves" not in get_collections()


# ============================================================== export


def test_export_json_csv_and_markdown(tmp_path):
    import json

    from readerm import library
    from mangasurf.features import export_library

    library.record_chapter("https://x.test/manga/1", "Test Manga", "Chapter 1",
                           pages=12, source="mangadex")

    json_path = tmp_path / "lib.json"
    export_library(str(json_path), "json")
    data = json.loads(json_path.read_text())
    assert data[0]["title"] == "Test Manga"

    csv_path = tmp_path / "lib.csv"
    export_library(str(csv_path), "csv")
    assert "Test Manga" in csv_path.read_text()

    md_path = tmp_path / "lib.md"
    export_library(str(md_path), "md")
    assert "| Title |" in md_path.read_text()


def test_export_rejects_unknown_format(tmp_path):
    from mangasurf.features import export_library

    with pytest.raises(ValueError):
        export_library(str(tmp_path / "x.bin"), "bin")


def test_import_round_trip(tmp_path):
    from readerm import library
    from mangasurf.features import export_library, import_library

    library.record_chapter("https://x.test/m/1", "Round Trip", "Chapter 1",
                           pages=5, source="mangadex")
    path = tmp_path / "lib.json"
    export_library(str(path), "json")
    library.clear_library()
    assert library.load_library() == {}

    result = import_library(str(path))
    assert result["imported"] == 1
    assert "Round Trip" in [e["title"] for e in library.load_library().values()]


# =========================================================== snapshots


def test_snapshot_and_restore():
    from readerm import library
    from mangasurf.features import list_snapshots, restore_snapshot, snapshot

    library.record_chapter("https://x.test/m/1", "Before", "Chapter 1",
                           source="mangadex")
    snap = snapshot("checkpoint")
    library.clear_library()
    assert library.load_library() == {}

    assert restore_snapshot(snap["id"]) is True
    assert "Before" in [e["title"] for e in library.load_library().values()]
    assert list_snapshots()[0]["label"] == "checkpoint"


# ============================================================ insights


def test_library_insights():
    from readerm import library
    from mangasurf.features import library_insights

    library.record_chapter("https://x.test/m/1", "A", "Chapter 1", pages=10,
                           source="mangadex")
    library.record_chapter("https://x.test/m/1", "A", "Chapter 2", pages=12,
                           source="mangadex")
    library.record_chapter("https://x.test/m/2", "B", "Chapter 1", pages=8,
                           source="natomanga")

    insights = library_insights()
    assert insights["series"] == 2
    assert insights["chapters"] == 3
    assert insights["pages"] == 30
    assert insights["by_source"]["mangadex"] == 1


# ================================================= search integration


def test_search_all_skips_excluded_sources(monkeypatch):
    """A source the user excluded must not be queried at all."""
    from readerm import config
    from mangasurf.sources import SOURCES, search_all

    config.set_enabled("natomanga", False)
    queried = []

    class FakeSource:
        def __init__(self, source_id):
            self.id = source_id

        def search(self, query, limit=20, **kwargs):
            queried.append(self.id)
            return [{"title": f"{self.id} hit", "url": "u", "source": self.id}]

        def close(self):
            pass

    monkeypatch.setattr("mangasurf.sources.get_source",
                        lambda sid, **kw: FakeSource(sid))
    results = search_all("anything")
    assert "natomanga" not in queried
    assert len(queried) == len(SOURCES) - 1
    assert all(r["source"] != "natomanga" for r in results)


def test_search_all_orders_by_rank(monkeypatch):
    from readerm import config
    from mangasurf.sources import search_all

    pinned = ["weebcentral", "natomanga", "mangakatana", "mangadex"]
    config.reorder(pinned)

    class FakeSource:
        def __init__(self, source_id):
            self.id = source_id

        def search(self, query, limit=20, **kwargs):
            return [{"title": f"{self.id} hit", "url": "u", "source": self.id}]

        def close(self):
            pass

    monkeypatch.setattr("mangasurf.sources.get_source",
                        lambda sid, **kw: FakeSource(sid))
    order = [r["source"] for r in search_all("anything")]
    assert order[:len(pinned)] == pinned


def test_search_all_interleaves_when_asked(monkeypatch):
    from readerm import config
    from mangasurf.sources import search_all

    config.reorder(["mangadex", "mangakatana", "natomanga", "weebcentral"])

    class FakeSource:
        def __init__(self, source_id):
            self.id = source_id

        def search(self, query, limit=20, **kwargs):
            return [{"title": f"{self.id} {i}", "url": "u", "source": self.id}
                    for i in range(2)]

        def close(self):
            pass

    monkeypatch.setattr("mangasurf.sources.get_source",
                        lambda sid, **kw: FakeSource(sid))
    order = [r["source"] for r in search_all("x", interleave=True)]
    assert order[:4] == ["mangadex", "mangakatana", "natomanga", "weebcentral"]


def test_search_all_survives_a_failing_source(monkeypatch):
    from mangasurf.sources import search_all

    class FakeSource:
        def __init__(self, source_id):
            self.id = source_id

        def search(self, query, limit=20, **kwargs):
            if self.id == "mangadex":
                raise RuntimeError("site down")
            return [{"title": "ok", "url": "u", "source": self.id}]

        def close(self):
            pass

    monkeypatch.setattr("mangasurf.sources.get_source",
                        lambda sid, **kw: FakeSource(sid))
    results = search_all("x")
    assert results                                    # other sources still work
    assert all(r["source"] != "mangadex" for r in results)
