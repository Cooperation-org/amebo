"""
Global authentication gate.

Closes the "every endpoint is open" hole. The rule the team set:

    Internal callers (Claude Code on the server) are trusted.
    Any EXTERNAL caller must present authentication.

How "external" is told apart from "internal", robustly:

  * The backend binds ``127.0.0.1:8000`` (loopback only) — confirmed in
    ``main.py``/``API_HOST``. Nothing off-box can reach the API port directly;
    external traffic MUST traverse Caddy -> nginx.
  * nginx, on the public ``api.amebo.linkedtrust.us`` vhost, sets
    ``X-Amebo-Edge: public`` with ``proxy_set_header`` (which *overwrites* any
    client-supplied value). So every externally-originated request carries the
    marker and a client cannot forge its absence — to remove it they would have
    to reach :8000 directly, which loopback-binding forbids.
  * A request WITHOUT the marker therefore came straight from this host's
    loopback — i.e. internal tooling (Claude Code, cron, local scripts). Trusted.

So: marker present  -> external -> must authenticate (Bearer JWT or X-API-Key).
    marker absent   -> internal -> pass through (routes' own deps still apply).

``is_active`` is enforced when a session JWT is *issued* (login / OIDC
callback), not here, so the gate stays a fast stateless check.
"""

from __future__ import annotations

import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.auth_utils import decode_token
from src.api.middleware.auth import _validate_api_key

logger = logging.getLogger(__name__)

# Header nginx stamps on public-edge traffic. Configurable but must match the
# nginx vhost (proxy_set_header X-Amebo-Edge "public";).
EDGE_HEADER = os.getenv("AMEBO_EDGE_HEADER", "x-amebo-edge").lower()
EDGE_VALUE = os.getenv("AMEBO_EDGE_VALUE", "public")

# Paths open to everyone, internal or external. Prefix match.
# Auth endpoints must be public or no one could ever log in; /connect is a
# user-facing OAuth flow self-gated by single-use link tokens; health/acme/root
# are infrastructure.
PUBLIC_PREFIXES = (
    "/api/auth/",     # password login, refresh, forgot/reset, google, oidc login+callback
    "/connect/",      # connect-link OAuth (self-gated by single-use short_code)
    "/.well-known/",  # acme-challenge, etc.
)
PUBLIC_EXACT = frozenset({"/", "/health"})


def _is_public(path: str) -> bool:
    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


def _authenticated(request: Request) -> bool:
    """True if the request carries a valid session JWT or a valid service API key."""
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = decode_token(auth[7:].strip())
            request.state.user = payload  # available to downstream handlers
            return True
        except Exception:
            pass  # fall through to API-key check / 401
    api_key = request.headers.get("x-api-key")
    if api_key:
        try:
            request.state.service_client = _validate_api_key(api_key)
            return True
        except Exception:
            pass
    return False


class AuthGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Never gate CORS preflight — the CORS middleware answers it.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if _is_public(path):
            return await call_next(request)

        is_external = request.headers.get(EDGE_HEADER, "").lower() == EDGE_VALUE
        if is_external and not _authenticated(request):
            logger.info("auth_gate: blocked unauthenticated external %s %s", request.method, path)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Sign in with LinkedTrust."},
            )

        return await call_next(request)
