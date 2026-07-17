"""Shared LLM client factory — the one place that decides which provider
(key + endpoint) amebo's conversation/QA/goal paths talk to.

Provider is selected by AMEBO_LLM_PROVIDER (read per-call, no restart needed
beyond the process picking up .env):

  anthropic (default) — ANTHROPIC_API_KEY against api.anthropic.com;
                        claude-* model ids pass through unchanged.
  minimax             — MINIMAX_API_KEY against MINIMAX_ANTHROPIC_BASE_URL
                        (MiniMax's Anthropic-compatible endpoint). claude-*
                        model ids do not exist there, so every requested model
                        resolves to MINIMAX_MODEL (default MiniMax-M3 — M2
                        prefixes answers with thinking blocks, M3 answers in
                        plain text blocks).

This is the first slice of the model/key switching described in
docs/AMEBO_PREFERENCES.md section 6; finer-grained per-purpose routing can
grow here without touching call sites again.
"""

import logging
import os
from typing import Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)

MINIMAX_DEFAULT_MODEL = "MiniMax-M3"
MINIMAX_DEFAULT_BASE_URL = "https://api.minimax.io/anthropic"


def get_provider() -> str:
    return os.getenv("AMEBO_LLM_PROVIDER", "anthropic").strip().lower()


def get_llm_client() -> Optional[Anthropic]:
    """Anthropic-SDK client for the configured provider, or None when the
    provider's key is missing (callers already handle a None client)."""
    provider = get_provider()
    if provider == "minimax":
        api_key = os.getenv("MINIMAX_API_KEY")
        if not api_key:
            logger.warning("AMEBO_LLM_PROVIDER=minimax but MINIMAX_API_KEY not set")
            return None
        base_url = os.getenv("MINIMAX_ANTHROPIC_BASE_URL", MINIMAX_DEFAULT_BASE_URL)
        return Anthropic(api_key=api_key, base_url=base_url)
    if provider != "anthropic":
        logger.warning("Unknown AMEBO_LLM_PROVIDER=%r, falling back to anthropic", provider)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set")
        return None
    return Anthropic(api_key=api_key)


def resolve_model(requested: str) -> str:
    """Map a requested model id to one the configured provider serves."""
    if get_provider() == "minimax":
        return os.getenv("MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL)
    return requested
