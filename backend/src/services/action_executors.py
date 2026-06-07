"""Executor registry — maps a gated ``action_type`` to the function that
performs it AFTER human approval.

Why this exists: a gated tool builds its executor as a closure at draft time
(see ``src/tools/gated_actuators.py``), but by the time a human approves the
pending_action, that closure is gone — only the stored ``payload`` remains.
The approval API therefore needs to look the executor up by ``action_type`` and
reconstruct the side effect from the payload. This registry is that lookup.

Encapsulation: each capability registers its own executor next to its tool, so
adding a capability is one place, not three. The executor signature matches
``DraftApprovalService.Executor`` exactly — ``fn(action: dict) -> str`` — and
reads everything it needs from ``action["payload"]``.
"""

from __future__ import annotations

import importlib
import logging
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# action_type -> executor(action) -> human-readable result string
Executor = Callable[[Dict], str]

_EXECUTORS: Dict[str, Executor] = {}
_loaded = False


def register_executor(action_type: str, fn: Executor) -> None:
    """Register the executor for an action type. Called at import time by the
    module that owns the capability (e.g. gated_actuators)."""
    if action_type in _EXECUTORS:
        logger.warning("Executor for %r registered twice, overwriting", action_type)
    _EXECUTORS[action_type] = fn


def _ensure_loaded() -> None:
    """Import the modules that register executors. Lazy + idempotent so this
    module has no import-time dependency on the tool modules (avoids cycles)."""
    global _loaded
    if _loaded:
        return
    # Importing the actuators triggers their register_executor() calls.
    importlib.import_module("src.tools.gated_actuators")
    _loaded = True


def get_executor(action_type: str) -> Optional[Executor]:
    """Return the executor for an action type, or None if none is registered
    (in which case an approved action cannot be auto-executed)."""
    _ensure_loaded()
    return _EXECUTORS.get(action_type)


def has_executor(action_type: str) -> bool:
    _ensure_loaded()
    return action_type in _EXECUTORS
