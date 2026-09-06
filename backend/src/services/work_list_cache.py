"""The inbox, pre-assembled.

Assembling the list costs the slowest source (Taiga ~7s, the CRM ~5s), and a
page that takes ten seconds is not used (golda 2026-09-06: "if it's not fast
it's not useful ... pregenerate it, regenerate in the background when things
change, always load fast"). So the assembled list is kept per (org, person):

- a hit is served at once, with its age;
- a hit older than ``STALE_AFTER`` is served and rebuilt in the background;
- every key seen recently is rebuilt on a timer, so the first open of the day
  is warm too;
- a write the person makes through amebo (a mark, an edit, an answer)
  invalidates their key so the next read rebuilds.

Display-only, per docs/DASHBOARD.md: the cached list is what is shown, never
what is acted on — every action re-reads the source it touches.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

STALE_AFTER = 120.0        # seconds before a hit triggers a background rebuild
WARM_EVERY = 600.0         # seconds between timer rebuilds of every known key
FORGET_AFTER = 3 * 86400   # a key nobody opened for three days stops being warmed

_entries: Dict[Tuple[Any, str], Tuple[float, Any]] = {}   # key -> (built_at, value)
_last_seen: Dict[Tuple[Any, str], float] = {}
_building: set = set()
_lock = threading.Lock()


def get(key: Tuple[Any, str]) -> Optional[Tuple[float, Any]]:
    with _lock:
        _last_seen[key] = time.time()
        return _entries.get(key)


def put(key: Tuple[Any, str], value: Any) -> None:
    with _lock:
        _entries[key] = (time.time(), value)


def invalidate(org_id: Any, person: Optional[str] = None) -> None:
    """Drop this person's list (or the whole org's) so the next read rebuilds."""
    with _lock:
        for k in list(_entries):
            if k[0] == org_id and (person is None or k[1] == person):
                _entries.pop(k, None)


def age(key: Tuple[Any, str]) -> Optional[float]:
    hit = _entries.get(key)
    return None if not hit else time.time() - hit[0]


async def rebuild(key: Tuple[Any, str], build: Callable[[], Awaitable[Any]]) -> Optional[Any]:
    """Build once per key at a time; a second caller while one is in flight
    just gets the current entry."""
    with _lock:
        if key in _building:
            return None
        _building.add(key)
    try:
        value = await build()
        put(key, value)
        return value
    except Exception as exc:  # noqa: BLE001 - a failed rebuild keeps the old list
        logger.warning("work-list cache: rebuild failed for %s: %s", key, exc)
        return None
    finally:
        with _lock:
            _building.discard(key)


async def warm_loop(build_for: Callable[[Tuple[Any, str]], Awaitable[Any]]) -> None:
    """Rebuild every recently-seen key on a timer. Runs for the life of the app."""
    while True:
        await asyncio.sleep(WARM_EVERY)
        now = time.time()
        with _lock:
            keys = [k for k, seen in _last_seen.items() if now - seen < FORGET_AFTER]
        for k in keys:
            await rebuild(k, lambda k=k: build_for(k))
