"""
State Decay + Per-Store Garbage Collection.

Implements the Amebo BOUNDARIES design decision (2026-06-06):

    "Amebo holds as little state as it can. Its own working state decays
    fairly quickly unless Amebo judges there is a reason to keep something;
    that judgment is part of its job. Anything worth keeping is crystallized
    out to a system of record and the rest decays. Garbage collection is NOT
    a single mechanism — each system of record runs its own GC appropriate to
    it, INCLUDING Amebo's own Abra working-memory scope. Do not assume one GC
    policy fits every store."

The pieces:

- ``policy``   — the ``GcPolicy`` protocol every store implements, the
                 ``GcReport`` result type, and the ``StoreRegistry`` that
                 holds one policy per store.
- ``judgment`` — the pluggable ``should_keep(item) -> bool`` retention hook.
                 Default is a cheap conservative heuristic; the real version
                 can call an LLM later through the same seam.
- ``stores``   — concrete policies: conversation threads/turns, goal_events
                 (audit), and Amebo's own abra working-memory scope/catcode.
- ``runner``   — ``run_gc(...)`` iterates the registered stores and expires
                 per each store's own policy. Callable from the existing
                 scheduler tick (see docs/STATE_DECAY_GC.md). Not a daemon.
"""

from src.services.state_decay.policy import (
    GcPolicy,
    GcReport,
    StoreRegistry,
    default_registry,
)
from src.services.state_decay.judgment import (
    RetentionJudge,
    default_should_keep,
    set_retention_judge,
    get_retention_judge,
)
from src.services.state_decay.runner import run_gc

__all__ = [
    "GcPolicy",
    "GcReport",
    "StoreRegistry",
    "default_registry",
    "RetentionJudge",
    "default_should_keep",
    "set_retention_judge",
    "get_retention_judge",
    "run_gc",
]
