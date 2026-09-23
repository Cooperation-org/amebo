"""Shared LLM client factory — the one place that decides which provider
(key + endpoint) amebo's conversation/QA/goal paths talk to.

Provider is selected by AMEBO_LLM_PROVIDER (read per-call, no restart needed
beyond the process picking up .env):

  kimi (default)      — KIMI_API_KEY against KIMI_ANTHROPIC_BASE_URL
                        (Moonshot's Anthropic-compatible endpoint). claude-*
                        model ids do not exist there, so every requested model
                        resolves to KIMI_MODEL (default kimi-k3).
  anthropic           — ANTHROPIC_API_KEY against api.anthropic.com;
                        claude-* model ids pass through unchanged.
  minimax             — MINIMAX_API_KEY against MINIMAX_ANTHROPIC_BASE_URL
                        (MiniMax's Anthropic-compatible endpoint). Same model
                        remapping, via MINIMAX_MODEL (default MiniMax-M3 — M2
                        prefixes answers with thinking blocks, M3 answers in
                        plain text blocks).

Reasoning models put a `thinking` block FIRST in content; kimi-k3 always does
(its API reports supports_thinking_type=only — thinking cannot be disabled).
`response.content[0].text` therefore raises on those providers. Read answer
text with first_text() instead, never by index.

This is the first slice of the model/key switching described in
docs/AMEBO_PREFERENCES.md section 6; finer-grained per-purpose routing can
grow here without touching call sites again.
"""

import logging
import os
from typing import Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)

KIMI_DEFAULT_MODEL = "kimi-k3"
KIMI_DEFAULT_BASE_URL = "https://api.moonshot.ai/anthropic"
MINIMAX_DEFAULT_MODEL = "MiniMax-M3"
MINIMAX_DEFAULT_BASE_URL = "https://api.minimax.io/anthropic"

# provider -> (key env var, base-url env var, base-url default, model env var,
#              model default). anthropic is absent: it needs no base_url and
#              passes model ids through unchanged.
_COMPATIBLE_PROVIDERS = {
    "kimi": ("KIMI_API_KEY", "KIMI_ANTHROPIC_BASE_URL", KIMI_DEFAULT_BASE_URL,
             "KIMI_MODEL", KIMI_DEFAULT_MODEL),
    "minimax": ("MINIMAX_API_KEY", "MINIMAX_ANTHROPIC_BASE_URL", MINIMAX_DEFAULT_BASE_URL,
                "MINIMAX_MODEL", MINIMAX_DEFAULT_MODEL),
}


def get_provider() -> str:
    return os.getenv("AMEBO_LLM_PROVIDER", "kimi").strip().lower()


def get_llm_client() -> Optional[Anthropic]:
    """Anthropic-SDK client for the configured provider, or None when the
    provider's key is missing (callers already handle a None client)."""
    provider = get_provider()
    spec = _COMPATIBLE_PROVIDERS.get(provider)
    if spec:
        key_var, url_var, url_default, _, _ = spec
        api_key = os.getenv(key_var)
        if not api_key:
            logger.warning("AMEBO_LLM_PROVIDER=%s but %s not set", provider, key_var)
            return None
        return Anthropic(api_key=api_key, base_url=os.getenv(url_var, url_default))
    if provider != "anthropic":
        logger.warning("Unknown AMEBO_LLM_PROVIDER=%r, falling back to anthropic", provider)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set")
        return None
    return Anthropic(api_key=api_key)


def resolve_model(requested: str) -> str:
    """Map a requested model id to one the configured provider serves."""
    spec = _COMPATIBLE_PROVIDERS.get(get_provider())
    if spec:
        _, _, _, model_var, model_default = spec
        return os.getenv(model_var, model_default)
    return requested


def first_text(response) -> str:
    """The answer text of a response, skipping thinking/tool_use blocks.

    Never index into content: a reasoning model (kimi-k3 always, MiniMax-M2)
    puts its thinking block at position 0 and that block has no .text.
    """
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""
