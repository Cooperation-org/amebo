"""
Authenticated HTTP client for tool code.

This is the ONLY thing tool implementations should reach for. Example:

    with credentials.client(org_id, kind="gmail") as c:
        resp = c.get("https://gmail.googleapis.com/gmail/v1/users/me/messages")

The wrapper handles:
- Looking up the credential (pre-flight refresh if expiring).
- Adding the right Authorization header for the provider.
- Catching 401 once → force-refresh → retry once.
- Recording last_used_at via the resolver.

Tools should NEVER touch CredentialResolver directly except through
this client. Keeps the surface small and the encapsulation enforceable.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

import requests

from src.credentials.resolver import (
    CredentialResolver,
    CredentialMissing,
    CredentialExpired,
    CredentialRevoked,
)

logger = logging.getLogger(__name__)


# Which header style does each provider use? Override only for non-Bearer
# auth (basic, custom header, etc.). Default is `Authorization: Bearer ...`.
_HEADER_STYLE = {
    # kind: (header_name, value_template)
    # value_template uses {token}
}


def _auth_headers(kind: str, access_token: str) -> dict:
    style = _HEADER_STYLE.get(kind)
    if style is None:
        return {"Authorization": f"Bearer {access_token}"}
    header_name, value_template = style
    return {header_name: value_template.format(token=access_token)}


class AuthSession(requests.Session):
    """
    Drop-in for requests.Session that:
    - injects auth headers on every request
    - handles a single 401 retry with a refreshed token
    - records last_used_at on first success
    """

    def __init__(self, resolver: CredentialResolver):
        super().__init__()
        self._resolver = resolver
        self._token = resolver.get().access_token
        self._used = False

    def request(self, method, url, **kwargs):
        headers = kwargs.pop("headers", None) or {}
        headers = {**headers, **_auth_headers(self._resolver.kind, self._token)}
        resp = super().request(method, url, headers=headers, **kwargs)

        # One refresh-and-retry per logical request. Track at session level
        # so we don't poke attributes onto the response object (which may be
        # a mock or shared object).
        if resp.status_code == 401:
            try:
                refreshed = self._resolver.force_refresh()
            except (CredentialExpired, CredentialRevoked, CredentialMissing):
                raise
            self._token = refreshed.access_token
            headers = {**headers, **_auth_headers(self._resolver.kind, self._token)}
            resp = super().request(method, url, headers=headers, **kwargs)
            # Caller gets whatever the retry returned — possibly still 401.
            # No further retries here; persistent auth failure surfaces.

        if resp.ok and not self._used:
            self._used = True
            try:
                self._resolver.mark_used()
            except Exception:
                logger.exception("Failed to mark credential used")

        return resp


@contextmanager
def client(
    org_id: int,
    kind: str,
    label: str = "default",
) -> Iterator[AuthSession]:
    """
    Acquire an authenticated HTTP session for (org, kind, label).

    Raises:
        CredentialMissing  — not connected; caller should mint a connect link.
        CredentialExpired  — refresh token dead; caller should mint a connect link.
        CredentialRevoked  — admin revoked; caller should mint a connect link.

    Tool code typically catches `CredentialMissing` and re-raises a typed
    error the dispatcher knows how to translate into a connect prompt.
    """
    resolver = CredentialResolver(org_id=org_id, kind=kind, label=label)
    session = AuthSession(resolver)
    try:
        yield session
    finally:
        session.close()
