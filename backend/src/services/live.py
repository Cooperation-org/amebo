"""Telling a browser something changed, the moment it changes.

The list used to find out on a timer: every browser asked again every sixty
seconds whether anything had happened. Most of those asks were wasted, and the
one change a person is actually waiting for — amebo has a question for you —
took up to a minute to appear.

What this is, and what it deliberately is not:

  **Amebo's own changes push.** A goal reaching ``waiting_user``, a draft being
  handed back, an edit a person just pressed: amebo knows the instant those
  happen, so it says so and the browser refetches at once.

  **Other systems' changes do not.** Taiga and Odoo have no change feed pointed
  at us. Something edited directly in Marten or the CRM is still found by the
  browser's fallback refresh, which is now slow rather than frequent, because it
  is the rare case rather than the normal one.

One process, one event loop (src/main.py runs a single uvicorn Server), so
subscribers live in memory here. If amebo ever runs more than one process this
has to move behind something shared — Postgres LISTEN/NOTIFY is the obvious
choice since the database is already there — and nothing else needs to change:
publish() and subscribe() are the whole surface.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# {org_id: [(queue, the loop that queue belongs to)]}
_subscribers: Dict[int, List[Tuple["asyncio.Queue[str]", asyncio.AbstractEventLoop]]] = {}

# A slow subscriber must never hold up a write. Its queue is small on purpose:
# the message carries no content, only "look again", so dropping a duplicate
# costs nothing.
_QUEUE_DEPTH = 8


def subscribe(org_id: int) -> "asyncio.Queue[str]":
    """A queue of change notices for one org. The caller must unsubscribe."""
    queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=_QUEUE_DEPTH)
    _subscribers.setdefault(org_id, []).append((queue, asyncio.get_running_loop()))
    return queue


def unsubscribe(org_id: int, queue: "asyncio.Queue[str]") -> None:
    remaining = [(q, l) for (q, l) in _subscribers.get(org_id, []) if q is not queue]
    if remaining:
        _subscribers[org_id] = remaining
    else:
        _subscribers.pop(org_id, None)


def publish(org_id: Optional[int], what: str = "work-list") -> None:
    """Say that ``what`` changed for this org.

    Safe to call from anywhere, including the threadpool a sync route body runs
    in — each subscriber is woken on its own loop. Never raises: a notification
    failing must not fail the write that caused it.
    """
    if not org_id:
        return
    for queue, loop in list(_subscribers.get(org_id, [])):
        try:
            loop.call_soon_threadsafe(_offer, queue, what)
        except RuntimeError:  # loop already closed; the stream is gone
            unsubscribe(org_id, queue)
        except Exception as exc:  # noqa: BLE001
            logger.debug("live: could not notify a subscriber: %s", exc)


def _offer(queue: "asyncio.Queue[str]", what: str) -> None:
    """Drop rather than block. A backed-up subscriber has already been told to
    look again; telling it twice more adds nothing."""
    try:
        queue.put_nowait(what)
    except asyncio.QueueFull:
        pass


def subscriber_count(org_id: int) -> int:
    return len(_subscribers.get(org_id, []))
