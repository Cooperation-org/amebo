"""
Google OAuth adapter — Gmail, Calendar, Drive, etc.

Configuration via env (set in systemd unit, NOT in DB):
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET

If either is missing, the adapter still loads (so other adapters work)
but raises a clear error when called. This lets dev environments run
without Google config until someone needs it.

Reference:
- https://developers.google.com/identity/protocols/oauth2/web-server#offline
- https://developers.google.com/identity/protocols/oauth2/web-server#refresh
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import urlencode

import requests

from src.credentials.adapters.base import (
    Adapter,
    RefreshedTokens,
    register_adapter,
)

logger = logging.getLogger(__name__)


AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleAdapter:
    kind = "google"

    def _client_id(self) -> str:
        cid = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
        if not cid:
            raise RuntimeError(
                "GOOGLE_OAUTH_CLIENT_ID is not set; cannot use Google OAuth."
            )
        return cid

    def _client_secret(self) -> str:
        secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
        if not secret:
            raise RuntimeError(
                "GOOGLE_OAUTH_CLIENT_SECRET is not set; cannot use Google OAuth."
            )
        return secret

    # ------------------------------------------------------------ Refresh

    def refresh(self, payload: Dict[str, Any]) -> RefreshedTokens:
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Stored credential has no refresh_token; cannot refresh.")

        resp = requests.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            # Most refresh failures (invalid_grant) mean the user revoked
            # access, the refresh token expired (6mo unused), or the OAuth
            # consent was withdrawn. All map to "must reconnect".
            logger.warning("Google refresh failed: %s %s", resp.status_code, resp.text[:200])
            raise RuntimeError(f"Google refresh failed ({resp.status_code}): {resp.text[:200]}")

        data = resp.json()
        access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 30)

        # Google sometimes does NOT return a new refresh_token on refresh;
        # the existing one stays valid. Only override if a new one came back.
        new_refresh = data.get("refresh_token") or refresh_token

        return RefreshedTokens(
            access_token=access_token,
            refresh_token=new_refresh,
            expires_at=expires_at,
            granted_scopes=tuple((data.get("scope") or "").split()) or (),
        )

    # ------------------------------------------------------- Authorize URL

    def build_authorize_url(
        self,
        state: str,
        scopes: List[str],
        redirect_uri: str,
    ) -> str:
        params = {
            "client_id": self._client_id(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",       # required to get a refresh_token
            "prompt": "consent",            # force refresh_token even on re-consent
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_ENDPOINT}?{urlencode(params)}"

    # ----------------------------------------------------- Exchange code

    def exchange_code(self, code: str, redirect_uri: str) -> RefreshedTokens:
        resp = requests.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Google code exchange failed ({resp.status_code}): {resp.text[:200]}"
            )

        data = resp.json()
        expires_in = int(data.get("expires_in", 3600))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 30)

        return RefreshedTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            granted_scopes=tuple((data.get("scope") or "").split()) or (),
        )


register_adapter(GoogleAdapter())
