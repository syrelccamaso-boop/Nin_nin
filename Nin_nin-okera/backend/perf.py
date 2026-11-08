"""
Centrum Laboratory - speed helpers shared by the services (backend/perf.py).

    cached(key, ttl, loader)   short-lived in-memory cache of read results
                               (single-flight: concurrent misses load ONCE)
    invalidate()               forget every cached result (main.py calls this
                               around every POST / PATCH / PUT / DELETE)
    lookup(key, ttl, loader)   same, for rarely-changing lookup tables; it is
                               NOT cleared by invalidate()
    parallel(name=fn, ...)     run several independent Supabase reads at once
    submit / submit_read       start one task in the pool
    background(fn, *args)      run best-effort work after the response
    stats()                    hit / miss / wait counters per cache key

Rules
-----
* Only request threads may wait on parallel(). Code that runs INSIDE
  parallel() or background() must not call parallel() itself.
* The cache lives in this process. With several uvicorn workers each worker
  has its own cache, so another worker may show data up to `ttl` seconds old
  after a change. Run ONE worker, or keep ttl small, if that matters.
* Never cache credentials or permissions here (auth_service has its own
  60 s token cache that is cleared on every account write).

Fix in this version: `lookup` had been decorated with functools.lru_cache.
Callers pass a new lambda / nested function every call, so lru_cache never
hit for them (ReportStatus was re-read from Supabase on almost every call),
while for stable loaders it returned the SAME mutable object forever,
ignoring the TTL and invalidate_lookups(). The decorator is removed.
"""

from __future__ import annotations

import copy
import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger("centrum.perf")


# =========================================================
# STATS (cache hit / miss rate)
# =========================================================

_stats_lock = threading.Lock()
_stats: dict[str, dict[str, int]] = {}


def _count(key: str, what: str) -> None:
    with _stats_lock:
        row = _stats.setdefault(key, {"hit": 0, "miss": 0, "wait": 0})
        row[what] += 1


def stats() -> dict[str, dict[str, Any]]:
    """{key: {hit, miss, wait, hit_rate}}. 'wait' = a request that found
    the key being loaded by another request and reused its result."""
    with _stats_lock:
        out = {}
        for key, row in _stats.items():
            total = row["hit"] + row["miss"] + row["wait"]
            out[key] = {
                **row,
                "hit_rate": (
                    round((row["hit"] + row["wait"]) / total, 3) if total else 0.0
                ),
            }
        return out


# =========================================================
# CACHE (invalidated after every change)
# =========================================================

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}

# Bumped by invalidate(). A result loaded while a change was being saved is
# not kept, so the cache can never hold data from before that change.
_generation = 0

# One lock per cache key (single-flight). The keys are a small fixed set.
_load_locks: dict[str, threading.Lock] = {}


def _load_lock(key: str) -> threading.Lock:
    with _lock:
        lock = _load_locks.get(key)
        if lock is None:
            lock = _load_locks[key] = threading.Lock()
        return lock


def cached(
    key: str, ttl: float, loader: Callable[[], Any], copy_result: bool = True
) -> Any:
    """
    Return the cached result for `key`, or call `loader()` and keep it for
    `ttl` seconds. Concurrent misses for the same key run `loader()` once.

    copy_result=True returns a deep copy (callers may mutate it). Pass False
    only for results that are serialised / read and never modified: it avoids
    deep-copying thousands of rows on every hit.
    """

    now = time.monotonic()

    with _lock:
        hit = _store.get(key)

    if hit is not None and hit[0] > now:
        _count(key, "hit")
        return copy.deepcopy(hit[1]) if copy_result else hit[1]

    with _load_lock(key):

        with _lock:
            hit = _store.get(key)
            generation = _generation

        if hit is not None and hit[0] > time.monotonic():
            _count(key, "wait")  # another request loaded it while we waited
            return copy.deepcopy(hit[1]) if copy_result else hit[1]

        _count(key, "miss")
        value = loader()

        with _lock:
            if generation == _generation:
                _store[key] = (time.monotonic() + ttl, value)

    return copy.deepcopy(value) if copy_result else value


def invalidate() -> None:
    """Forget every cached result (called after any change).
    Lookup data cached with lookup() is kept."""

    global _generation

    with _lock:
        _generation += 1
        _store.clear()


# ---------------------------------------------------------
# Lookup tables (ReportStatus, ReportIssues, ReportCategory...)
# ---------------------------------------------------------

_lookups: dict[str, tuple[float, Any]] = {}


def lookup(key: str, ttl: float, loader: Callable[[], Any]) -> Any:
    """Like cached(), for rarely-changing lookup tables. Expires with time
    or invalidate_lookups(); not cleared by invalidate()."""

    now = time.monotonic()

    with _lock:
        hit = _lookups.get(key)

    if hit is not None and hit[0] > now:
        _count("lookup:" + key, "hit")
        return copy.deepcopy(hit[1])

    with _load_lock("lookup:" + key):

        with _lock:
            hit = _lookups.get(key)

        if hit is not None and hit[0] > time.monotonic():
            _count("lookup:" + key, "wait")
            return copy.deepcopy(hit[1])

        _count("lookup:" + key, "miss")
        value = loader()

        with _lock:
            _lookups[key] = (time.monotonic() + ttl, value)

    return copy.deepcopy(value)


def invalidate_lookups() -> None:
    """Forget the cached lookup tables (after adding a row to one)."""

    with _lock:
        _lookups.clear()


# =========================================================
# PARALLEL READS
# =========================================================

_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="centrum-db")

PARALLEL_READS = os.getenv("CENTRUM_PARALLEL_READS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


def _read_with_retry(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Run one READ, trying once more if it fails (reads change nothing)."""

    try:
        return fn(*args, **kwargs)
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Read %s failed (%s: %s) - trying once more.",
            getattr(fn, "__name__", "task"),
            type(error).__name__,
            error,
        )
        time.sleep(0.3)
        return fn(*args, **kwargs)


def parallel(**tasks: Callable[[], Any]) -> dict[str, Any]:
    """
    Run independent loaders at the same time and return their results by name.
    The first error is raised after all of them have finished.
    Must not be called from inside the pool (see module docstring).
    """

    if not PARALLEL_READS:
        return {name: fn() for name, fn in tasks.items()}

    futures = {name: _POOL.submit(_read_with_retry, fn) for name, fn in tasks.items()}

    results: dict[str, Any] = {}
    first_error: BaseException | None = None

    for name, future in futures.items():
        try:
            results[name] = future.result()
        except BaseException as error:  # noqa: BLE001 - re-raised below
            if first_error is None:
                first_error = error

    if first_error is not None:
        raise first_error

    return results


def submit(fn: Callable[..., Any], *args, **kwargs):
    """Start one task in the pool; call .result() on the returned future.
    Not retried, so it is safe for writes too. For reads use submit_read()."""

    return _start(fn, args, kwargs)


def submit_read(fn: Callable[..., Any], *args, **kwargs):
    """Like submit(), for a READ: it is tried once more if it fails."""

    return _start(_read_with_retry, (fn, *args), kwargs)


def _start(fn: Callable[..., Any], args, kwargs):
    if not PARALLEL_READS:
        done: Future = Future()
        try:
            done.set_result(fn(*args, **kwargs))
        except BaseException as error:  # noqa: BLE001
            done.set_exception(error)
        return done

    return _POOL.submit(fn, *args, **kwargs)


# =========================================================
# BACKGROUND WORK
# =========================================================

_BACKGROUND = ThreadPoolExecutor(max_workers=4, thread_name_prefix="centrum-bg")


def _run_logged(fn: Callable[..., Any], args, kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:  # noqa: BLE001
        logger.exception("Background task %s failed", getattr(fn, "__name__", fn))


def background(fn: Callable[..., Any], *args, **kwargs) -> None:
    """Run best-effort work (notifications) without making the request wait.
    Only for work whose failure the user doesn't need to see."""

    _BACKGROUND.submit(_run_logged, fn, args, kwargs)
