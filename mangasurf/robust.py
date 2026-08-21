"""Robust calling: retries, circuit breaking, caching and graceful degradation.

Sources talk to third-party websites that go down, rate-limit, change markup
or simply hang. This module centralises the defensive plumbing so a single
misbehaving site degrades the experience instead of breaking it.

Pieces
------
``retry``            decorator: bounded retries with exponential backoff+jitter
``CircuitBreaker``   stops hammering a site that is clearly down, then probes
``TTLCache``         short-lived in-memory cache for idempotent lookups
``call_safely``      run a callable, swallow failure, return a fallback
``gather``           run many callables in parallel, keep whatever succeeds

The circuit breaker is the important one. Without it, a dead site costs the
full timeout on every single request; with it, the first few failures trip the
breaker and subsequent calls fail instantly until a cooldown elapses.
"""

import functools
import logging
import random
import threading
import time

logger = logging.getLogger(__name__)


class CircuitOpen(Exception):
    """Raised when a call is refused because the breaker is open."""


# ============================================================ retry helper


def backoff_delay(attempt, base=1.0, cap=30.0, jitter=0.2):
    """Exponential backoff with proportional jitter."""
    delay = min(base * (2 ** attempt), cap)
    spread = delay * jitter
    return max(0.05, delay + random.uniform(-spread, spread))


def retry(attempts=3, base=1.0, cap=30.0, exceptions=(Exception,),
          on_retry=None, retry_if=None):
    """Retry a callable with exponential backoff.

    ``retry_if`` may inspect the exception and return False to give up early
    (useful for 404s, which will never succeed no matter how often you ask).
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last = None
            for attempt in range(max(1, attempts)):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    last = exc
                    if retry_if is not None and not retry_if(exc):
                        raise
                    if attempt >= attempts - 1:
                        break
                    delay = backoff_delay(attempt, base, cap)
                    if on_retry:
                        try:
                            on_retry(attempt + 1, exc, delay)
                        except Exception:
                            pass
                    logger.debug("%s failed (%s); retry %d in %.1fs",
                                 getattr(fn, "__name__", "call"), exc,
                                 attempt + 1, delay)
                    time.sleep(delay)
            raise last
        return wrapper
    return decorator


# =========================================================== circuit breaker


class CircuitBreaker:
    """Per-target breaker with closed / open / half-open states.

    closed     calls pass through; consecutive failures are counted
    open       calls are refused immediately until the cooldown expires
    half-open  a single probe is allowed; success closes, failure re-opens
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"

    def __init__(self, threshold=4, cooldown=60.0, max_cooldown=600.0):
        self.threshold = int(threshold)
        self.cooldown = float(cooldown)
        self.max_cooldown = float(max_cooldown)
        self._lock = threading.RLock()
        self._state = {}

    def _entry(self, key):
        return self._state.setdefault(key, {
            "failures": 0, "opened_at": 0.0, "trips": 0,
            "state": self.CLOSED, "last_error": "",
        })

    def state(self, key):
        with self._lock:
            entry = self._entry(key)
            if entry["state"] == self.OPEN:
                waited = time.time() - entry["opened_at"]
                if waited >= self._cooldown_for(entry):
                    entry["state"] = self.HALF_OPEN
            return entry["state"]

    def _cooldown_for(self, entry):
        """Each repeated trip doubles the cooldown, up to the cap."""
        trips = max(1, entry["trips"])
        return min(self.max_cooldown, self.cooldown * (2 ** (trips - 1)))

    def allows(self, key):
        return self.state(key) != self.OPEN

    def record_success(self, key):
        with self._lock:
            entry = self._entry(key)
            entry.update({"failures": 0, "state": self.CLOSED,
                          "opened_at": 0.0, "trips": 0, "last_error": ""})

    def record_failure(self, key, error=""):
        with self._lock:
            entry = self._entry(key)
            entry["failures"] += 1
            entry["last_error"] = str(error)[:200]
            if entry["failures"] >= self.threshold or entry["state"] == self.HALF_OPEN:
                entry["state"] = self.OPEN
                entry["opened_at"] = time.time()
                entry["trips"] += 1
                logger.warning("Circuit opened for '%s' after %d failures "
                               "(cooldown %.0fs)", key, entry["failures"],
                               self._cooldown_for(entry))

    def retry_after(self, key):
        """Seconds until an open breaker will allow a probe."""
        with self._lock:
            entry = self._entry(key)
            if entry["state"] != self.OPEN:
                return 0.0
            return max(0.0, self._cooldown_for(entry)
                       - (time.time() - entry["opened_at"]))

    def call(self, key, fn, *args, **kwargs):
        if not self.allows(key):
            raise CircuitOpen(
                f"'{key}' is temporarily unavailable "
                f"(retry in {self.retry_after(key):.0f}s)")
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            self.record_failure(key, exc)
            raise
        self.record_success(key)
        return result

    def reset(self, key=None):
        with self._lock:
            if key is None:
                self._state.clear()
            else:
                self._state.pop(key, None)

    def snapshot(self):
        """Current breaker state per target, for diagnostics."""
        with self._lock:
            return {
                key: {
                    "state": self.state(key),
                    "failures": entry["failures"],
                    "trips": entry["trips"],
                    "retry_after": round(self.retry_after(key), 1),
                    "last_error": entry["last_error"],
                }
                for key, entry in self._state.items()
            }


# Shared breaker, keyed by source id.
SOURCE_BREAKER = CircuitBreaker(threshold=4, cooldown=45.0)


# ================================================================= caching


class TTLCache:
    """Small thread-safe cache with per-entry expiry and LRU-ish eviction."""

    def __init__(self, ttl=300.0, maxsize=256):
        self.ttl = float(ttl)
        self.maxsize = int(maxsize)
        self._lock = threading.RLock()
        self._data = {}
        self.hits = 0
        self.misses = 0

    def get(self, key, default=None):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return default
            value, expires = item
            if time.time() >= expires:
                self._data.pop(key, None)
                self.misses += 1
                return default
            self.hits += 1
            return value

    def set(self, key, value, ttl=None):
        with self._lock:
            if len(self._data) >= self.maxsize:
                # drop the entry closest to expiry
                oldest = min(self._data, key=lambda k: self._data[k][1])
                self._data.pop(oldest, None)
            self._data[key] = (value, time.time() + float(ttl or self.ttl))
            return value

    def get_or_set(self, key, factory, ttl=None):
        sentinel = object()
        found = self.get(key, sentinel)
        if found is not sentinel:
            return found
        value = factory()
        self.set(key, value, ttl)
        return value

    def invalidate(self, key=None):
        with self._lock:
            if key is None:
                self._data.clear()
            else:
                self._data.pop(key, None)

    def stats(self):
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._data),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total * 100, 1) if total else 0.0,
            }


# Discovery listings change slowly; caching them makes the UI feel instant
# and spares the sites repeated identical requests.
BROWSE_CACHE = TTLCache(ttl=300.0, maxsize=128)
GENRE_CACHE = TTLCache(ttl=3600.0, maxsize=32)


def cache_key(*parts):
    return "|".join("" if p is None else str(p) for p in parts)


# ============================================================ safe calling


def call_safely(fn, *args, default=None, label="", breaker=None,
                breaker_key=None, **kwargs):
    """Run a callable, returning ``default`` instead of raising.

    Every failure is logged once with context. This is the workhorse for
    "one source failing must not break the page".
    """
    try:
        if breaker is not None and breaker_key is not None:
            return breaker.call(breaker_key, fn, *args, **kwargs)
        return fn(*args, **kwargs)
    except CircuitOpen as exc:
        logger.info("Skipped %s: %s", label or getattr(fn, "__name__", "call"), exc)
        return default
    except Exception as exc:
        logger.warning("%s failed: %s", label or getattr(fn, "__name__", "call"), exc)
        return default


def gather(tasks, workers=4, timeout=None):
    """Run ``{key: callable}`` in parallel and keep whatever succeeds.

    Returns ``(results, errors)``. Never raises: a task that blows up lands in
    ``errors`` and the rest still come back.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    tasks = dict(tasks or {})
    if not tasks:
        return {}, {}

    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(tasks)))) as pool:
        futures = {pool.submit(fn): key for key, fn in tasks.items()}
        try:
            for future in as_completed(futures, timeout=timeout):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as exc:
                    errors[key] = str(exc)
                    logger.warning("Task '%s' failed: %s", key, exc)
        except Exception as exc:
            # overall timeout: keep what finished
            for future, key in futures.items():
                if key not in results and key not in errors:
                    errors[key] = f"timed out: {exc}"
                    future.cancel()
    return results, errors


def health_report():
    """Diagnostics for the UI: breaker state plus cache efficiency."""
    return {
        "breakers": SOURCE_BREAKER.snapshot(),
        "browse_cache": BROWSE_CACHE.stats(),
        "genre_cache": GENRE_CACHE.stats(),
    }
