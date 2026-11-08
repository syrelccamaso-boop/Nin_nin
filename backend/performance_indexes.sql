"""
Centrum Laboratory - speed helpers shared by the services.

    cached(key, ttl, loader)   short-lived in-memory cache of read results
    invalidate()               forget every cached result (main.py calls this
                               around every POST / PATCH / PUT / DELETE)
    parallel(name=fn, ...)     run several independent Supabase reads at once
    background(fn, *args)      run best-effort work (notifications) after the
                               response, so the user doesn't wait for it

Why
---
Every Supabase query is a network round trip. The dashboards made 8-10 of
them one after another, and every dashboard (and every user) reloaded the
same tables on every click.

Rules
-----
* Only request threads may wait on parallel(). Code that runs INSIDE
  parallel() or background() must not call parallel() itself - with many
  users at once the pool could fill up with threads waiting on each other.
* The cache lives in this server process. With several uvicorn workers each
  worker has its own cache, so another worker may show data up to `ttl`
  seconds old after a change. With the default single worker this can't
  happen, because every change clears the cache.
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
# CACHE
# =========================================================

_lock = threading.Lock()
_store: dict[str, tuple[float, Any]] = {}

# Bumped by invalidate(). A result loaded while a change was being saved is
# not kept, so the cache can never hold data from before that change.
_generation = 0


def cached(key: str, ttl: float, loader: Callable[[], Any], copy_result: bool = True) -> Any:
    """
    Return the cached result for `key`, or call `loader()` and keep its
    result for `ttl` seconds.

    A deep copy is returned by default, so callers may change the data
    without changing what other requests get from the cache.
    """

    now = time.monotonic()

    with _lock:
        hit = _store.get(key)
        generation = _generation

    if hit is not None and hit[0] > now:
        return copy.deepcopy(hit[1]) if copy_result else hit[1]

    value = loader()

    with _lock:
        if generation == _generation:
            _store[key] = (time.monotonic() + ttl, value)

    return copy.deepcopy(value) if copy_result else value


def invalidate() -> None:
    """Forget every cached result (called after any change).

    Lookup data cached with lookup() is kept - see below."""

    global _generation

    with _lock:
        _generation += 1
        _store.clear()


# ---------------------------------------------------------
# Lookup tables (ReportStatus, ReportIssues, ...)
# ---------------------------------------------------------
#
# These almost never change, and they are needed by the very requests that
# change data (which clear the normal cache first). They are kept in their
# own cache that only expires with time, or with invalidate_lookups() when
# code adds a row to one of them.

_lookups: dict[str, tuple[float, Any]] = {}


def lookup(key: str, ttl: float, loader: Callable[[], Any]) -> Any:
    """Like cached(), for rarely-changing lookup tables."""

    now = time.monotonic()

    with _lock:
        hit = _lookups.get(key)

    if hit is not None and hit[0] > now:
        return copy.deepcopy(hit[1])

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

# Supabase reads are network-bound, so threads run them in parallel well.
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="centrum-db")

# Emergency switch: put CENTRUM_PARALLEL_READS=0 in .env to turn parallel
# reads off (everything then runs one after another, like before).
PARALLEL_READS = os.getenv("CENTRUM_PARALLEL_READS", "1").strip().lower() not in {
    "0", "false", "no", "off",
}


def _read_with_retry(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """
    Run one READ, trying once more if it fails.

    Reads change nothing, so a second try is always safe. It covers short
    network hiccups (for example Supabase closing an idle connection).
    """

    try:
        return fn(*args, **kwargs)
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "Read %s failed (%s: %s) - trying once more.",
            getattr(fn, "__name__", "task"), type(error).__name__, error,
        )
        time.sleep(0.3)
        return fn(*args, **kwargs)


def parallel(**tasks: Callable[[], Any]) -> dict[str, Any]:
    """
    Run independent loaders at the same time and return their results by
    name:

        data = parallel(computers=_load_computers, users=_load_users)
        data["computers"], data["users"]

    The first error raised by any loader is raised here (after all of them
    have finished), exactly as if they had run one after another.
    """

    if not PARALLEL_READS:
        # Switched off in .env: run the loaders one after another, exactly
        # like the code did before (slower, but no threads).
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
        except BaseException as error:  # noqa: BLE001 - raised by .result()
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
    except Exception:  # noqa: BLE001 - background work must never crash anything
        logger.exception("Background task %s failed", getattr(fn, "__name__", fn))


def background(fn: Callable[..., Any], *args, **kwargs) -> None:
    """
    Run best-effort work (notifications) without making the request wait.

    Only use this for work whose failure the user doesn't need to see.
    """

    _BACKGROUND.submit(_run_logged, fn, args, kwargs)