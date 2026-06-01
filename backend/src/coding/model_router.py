"""
Dispatch-time model routing.

The model is chosen when an intention thread opens and kept stable for the life
of the session (prompt cache is per-model; switching mid-session costs a cache
rewrite). The default is conservative: a misroute that sends a hard task to a
cheap model costs more in flailing than it saves, so we only pick the cheap tier
on an explicit signal.

Routing is intentionally simple and pluggable. Start with explicit hints and a
narrow keyword heuristic; richer judgment can replace `choose_model` later
without touching callers.
"""

import logging
import os
import re
from typing import Optional

from src.coding.models import Model

logger = logging.getLogger(__name__)

# Default tier when nothing says otherwise. Overridable via env for the whole
# deployment without code changes.
DEFAULT_MODEL = os.getenv("CODING_DEFAULT_MODEL", Model.OPUS.value)
CHEAP_MODEL = os.getenv("CODING_CHEAP_MODEL", Model.HAIKU.value)

# Narrow set of signals that a task is mechanical/low-risk enough for the cheap
# tier. Kept deliberately small; expand only with evidence.
_EASY_PATTERNS = [
    r"\btypo\b", r"\brename\b", r"\bcomment\b", r"\bformat(ting)?\b",
    r"\bbump (the )?version\b", r"\blint\b", r"\bdocstring\b",
]
_EASY_RE = re.compile("|".join(_EASY_PATTERNS), re.IGNORECASE)


def choose_model(prompt: str, hint: Optional[str] = None) -> str:
    """
    Return the model id for a new session.

    hint: explicit caller override. Accepts a Model value/name (e.g. "haiku",
    "opus", or a full model id). Wins over the heuristic.
    """
    if hint:
        resolved = _resolve_hint(hint)
        if resolved:
            logger.info("Model routed by hint %r -> %s", hint, resolved)
            return resolved
        logger.warning("Unrecognized model hint %r; falling back to heuristic", hint)

    if _EASY_RE.search(prompt or ""):
        logger.info("Model routed cheap (mechanical task signal) -> %s", CHEAP_MODEL)
        return CHEAP_MODEL

    return DEFAULT_MODEL


def _resolve_hint(hint: str) -> Optional[str]:
    h = hint.strip().lower()
    by_name = {
        "opus": Model.OPUS.value,
        "sonnet": Model.SONNET.value,
        "haiku": Model.HAIKU.value,
        "cheap": CHEAP_MODEL,
        "default": DEFAULT_MODEL,
    }
    if h in by_name:
        return by_name[h]
    # Allow passing a full model id directly.
    if any(h == m.value for m in Model):
        return h
    return None
