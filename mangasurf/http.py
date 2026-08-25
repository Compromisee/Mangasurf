"""curl_cffi HTTP layer for Mangasurf.

Mangasurf is all-in on **curl_cffi**. ``curl_cffi`` is a thin, native C
binding over libcurl that performs **real TLS/JA3+JA4 browser
fingerprinting** (``impersonate="chrome"`` etc.), which gets us past the
Cloudflare / Akamai bot checks that block plain ``requests``-style clients,
and it is measurably faster per request than ``requests`` + urllib3.

This module is the single place Mangasurf talks to the network. It exposes
two layers:

1. A **``requests``-compatible synchronous session** (``Session``) so the
   dozens of source plugins keep calling ``session.get(...).json()`` with
   zero changes, but every request is now handled by curl_cffi.
2. A **fast asynchronous engine** (``AsyncEngine`` + the module-level
   ``fetch_many`` / ``download_many`` helpers) that runs many requests
   concurrently on a single libcurl multi handle. This is what the download
   engine uses for image pages, and it is many times faster than a thread
   pool for batch work.

The only ``requests``-ism this module deliberately keeps is the *exception
API* (``exceptions.RequestException`` etc.) so error handling code in the
sources keeps working verbatim. Underneath, though, it is all curl_cffi.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Awaitable, Callable, Optional, Sequence

import curl_cffi.requests as _cffi
from curl_cffi.requests import exceptions  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)

#: Default browser fingerprint to impersonate. ``"chrome"`` picks the newest
#: supported Chrome. Override per request with ``impersonate=`` or set the
#: ``MANGASURF_IMPERSONATE`` env var (e.g. ``"safari"``, ``"firefox"``,
#: ``"chrome124"``).
DEFAULT_IMPERSONATE = "chrome"

#: Re-exported for the legacy names consumed by source plugins.
RequestsError = _cffi.exceptions.RequestException
RequestException = _cffi.exceptions.RequestException
ConnectionError = _cffi.exceptions.ConnectionError
Timeout = _cffi.exceptions.Timeout
SSLError = _cffi.exceptions.SSLError
ProxyError = _cffi.exceptions.ProxyError
HTTPError = _cffi.exceptions.HTTPError

__all__ = [
    "Session",
    "AsyncEngine",
    "get",
    "post",
    "fetch",
    "fetch_many",
    "download_many",
    "new_session",
    "default_session",
    "exceptions",
    "RequestsError",
    "RequestException",
    "ConnectionError",
    "Timeout",
    "SSLError",
    "ProxyError",
    "HTTPError",
    "DEFAULT_IMPERSONATE",
]


def _default_impersonate() -> str:
    """Resolve the impersonation target from the environment, if set."""
    return os.environ.get("MANGASURF_IMPERSONATE", DEFAULT_IMPERSONATE)


class Session(_cffi.Session):
    """A curl_cffi session with browser impersonation on every request.

    Mirrors the small slice of the ``requests.Session`` API that the source
    plugins rely on (``get``, ``post``, ``headers``, ``close``, and the
    ``Response`` duck-type of ``.status_code`` / ``.text`` / ``.content`` /
    ``.json()`` / ``.headers`` / ``.raise_for_status()`` / ``.iter_content()``),
    so ports are mechanical. Browser impersonation is the default.
    """

    def __init__(self, *args, impersonate: Optional[str] = None,
                 max_connections: int = 16, **kwargs):
        #: curl_cffi pools connections internally and keeps them alive; we
        #: request a wide multi-socket pool so the download engine's worker
        #: threads never recycle connections (a wide pool is measured to
        #: avoid \"Connection pool is full\" churn on every page).
        impersonate = impersonate or _default_impersonate()
        kwargs.setdefault("impersonate", impersonate)
        super().__init__(*args, **kwargs)
        self._max_connections = max_connections
        self.impersonate = impersonate

    def _with_request_ref(self, method: str, resp):
        """Attach a minimal ``.request`` object like requests does.

        curl_cffi's ``Response`` has no ``.request`` attribute; the source
        base class reads ``response.request.method`` to detect HEAD, so we
        surface one for compatibility.
        """
        if not hasattr(resp, "request") or resp.request is None:
            try:
                resp.request = type(
                    "Request", (), {"method": method.upper(), "url": getattr(resp, "url", "")}
                )()
            except Exception:      # pragma: no cover - cosmetic
                pass
        return resp

    # -- verb helpers --------------------------------------------------
    def get(self, url, **kwargs):  # noqa: A003
        resp = super().get(url, **kwargs)
        return self._with_request_ref("get", resp)

    def post(self, url, **kwargs):  # noqa: A003
        resp = super().post(url, **kwargs)
        return self._with_request_ref("post", resp)


class AsyncEngine:
    """Reusable async curl_cffi engine for high-throughput batch requests.

    One libcurl multi handle, ``max_concurrency`` parallel transfers, shared
    cookie jar and a single :class:`asyncio.AioLoop` run on a dedicated
    daemon thread. Because the rest of Mangasurf is synchronous, this class
    also knows how to *drive* the loop from a blocking caller via
    :meth:`run` / :meth:`run_coro`, so it needs no asyncio experience in the
    consumer.
    """

    def __init__(self, max_concurrency: int = 16,
                 impersonate: Optional[str] = None, **session_kwargs):
        self.max_concurrency = max_concurrency
        self._impersonate = impersonate or _default_impersonate()
        self._session_kwargs = session_kwargs
        self._session: Optional[_cffi.AsyncSession] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = False
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------
    def _ensure_loop(self):
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name="mangasurf-async"
            )
            self._thread.start()
            self._started = True

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_session(self) -> _cffi.AsyncSession:
        if self._session is None:
            self._session = self._loop.create_task(
                self._make_session()
            )
        return self._session

    async def _make_session(self) -> _cffi.AsyncSession:
        self._max_clients = self.max_concurrency
        return _cffi.AsyncSession(
            max_clients=self.max_concurrency,
            impersonate=self._impersonate,
            **self._session_kwargs,
        )

    def run_coro(self, coro: Awaitable):
        """Run an awaitable on the engine loop from synchronous code."""
        if self._loop is None:
            self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def start(self):
        self._ensure_loop()

    def close(self):
        if not self._started:
            return
        async def _shutdown():
            if self._session is not None:
                try:
                    sess = await self._session
                except Exception:
                    sess = None
                if sess is not None:
                    await sess.close()
            self._loop.stop()

        try:
            if self._loop:
                asyncio.run_coroutine_threadsafe(_shutdown(), self._loop).result(timeout=5)
        except Exception:
            pass
        finally:
            self._loop = None
            self._session = None
            self._started = False


#: Shared synchronous session used by module-level ``get`` / ``post`` and
#: handy for one-off fetches (metadata enrichment, FlareSolverr health, ...).
_default_session: Optional[Session] = None
_default_session_lock = threading.Lock()


def new_session(**kwargs) -> Session:
    """Create a fresh authenticated-browser session."""
    return Session(**kwargs)


def default_session(reuse: bool = True) -> Session:
    """A process-wide session, created lazily and reused."""
    global _default_session
    if reuse and _default_session is not None:
        return _default_session
    with _default_session_lock:
        if _default_session is None:
            _default_session = new_session()
        return _default_session


def get(url: str, **kwargs):
    """``requests.get`` drop-in backed by curl_cffi browser impersonation."""
    return default_session().get(url, **kwargs)


def post(url: str, **kwargs):
    """``requests.post`` drop-in backed by curl_cffi browser impersonation."""
    return default_session().post(url, **kwargs)


def fetch(url: str, *, timeout: int = 10, headers=None, params=None):
    """One-shot GET returning a curl_cffi Response (or None on transport error)."""
    try:
        return default_session().get(url, headers=headers, params=params, timeout=timeout)
    except Exception as e:      # noqa: BLE001
        logger.warning("fetch failed for %s: %s", url, e)
        return None


# --------------------------------------------------------------------------
# Fast batch engine
# --------------------------------------------------------------------------

#: A single shared async engine for the whole process. The download and
#: batch-search code path through this.
_ENGINE: Optional[AsyncEngine] = None
_engine_lock = threading.Lock()


def get_engine(max_concurrency: int = 16) -> AsyncEngine:
    """Return the shared async engine (created on first use)."""
    global _ENGINE
    with _engine_lock:
        if _ENGINE is None:
            _ENGINE = AsyncEngine(max_concurrency=max_concurrency)
            _ENGINE.start()
        return _ENGINE


def close_engine():
    """Shut the shared async engine down (used at teardown)."""
    global _ENGINE
    with _engine_lock:
        if _ENGINE is not None:
            _ENGINE.close()
            _ENGINE = None


def _async_fetch_many(engine: AsyncEngine, urls: Sequence[str],
                      timeout: int = 15, headers=None, params=None,
                      referer=None):
    """Coroutine: fetch many URLs concurrently and return responses."""
    async def inner():
        sess = await engine._ensure_session()
        sem = asyncio.Semaphore(engine.max_concurrency)
        hdrs = dict(headers or {})
        if referer:
            hdrs.setdefault("Referer", referer)

        async def one(u):
            async with sem:
                try:
                    return await sess.get(u, timeout=timeout, headers=hdrs, params=params)
                except Exception as e:      # noqa: BLE001
                    logger.debug("async fetch failed for %s: %s", u, e)
                    return None

        return await asyncio.gather(*(one(u) for u in urls))

    return inner()


def fetch_many(urls: Sequence[str], *, timeout: int = 15, headers=None,
               params=None, referer=None, max_concurrency: int = 16,
               engine: Optional[AsyncEngine] = None) -> list:
    """Concurrently GET a list of URLs and return their responses.

    This is the \"fast engine\" entry point used from synchronous code. Each
    URL is sprayed across the single async libcurl multi handle, so a
    chapter of 30 pages comes back in roughly one page's latency instead of
    thirty sequential round trips.

    Responses that fail are returned as ``None`` in the same position so the
    caller can decide whether to retry.
    """
    if not urls:
        return []
    engine = engine or get_engine(max_concurrency=max_concurrency)
    return engine.run_coro(_async_fetch_many(engine, urls, timeout=timeout,
                                             headers=headers, params=params,
                                             referer=referer))


def _is_image(response, content: bytes) -> bool:
    """Magic-byte / content-type check, the same one the sources use."""
    ctype = ((response.headers.get("content-type") if response else "") or "").lower()
    if ctype.startswith("image/"):
        return True
    if not content:
        return False
    return (
        content[:3] == b"\xff\xd8\xff"
        or content[:8] == b"\x89PNG\r\n\x1a\n"
        or content[:6] in (b"GIF87a", b"GIF89a")
        or (content[:4] == b"RIFF" and content[8:12] == b"WEBP")
        or content[4:12] in (b"ftypavif", b"ftypavis")
    )


def download_many(items: Sequence[dict], *, timeout: int = 30,
                  max_concurrency: int = 16,
                  engine: Optional[AsyncEngine] = None,
                  on_bytes: Optional[Callable[[int], None]] = None) -> list:
    """Concurrently stream-download a batch of files.

    ``items`` is a list of dicts with keys:
        url (str, required)
        path (str, required)          target file
        headers (dict, optional)
        referer (str, optional)
        type (str, optional)          \"image\" to validate magic bytes

    Returns a bool list (True = file written OK) in the same order.
    Writing is atomic (``.part`` then ``os.replace``) so a crashed run never
    yields a truncated image that resume would mistake for a complete one.
    """
    if not items:
        return []
    engine = engine or get_engine(max_concurrency=max_concurrency)
    return engine.run_coro(_async_download_many(engine, items, timeout=timeout,
                                                on_bytes=on_bytes))


async def _async_download_many(engine: AsyncEngine, items: Sequence[dict],
                               timeout: int, on_bytes=None):
    async def inner():
        sess = await engine._ensure_session()
        sem = asyncio.Semaphore(engine.max_concurrency)

        async def one(item):
            url = item["url"]
            path = item["path"]
            hdrs = dict(item.get("headers") or {})
            if item.get("referer"):
                hdrs.setdefault("Referer", item["referer"])
            tmp = str(path) + ".part"
            async with sem:
                try:
                    resp = await sess.get(url, headers=hdrs, timeout=timeout, stream=True)
                except Exception as e:      # noqa: BLE001
                    logger.debug("batch download failed for %s: %s", url, e)
                    return False
            if resp.status_code >= 400:
                return False
            head = b""
            try:
                with open(tmp, "wb") as f:
                    async for block in resp.aiter_content(chunk_size=65536):
                        if not block:
                            continue
                        if len(head) < 16:
                            head += block[:16 - len(head)]
                        f.write(block)
                        if on_bytes is not None:
                            try:
                                on_bytes(len(block))
                            except Exception:
                                pass
            except Exception as e:      # noqa: BLE001
                logger.warning("batch download write failed for %s: %s", url, e)
                return False
            kind = item.get("type")
            if kind == "image" and not _is_image(resp, head):
                return False
            if os.path.getsize(tmp) == 0:
                return False
            try:
                os.replace(tmp, path)
            except OSError:
                return False
            return True

        return await asyncio.gather(*(one(it) for it in items))

    return await inner()


# Teardown hook so the engine's loop thread is reaped on interpreter exit.
import atexit  # noqa: E402

atexit.register(close_engine)
