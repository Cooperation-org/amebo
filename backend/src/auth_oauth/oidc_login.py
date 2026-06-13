"""
LinkedTrust IdP (OIDC) login for amebo.

amebo is a confidential OIDC *client* of the team identity provider at
``OIDC_ISSUER`` (live.linkedtrust.us — implemented in trust_claim_backend).
That IdP brokers Google, Bluesky (ATProto), and LinkedTrust accounts, so this
one integration gives amebo all three login methods without amebo ever
touching DPoP, a Google client, or per-provider crypto.

Flow (authorization code + PKCE):
  1. ``build_authorize_url()`` — redirect the browser to the IdP.
  2. IdP authenticates the user (its choice of provider) and redirects back to
     ``OIDC_REDIRECT_URI`` with ``code`` + ``state``.
  3. ``exchange_code()`` — back-channel POST to the token endpoint (client
     secret stays server-side), returns the token set incl. ``id_token``.
  4. ``verify_id_token()`` — verify the IdP's EdDSA signature against its JWKS,
     check ``iss`` / ``aud`` / ``nonce``, and return the claims.

The route layer turns the verified claims into a ``platform_users`` row and
mints amebo's own session JWT (see ``api/routes/auth.py``). This module owns
only the OIDC handshake, never amebo's session.

id_tokens are EdDSA-signed; ``python-jose`` 3.3 cannot verify EdDSA, so this
module uses ``PyJWT[crypto]`` (which verifies via the already-present
``cryptography`` backend).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import urlencode

import jwt  # PyJWT[crypto]
import requests
from jwt import PyJWKClient

OIDC_SCOPES_DEFAULT = "openid profile email"
_DISCOVERY_PATH = "/.well-known/openid-configuration"
_HTTP_TIMEOUT = 15


class OidcError(RuntimeError):
    """Any failure in the OIDC handshake. Route handlers turn this into 401."""


def _env(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default)
    if not val:
        raise OidcError(f"{name} is not set; LinkedTrust OIDC login is disabled.")
    return val


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str

    @classmethod
    def from_env(cls) -> "OidcConfig":
        return cls(
            issuer=_env("OIDC_ISSUER").rstrip("/"),
            client_id=_env("OIDC_CLIENT_ID"),
            client_secret=_env("OIDC_CLIENT_SECRET"),
            redirect_uri=_env("OIDC_REDIRECT_URI"),
            scopes=os.getenv("OIDC_SCOPES", OIDC_SCOPES_DEFAULT),
        )


@dataclass(frozen=True)
class OidcIdentity:
    sub: str                      # stable subject id from the IdP
    email: Optional[str]
    email_verified: bool
    name: Optional[str]


# --- discovery + JWKS (cached per-process; cheap and rarely changes) ---------

_discovery_cache: dict = {}
_jwk_client_cache: dict = {}


def _discover(cfg: OidcConfig) -> dict:
    cached = _discovery_cache.get(cfg.issuer)
    if cached:
        return cached
    try:
        resp = requests.get(cfg.issuer + _DISCOVERY_PATH, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        meta = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise OidcError(f"OIDC discovery failed: {exc}") from exc
    # Defend against a discovery doc whose issuer doesn't match where we fetched it.
    if meta.get("issuer", "").rstrip("/") != cfg.issuer:
        raise OidcError("OIDC discovery issuer mismatch.")
    _discovery_cache[cfg.issuer] = meta
    return meta


def _jwk_client(cfg: OidcConfig) -> PyJWKClient:
    client = _jwk_client_cache.get(cfg.issuer)
    if client is None:
        client = PyJWKClient(_discover(cfg)["jwks_uri"])
        _jwk_client_cache[cfg.issuer] = client
    return client


# --- PKCE --------------------------------------------------------------------

def new_pkce() -> Tuple[str, str]:
    """Return (verifier, S256 challenge). Store the verifier with the request state."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# --- the three handshake steps -----------------------------------------------

def build_authorize_url(cfg: OidcConfig, *, state: str, nonce: str, code_challenge: str) -> str:
    meta = _discover(cfg)
    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": cfg.scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return meta["authorization_endpoint"] + "?" + urlencode(params)


def exchange_code(cfg: OidcConfig, *, code: str, code_verifier: str) -> dict:
    meta = _discover(cfg)
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.redirect_uri,
        "code_verifier": code_verifier,
        # confidential client — secret in the POST body (client_secret_post)
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
    }
    try:
        resp = requests.post(meta["token_endpoint"], data=data, timeout=_HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise OidcError(f"token exchange request failed: {exc}") from exc
    if resp.status_code != 200:
        raise OidcError(f"token exchange rejected ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def verify_id_token(cfg: OidcConfig, id_token: str, *, nonce: str) -> OidcIdentity:
    meta = _discover(cfg)
    algs = meta.get("id_token_signing_alg_values_supported", ["EdDSA"])
    try:
        signing_key = _jwk_client(cfg).get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=algs,
            audience=cfg.client_id,
            issuer=cfg.issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"id_token verification failed: {exc}") from exc
    if claims.get("nonce") != nonce:
        raise OidcError("id_token nonce mismatch (possible replay).")
    return OidcIdentity(
        sub=claims["sub"],
        email=claims.get("email"),
        email_verified=bool(claims.get("email_verified", False)),
        name=claims.get("name"),
    )


def new_state_nonce() -> Tuple[str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)
