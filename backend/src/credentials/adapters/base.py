"""
Adapter contract for OAuth providers.

Each provider implements:
- refresh(payload) → RefreshedTokens
- build_authorize_url(state, scopes) → str
- exchange_code(code, redirect_uri) → RefreshedTokens (initial connect)

Refresh and exchange both produce RefreshedTokens for symmetry — the
resolver stores them the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Protocol


@dataclass(frozen=True)
class RefreshedTokens:
    """Result of a refresh or initial-exchange call."""
    access_token: str
    refresh_token: Optional[str] = None      # None when provider doesn't rotate
    expires_at: Optional[datetime] = None
    granted_scopes: tuple[str, ...] = ()
    extra: Dict[str, Any] = field(default_factory=dict)


class Adapter(Protocol):
    """Per-provider interface. New providers implement this."""

    kind: str

    def refresh(self, payload: Dict[str, Any]) -> RefreshedTokens:
        """
        Exchange the stored refresh_token for a new access_token. Raise
        any exception to signal "this credential is dead, mark revoked";
        the resolver translates into CredentialExpired.

        payload is the decrypted blob currently stored.
        """
        ...

    def build_authorize_url(
        self,
        state: str,
        scopes: list[str],
        redirect_uri: str,
    ) -> str:
        """Build the provider's OAuth consent URL."""
        ...

    def exchange_code(
        self,
        code: str,
        redirect_uri: str,
    ) -> RefreshedTokens:
        """Exchange the OAuth authorization code for initial tokens."""
        ...


_REGISTRY: Dict[str, Adapter] = {}


def register_adapter(adapter: Adapter) -> Adapter:
    _REGISTRY[adapter.kind] = adapter
    return adapter


def get_adapter(kind: str) -> Adapter:
    try:
        return _REGISTRY[kind]
    except KeyError as exc:
        raise LookupError(
            f"No credential adapter registered for kind={kind!r}. "
            f"Available: {sorted(_REGISTRY)}"
        ) from exc


def known_kinds() -> list[str]:
    return sorted(_REGISTRY)
