"""
Coding-agent credential config.

For now the Anthropic credential is read from the environment (no per-org
credential store yet). Prefers a subscription Agent SDK token when present
(CLAUDE_CODE_OAUTH_TOKEN, from `claude setup-token`, available 2026-06-15),
otherwise an API key (ANTHROPIC_API_KEY).

Per-org / per-user credential storage is a later step; isolating credential
resolution here means only this function changes when that lands.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AnthropicCredential:
    token: str
    kind: str  # "oauth_token" | "api_key"


def get_anthropic_credential() -> Optional[AnthropicCredential]:
    """Resolve the Anthropic credential from env, or None if none is set."""
    oauth = os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
    if oauth:
        return AnthropicCredential(token=oauth, kind="oauth_token")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        return AnthropicCredential(token=api_key, kind="api_key")
    return None
