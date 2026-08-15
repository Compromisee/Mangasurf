"""Tests for genre search, query-less trending, and the robust-calling layer."""

import importlib
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NETWORK = pytest.mark.skipif(
    not os.environ.get("READERM_NETWORK_TESTS"),
    reason="set READERM_NETWORK_TESTS=1 to run live-site tests",
)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch):
    home = tempfile.mkdtemp()
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("USERPROFILE", home)
    import readerm.config as config
    import readerm.features as features
    import readerm.robust as robust
    for module in (config, features, robust):
        importlib.reload(module)
    # start every test from a clean breaker/cache
    robust.SOURCE_BREAKER.reset()
    robust.BROWSE_CACHE.invalidate()
    robust.GENRE_CACHE.invalidate()
    yield home


class FakeSource:
    """Stand-in source so browse tests never touch the network."""

    supports_browse = True
    supports_genres = True

    def __init__(self, source_id, rows=2, fail=False, genres=None):
        self.id = source_id
        self.name = source_id.title()
        self.rows = rows
        self.fail = fail
        self._genres = genres or ["Action", "Romance"]
        self.browse_calls = []

    def browse(self, sort=None, genre=None, page=1, limit=32, **kwargs):
        if self.fail:
            raise RuntimeError(f"{self.id} is down")
        self.browse_calls.append({"sort": sort, "genre": genre, "page": page})
        return [
            {"title": f"{self.id} {genre or sort or 'top'} {i}",
             "url": f"https://{self.id}.test/{i}", "source": self.id,
             "source_name": self.name}
            for i in range(self.rows)
        ]

    def search(self, query, limit=20, **kwargs):
        if self.fail:
            raise RuntimeError(f"{self.id} is down")
        return [{"title": f"{self.id} {query}", "url": f"https://{self.id}.test/q",
                 "source": self.id, "source_name": self.name}]

    def genres(self):
        return [{"id": g.lower(), "name": g} for g in self._genres]

    def close(self):
        pass


def patch_sources(monkeypatch, factory):
    monkeypatch.setattr("readerm.sources.get_source",
                        lambda sid, **kw: factory(sid))


# ============================================================ source layer


def test_every_source_declares_browse_support():
    from readerm.sources import SOURCES

    for cls in SOURCES.values():
        assert isinstance(cls.supports_browse, bool)
        assert isinstance(cls.supports_genres, bool)


def test_all_sources_support_browse_and_genres():
    from readerm.sources import SOURCES

    assert all(cls.supports_browse for cls in SOURCES.values())
    assert all(cls.supports_genres for cls in SOURCES.values())


def test_list_sources_exposes_browse_metadata():
    from readerm.sources import list_sources

    row = list_sources()[0]
    assert "supports_browse" in row
    assert "browse_sorts" in row


def test_base_browse_is_abstract():
    from readerm.sources.base import Source

    with pytest.raises(NotImplementedError):
        Source().browse()


def test_base_genres_defaults_to_empty():
    from readerm.sources.base import Source

    assert Source().genres() == []


# ============================================== mangadex genre resolution


def test_mangadex_resolves_genre_names_to_tag_ids(monkeypatch):
    from readerm.sources.mangadex import MangaDexSource

    MangaDexSource._tag_cache = [
        {"id": "uuid-action", "name": "Action", "group": "genre"},
        {"id": "uuid-scifi", "name": "Sci-Fi", "group": "genre"},
    ]
    source = MangaDexSource()
    assert source._tag_id("Action") == "uuid-action"
    assert source._tag_id("action") == "uuid-action"     # case-insensitive
    assert source._tag_id("sci") == "uuid-scifi"         # partial match
    assert source._tag_id("nonsense") is None
    MangaDexSource._tag_cache = None


def test_mangadex_passes_through_a_raw_tag_uuid():
    from readerm.sources.mangadex import MangaDexSource

    uuid = "391b0423-d847-456f-aff0-8b0cfc03066b"
    assert MangaDexSource()._tag_id(uuid) == uuid


def test_mangadex_trending_maps_to_follow_count():
    from readerm.sources.mangadex import MangaDexSource

    assert MangaDexSource._SORTS["Trending"] == ("followedCount", "desc")


# ==================================================== browse_all merging


def test_browse_all_queries_every_enabled_source(monkeypatch):
    from readerm.sources import SOURCES, browse_all

    patch_sources(monkeypatch, lambda sid: FakeSource(sid))
    results = browse_all(limit=2)
    assert len({r["source"] for r in results}) == len(SOURCES)


def test_browse_all_interleaves_by_default(monkeypatch):
    from readerm.config import reorder
    from readerm.sources import browse_all

    reorder(["mangadex", "mangakatana", "natomanga", "weebcentral"])
    patch_sources(monkeypatch, lambda sid: FakeSource(sid, rows=2))
    order = [r["source"] for r in browse_all(limit=2)]
    assert order[:4] == ["mangadex", "mangakatana", "natomanga", "weebcentral"]


def test_browse_all_can_group_instead(monkeypatch):
    from readerm.config import reorder
    from readerm.sources import browse_all

    reorder(["mangadex", "mangakatana", "natomanga", "weebcentral"])
    patch_sources(monkeypatch, lambda sid: FakeSource(sid, rows=2))
    order = [r["source"] for r in browse_all(limit=2, interleave=False)]
    assert order[:2] == ["mangadex", "mangadex"]


def test_browse_all_respects_rank(monkeypatch):
    from readerm.config import reorder
    from readerm.sources import browse_all

    pinned = ["weebcentral", "natomanga", "mangakatana", "mangadex"]
    reorder(pinned)
    patch_sources(monkeypatch, lambda sid: FakeSource(sid, rows=1))
    assert [r["source"] for r in browse_all(limit=1)][:len(pinned)] == pinned


def test_browse_all_skips_excluded_sources(monkeypatch):
    from readerm.config import set_enabled
    from readerm.sources import browse_all

    set_enabled("natomanga", False)
    patch_sources(monkeypatch, lambda sid: FakeSource(sid))
    assert all(r["source"] != "natomanga" for r in browse_all())


def test_browse_all_survives_a_dead_source(monkeypatch):
    from readerm.sources import browse_all

    patch_sources(monkeypatch,
                  lambda sid: FakeSource(sid, fail=(sid == "mangadex")))
    results = browse_all(use_cache=False)
    assert results
    assert all(r["source"] != "mangadex" for r in results)


def test_browse_all_passes_the_genre_through(monkeypatch):
    from readerm.sources import browse_all

    created = {}

    def factory(sid):
        created[sid] = FakeSource(sid)
        return created[sid]

    patch_sources(monkeypatch, factory)
    browse_all(genre="Horror", use_cache=False)
    assert all(s.browse_calls[0]["genre"] == "Horror" for s in created.values())


def test_browse_all_skips_sources_that_cannot_browse(monkeypatch):
    from readerm.sources import SOURCES, browse_all

    original = SOURCES["weebcentral"].supports_browse
    SOURCES["weebcentral"].supports_browse = False
    try:
        patch_sources(monkeypatch, lambda sid: FakeSource(sid))
        assert all(r["source"] != "weebcentral" for r in browse_all())
    finally:
        SOURCES["weebcentral"].supports_browse = original


def test_browse_results_are_cached(monkeypatch):
    from readerm.sources import browse_all

    counter = {"n": 0}

    class Counting(FakeSource):
        def browse(self, **kwargs):
            counter["n"] += 1
            return super().browse(**kwargs)

    patch_sources(monkeypatch, lambda sid: Counting(sid))
    browse_all(limit=2)
    first = counter["n"]
    browse_all(limit=2)                       # identical request
    assert counter["n"] == first              # served from cache


# ============================================================ genres_all


def test_genres_all_merges_across_sources(monkeypatch):
    from readerm.sources import genres_all

    monkeypatch.setattr(
        "readerm.sources.get_source",
        lambda sid, **kw: FakeSource(
            sid, genres=["Action", "Romance"] if sid == "mangadex"
            else ["action", "Horror"]))
    rows = genres_all()
    names = {r["name"].lower() for r in rows}
    assert "action" in names and "romance" in names and "horror" in names
    from readerm.sources import SOURCES

    action = next(r for r in rows if r["name"].lower() == "action")
    assert len(action["sources"]) == len(SOURCES)   # every source offers it


def test_genres_all_sorts_widely_supported_first(monkeypatch):
    from readerm.sources import genres_all

    monkeypatch.setattr(
        "readerm.sources.get_source",
        lambda sid, **kw: FakeSource(
            sid, genres=["Action", "Rare"] if sid == "mangadex" else ["Action"]))
    rows = genres_all()
    assert rows[0]["name"] == "Action"


def test_genres_all_survives_a_failing_source(monkeypatch):
    from readerm.sources import genres_all

    class Boom(FakeSource):
        def genres(self):
            raise RuntimeError("nope")

    monkeypatch.setattr(
        "readerm.sources.get_source",
        lambda sid, **kw: Boom(sid) if sid == "mangadex" else FakeSource(sid))
    assert genres_all()          # other sources still contribute


# =========================================================== robust layer


def test_retry_eventually_succeeds():
    from readerm.robust import retry

    state = {"n": 0}

    @retry(attempts=4, base=0.001)
    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert flaky() == "ok"
    assert state["n"] == 3


def test_retry_gives_up_and_reraises():
    from readerm.robust import retry

    @retry(attempts=2, base=0.001)
    def always():
        raise ValueError("always")

    with pytest.raises(ValueError):
        always()


def test_retry_if_can_skip_pointless_retries():
    from readerm.robust import retry

    state = {"n": 0}

    @retry(attempts=5, base=0.001, retry_if=lambda e: "404" not in str(e))
    def missing():
        state["n"] += 1
        raise ValueError("404 not found")

    with pytest.raises(ValueError):
        missing()
    assert state["n"] == 1


def test_backoff_grows_and_stays_capped():
    from readerm.robust import backoff_delay

    assert backoff_delay(0, base=1, cap=30) < backoff_delay(4, base=1, cap=30)
    assert all(backoff_delay(i, base=1, cap=10) <= 12.1 for i in range(10))


def test_circuit_opens_after_the_threshold():
    from readerm.robust import CircuitBreaker, CircuitOpen

    breaker = CircuitBreaker(threshold=3, cooldown=10)

    def boom():
        raise RuntimeError("down")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call("site", boom)
    assert breaker.state("site") == "open"
    with pytest.raises(CircuitOpen):
        breaker.call("site", boom)


def test_circuit_half_opens_then_closes_on_success():
    from readerm.robust import CircuitBreaker

    breaker = CircuitBreaker(threshold=2, cooldown=0.05)

    def boom():
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker.call("site", boom)
    time.sleep(0.08)
    assert breaker.state("site") == "half-open"
    assert breaker.call("site", lambda: "alive") == "alive"
    assert breaker.state("site") == "closed"


def test_circuit_success_resets_the_failure_count():
    from readerm.robust import CircuitBreaker

    breaker = CircuitBreaker(threshold=3, cooldown=10)
    with pytest.raises(RuntimeError):
        breaker.call("s", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    breaker.call("s", lambda: "ok")
    assert breaker.snapshot()["s"]["failures"] == 0


def test_circuit_cooldown_escalates():
    from readerm.robust import CircuitBreaker

    breaker = CircuitBreaker(threshold=1, cooldown=1.0, max_cooldown=100)
    entry = breaker._entry("s")
    entry["trips"] = 1
    first = breaker._cooldown_for(entry)
    entry["trips"] = 3
    assert breaker._cooldown_for(entry) > first


def test_ttl_cache_hits_then_expires():
    from readerm.robust import TTLCache

    cache = TTLCache(ttl=0.05)
    state = {"n": 0}

    def build():
        state["n"] += 1
        return state["n"]

    assert cache.get_or_set("k", build) == 1
    assert cache.get_or_set("k", build) == 1     # cached
    time.sleep(0.08)
    assert cache.get_or_set("k", build) == 2     # expired


def test_ttl_cache_evicts_when_full():
    from readerm.robust import TTLCache

    cache = TTLCache(ttl=60, maxsize=3)
    for i in range(5):
        cache.set(f"k{i}", i)
    assert cache.stats()["entries"] <= 3


def test_ttl_cache_invalidate():
    from readerm.robust import TTLCache

    cache = TTLCache()
    cache.set("a", 1)
    cache.invalidate("a")
    assert cache.get("a") is None


def test_call_safely_returns_the_fallback():
    from readerm.robust import call_safely

    def boom():
        raise RuntimeError("x")

    assert call_safely(boom, default=[], label="test") == []
    assert call_safely(lambda: "fine", default=[]) == "fine"


def test_gather_keeps_partial_results():
    from readerm.robust import gather

    results, errors = gather({
        "a": lambda: 1,
        "b": lambda: (_ for _ in ()).throw(RuntimeError("no")),
        "c": lambda: 3,
    })
    assert results == {"a": 1, "c": 3}
    assert "b" in errors


def test_gather_handles_no_tasks():
    from readerm.robust import gather

    assert gather({}) == ({}, {})


def test_health_report_shape():
    from readerm.robust import health_report

    report = health_report()
    assert {"breakers", "browse_cache", "genre_cache"} <= set(report)


# ======================================================== gui integration


def test_empty_query_triggers_browse(monkeypatch):
    """Pressing Search with an empty box must return trending, not an error."""
    from readerm.gui import Api

    patch_sources(monkeypatch, lambda sid: FakeSource(sid))
    result = Api().search("", {"source": "all"})
    assert result["ok"] is True
    assert result.get("browse") is True
    assert result["results"]


def test_empty_query_with_genre_browses_that_genre(monkeypatch):
    from readerm.gui import Api

    patch_sources(monkeypatch, lambda sid: FakeSource(sid))
    result = Api().search("", {"source": "all", "genre": "Horror"})
    assert result["genre"] == "Horror"
    assert all("Horror" in r["title"] for r in result["results"])


def test_non_empty_query_still_searches(monkeypatch):
    from readerm.gui import Api

    patch_sources(monkeypatch, lambda sid: FakeSource(sid))
    result = Api().search("naruto", {"source": "all"})
    assert not result.get("browse")


def test_browse_reports_unsupported_sources(monkeypatch):
    from readerm.gui import Api
    from readerm.sources import SOURCES

    original = SOURCES["weebcentral"].supports_browse
    SOURCES["weebcentral"].supports_browse = False
    try:
        api = Api()
        monkeypatch.setattr(api, "_source",
                            lambda sid=None, url=None: SOURCES["weebcentral"]())
        result = api.browse({"source": "weebcentral"})
        assert result["ok"] is True
        assert result["results"] == []
        assert "cannot list" in result["message"]
    finally:
        SOURCES["weebcentral"].supports_browse = original


# ============================================================ live checks


@NETWORK
@pytest.mark.parametrize("source_id", ["mangadex", "mangakatana",
                                       "natomanga", "weebcentral"])
def test_live_browse_returns_results(source_id):
    from readerm.sources import get_source

    source = get_source(source_id)
    try:
        rows = source.browse(limit=5)
        assert rows, f"{source_id} returned no trending results"
        assert all(r.get("title") and r.get("url") for r in rows)
    finally:
        source.close()


@NETWORK
@pytest.mark.parametrize("source_id", ["mangadex", "mangakatana",
                                       "natomanga", "weebcentral"])
def test_live_genres_are_listed(source_id):
    from readerm.sources import get_source

    source = get_source(source_id)
    try:
        genres = source.genres()
        assert genres, f"{source_id} listed no genres"
        assert all(g.get("name") for g in genres)
    finally:
        source.close()


@NETWORK
def test_live_genre_browse_actually_filters():
    """A genre listing must differ from the unfiltered one."""
    from readerm.sources import get_source

    source = get_source("weebcentral")
    try:
        plain = {r["title"] for r in source.browse(limit=8)}
        horror = {r["title"] for r in source.browse(genre="Horror", limit=8)}
        assert horror and horror != plain
    finally:
        source.close()


@NETWORK
def test_live_browse_all_mixes_sources():
    from readerm.sources import browse_all

    rows = browse_all(limit=3, use_cache=False)
    assert len({r["source"] for r in rows}) >= 2
