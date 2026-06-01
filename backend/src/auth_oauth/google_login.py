"""
Google Sign-In support — verify an ID token, OR exchange an OAuth
authorization code, and return a normalized user profile.

Two flows supported:

1. ID token (recommended for SPA / mobile / Google One Tap):
   Client gets an ID token from Google directly via the JS library,
   sends it to us, we verify the signature + audience against
   GOOGLE_OAUTH_CLIENT_ID.

2. Authorization code (server-side OAuth):
   Client gets a `code` from the redirect, we exchange it server-side
   for tokens, then verify the ID token from the response.

Both paths produce a GoogleProfile dataclass. The route handler
upserts a platform_users row, mints amebo JWTs, returns.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

logger = logging.getLogger(__name__)


GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
DEFAULT_LOGIN_REDIRECT_PATH = "/auth/google/callback"


class GoogleLoginError(RuntimeError):
    """Verification or token-exchange failure. Routes turn this into 401."""


@dataclass(frozen=True)
class GoogleProfile:
    sub: str               # stable Google user id
    email: str
    email_verified: bool
    name: Optional[str] = None
    given_name: Optional[str] = None
    picture: Optional[str] = None


def _client_id() -> str:
    cid = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    if not cid:
        raise GoogleLoginError(
            "GOOGLE_OAUTH_CLIENT_ID is not set; Google login is disabled."
        )
    return cid


def _client_secret() -> str:
    secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not secret:
        raise GoogleLoginError(
            "GOOGLE_OAUTH_CLIENT_SECRET is not set; Google login is disabled."
        )
    return secret


def _public_base_url() -> str:
    return os.getenv("AMEBO_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def _default_redirect_uri() -> str:
    return f"{_public_base_url()}{DEFAULT_LOGIN_REDIRECT_PATH}"


def verify_id_token(token: str) -> GoogleProfile:
    """Verify an ID token directly (Google Sign-In / One Tap flow)."""
    if not token:
        raise GoogleLoginError("Missing Google ID token.")
    try:
        # google-auth verifies signature against Google's published keys,
        # checks audience matches our client_id, and asserts the token
        # hasn't expired. Anything wrong → ValueError.
        payload = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=_client_id(),
        )
    except ValueError as exc:
        logger.warning("Google ID token verification failed: %s", exc)
        raise GoogleLoginError("Invalid Google ID token.") from exc

    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        raise GoogleLoginError("Google token did not include sub + email.")

    return GoogleProfile(
        sub=sub,
        email=email,
        email_verified=bool(payload.get("email_verified")),
        name=payload.get("name"),
        given_name=payload.get("given_name"),
        picture=payload.get("picture"),
    )


def exchange_code(code: str, redirect_uri: Optional[str] = None) -> GoogleProfile:
    """
    Trade an OAuth authorization code for tokens, then verify the ID
    token from the response.
    """
    if not code:
        raise GoogleLoginError("Missing OAuth authorization code.")

    resp = requests.post(
        GOOGLE_TOKEN_ENDPOINT,
        data={
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": redirect_uri or _default_redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    if resp.status_code != 200:
        logger.warning("Google code exchange failed: %s %s", resp.status_code, resp.text[:200])
        raise GoogleLoginError(f"Google code exchange failed ({resp.status_code}).")

    body = resp.json()
    id_token_str = body.get("id_token")
    if not id_token_str:
        raise GoogleLoginError("Google token response did not include an id_token.")

    return verify_id_token(id_token_str)


def resolve_google_identity(
    id_token: Optional[str] = None,
    code: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> GoogleProfile:
    """
    Single entry point — pass either an ID token or an authorization code,
    get back a verified GoogleProfile. The route handler can accept both
    fields from the client and pass them through.
    """
    if id_token:
        return verify_id_token(id_token)
    if code:
        return exchange_code(code, redirect_uri=redirect_uri)
    raise GoogleLoginError("Either id_token or code is required.")
