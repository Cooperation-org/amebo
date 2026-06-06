"""
Retention judgment — the seam where Amebo decides "is this worth keeping?".

Before letting working-state decay, Amebo can judge whether an item should be
crystallized/kept rather than expired. That judgment is part of Amebo's job
(per the BOUNDARIES design decision). This module defines the seam:

    should_keep(item, *, store) -> bool

The default implementation is a cheap, conservative heuristic that needs no
LLM and no network. A richer implementation (LLM-backed "is this worth
crystallizing to a system of record?") can be swapped in at runtime via
``set_retention_judge`` without touching the runner or any policy.

Convention: ``True`` means KEEP (survive this GC pass). ``False`` means LET IT
DECAY. The default leans toward decay (Amebo holds as little state as it can)
but keeps a few cheap, unambiguous signals.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class RetentionJudge(Protocol):
    """A callable that decides whether an expirable item should be kept."""

    def __call__(self, item: Any, *, store: str) -> bool:
        ...


def _truthy(value: Any) -> bool:
    return bool(value)


def default_should_keep(item: Any, *, store: str) -> bool:
    """
    Cheap conservative default. No LLM, no network. Leans toward decay.

    Signals that say KEEP (any one is enough):

      - The item carries an explicit retention marker the store surfaced:
        ``retained_until`` set and not yet past is treated as "kept" by the
        store's own ``is_durable`` already, but if a policy forwards a raw row
        here we still honor a truthy ``kept`` / ``retained_until`` /
        ``do_not_decay`` field.
      - The item is flagged important in its metadata
        (``metadata.keep`` / ``metadata.pin`` / ``metadata.crystallized``).

    Everything else is allowed to decay. Items are dict-like (DB rows) or
    objects; we read attributes defensively so policies can pass either.
    """
    get = _accessor(item)

    # Explicit, persisted "keep me" markers.
    for marker in ("kept", "retained_until", "do_not_decay"):
        if _truthy(get(marker)):
            return True

    # Metadata-carried importance flags.
    metadata = get("metadata") or {}
    if isinstance(metadata, dict):
        for flag in ("keep", "pin", "pinned", "crystallized", "important"):
            if _truthy(metadata.get(flag)):
                return True

    # Default: let it decay.
    return False


def _accessor(item: Any) -> Callable[[str], Any]:
    """Return a getter that works for dicts and for plain objects."""
    if isinstance(item, dict):
        return lambda key: item.get(key)
    return lambda key: getattr(item, key, None)


# ---------------------------------------------------------------------------
# Pluggable judge: one process-wide judge, swappable at runtime.
# ---------------------------------------------------------------------------

_active_judge: RetentionJudge = default_should_keep


def set_retention_judge(judge: RetentionJudge) -> None:
    """
    Install the active retention judge. Pass ``default_should_keep`` to reset.

    The real version can be an LLM-backed callable; it just has to satisfy the
    ``RetentionJudge`` signature. Installed once at startup (or per-test).
    """
    global _active_judge
    if not callable(judge):
        raise TypeError("retention judge must be callable")
    _active_judge = judge
    logger.info("Retention judge set to %r", getattr(judge, "__name__", judge))


def get_retention_judge() -> RetentionJudge:
    """Return the active retention judge (default if none was installed)."""
    return _active_judge


def should_keep(item: Any, *, store: str) -> bool:
    """
    Delegate to the active judge. A judge that raises is treated as a vote to
    KEEP — failing safe: when in doubt, do not destroy state.
    """
    judge = _active_judge
    try:
        return bool(judge(item, store=store))
    except Exception:
        logger.exception(
            "Retention judge raised on a %s item; keeping it (fail-safe)", store
        )
        return True
