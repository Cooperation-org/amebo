"""
Connection management endpoints — credentials lifecycle for an org.

API surface:

    POST   /api/connections/start        — mint a connect link (service or user)
    GET    /api/connections/             — list this org's connections (metadata only)
    DELETE /api/connections/{id}         — revoke a connection
    GET    /connect/{short_code}         — user-facing: redirect to provider OAuth
    GET    /connect/{short_code}/callback — provider redirects back here

`/api/connections/*` uses the X-API-Key service-client auth so
dispatchers and the web UI's API tier can both call it. The two
`/connect/*` endpoints serve HTTP redirects directly to the user, gated
by an admin login (the platform_user JWT).

OAuth state token uses the connect_link short_code itself — the link
IS the state. Single-use semantics live in connect_links.consumed_at.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel, Field

from src.api.middleware.auth import (
    get_current_user_optional,
    get_service_client,
)
from src.credentials import (
    ConnectLinkError,
    CredentialResolver,
    consume_connect_link,
    get_connect_link,
    mint_connect_link,
)
from src.credentials.adapters import get_adapter

router = APIRouter()
logger = logging.getLogger(__name__)


# Public URL where amebo lives — used to build OAuth redirect URIs.
# Falls back to localhost for dev.
def _public_base_url() -> str:
    return os.getenv("AMEBO_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def _redirect_uri(short_code: str) -> str:
    return f"{_public_base_url()}/connect/{short_code}/callback"


# ---------------------------------------------------------------------------
# Pydantic
# ---------------------------------------------------------------------------


class StartConnectionRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=50)
    scopes: List[str] = Field(default_factory=list)
    label: str = Field("default", max_length=100)
    reply_channel: Optional[str] = Field(None, max_length=255)


class StartConnectionResponse(BaseModel):
    short_code: str
    connect_url: str
    expires_at: datetime
    kind: str
    label: str


class ConnectionResponse(BaseModel):
    id: int
    kind: str
    label: str
    granted_scopes: List[str]
    expires_at: Optional[datetime]
    created_at: datetime
    last_used_at: Optional[datetime]
    revoked_at: Optional[datetime]


# ---------------------------------------------------------------------------
# API: start, list, revoke
# ---------------------------------------------------------------------------


@router.post("/start", response_model=StartConnectionResponse)
async def start_connection(
    req: StartConnectionRequest,
    client: dict = Depends(get_service_client),
):
    """
    Mint a connect link for the calling org. The response contains the
    URL to deliver to the user (via channel adapter or web UI).
    """
    org_id = client["org_id"]

    # Verify we know how to drive this provider before minting a link
    # for a kind we can't actually complete.
    try:
        get_adapter(req.kind)
    except LookupError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    link = mint_connect_link(
        org_id=org_id,
        kind=req.kind,
        requested_scopes=req.scopes,
        reply_channel=req.reply_channel,
        label=req.label,
    )
    return StartConnectionResponse(
        short_code=link.short_code,
        connect_url=f"{_public_base_url()}/connect/{link.short_code}",
        expires_at=link.expires_at,
        kind=link.kind,
        label=link.label,
    )


@router.get("/", response_model=List[ConnectionResponse])
async def list_connections(
    client: dict = Depends(get_service_client),
):
    rows = CredentialResolver.list_for_org(client["org_id"])
    return [
        ConnectionResponse(
            id=r["id"],
            kind=r["kind"],
            label=r["label"],
            granted_scopes=list(r.get("granted_scopes") or []),
            expires_at=r.get("expires_at"),
            created_at=r["created_at"],
            last_used_at=r.get("last_used_at"),
            revoked_at=r.get("revoked_at"),
        )
        for r in rows
    ]


class RevokeResponse(BaseModel):
    revoked: bool


@router.delete("/{kind}", response_model=RevokeResponse)
async def revoke_connection(
    kind: str,
    label: str = Query("default"),
    client: dict = Depends(get_service_client),
):
    ok = CredentialResolver.revoke(client["org_id"], kind, label)
    if not ok:
        raise HTTPException(status_code=404, detail="No active connection to revoke")
    return RevokeResponse(revoked=True)


# ---------------------------------------------------------------------------
# User-facing OAuth flow: /connect/{code} and /connect/{code}/callback
# These are mounted at root path (not /api/) so they look like normal URLs
# users can click in chat/email/etc.
# ---------------------------------------------------------------------------


public_router = APIRouter()


def _render_message(title: str, body: str, status: int = 200) -> HTMLResponse:
    """Minimal HTML for messages we send to the user mid-flow."""
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 Helvetica, Arial, sans-serif;
    max-width: 32rem;
    margin: 4rem auto;
    padding: 0 1.5rem;
    color: #1a1a1a;
    line-height: 1.55;
  }}
  h1 {{ font-size: 1.4rem; margin-bottom: 1rem; }}
  p {{ margin: 0.75rem 0; }}
  a.btn {{
    display: inline-block;
    padding: 0.6rem 1.2rem;
    margin-top: 0.5rem;
    background: #1a1a1a;
    color: #fff;
    border-radius: 0.4rem;
    text-decoration: none;
  }}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status)


@public_router.get("/connect/{short_code}", name="connect_start")
async def connect_start(
    short_code: str,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    """
    Entry point a user clicks. Validates the link, requires login, then
    redirects to the provider's OAuth consent screen.
    """
    try:
        link = get_connect_link(short_code)
    except ConnectLinkError:
        return _render_message(
            "Connect link not found",
            "<p>This connect link doesn't exist or has been removed. Please ask for a new one.</p>",
            status=404,
        )

    if not link.is_usable:
        if link.is_consumed:
            return _render_message(
                "Already used",
                "<p>This connect link has already been used. If you need to reconnect, please request a new one.</p>",
                status=410,
            )
        return _render_message(
            "Link expired",
            "<p>This connect link has expired. Please request a new one.</p>",
            status=410,
        )

    # Require a logged-in admin of the org.
    if user is None:
        login_url = f"{_public_base_url()}/login?next=/connect/{short_code}"
        return _render_message(
            "Sign in required",
            f'<p>You need to sign in to amebo to connect this credential.</p>'
            f'<p><a class="btn" href="{login_url}">Sign in</a></p>',
            status=401,
        )

    if user.get("org_id") != link.org_id:
        return _render_message(
            "Wrong organisation",
            "<p>This connect link is for a different organisation. Sign in with an account that belongs to the right org.</p>",
            status=403,
        )

    if user.get("role") not in ("owner", "admin"):
        return _render_message(
            "Admin permission required",
            "<p>Only org admins can connect new credentials. Please ask your admin to click this link.</p>",
            status=403,
        )

    # All checks passed — redirect to provider OAuth.
    try:
        adapter = get_adapter(link.kind)
    except LookupError:
        return _render_message(
            "Unknown provider",
            f"<p>No adapter is configured for provider '{link.kind}'.</p>",
            status=500,
        )

    try:
        authorize_url = adapter.build_authorize_url(
            state=short_code,
            scopes=list(link.requested_scopes),
            redirect_uri=_redirect_uri(short_code),
        )
    except Exception as exc:
        logger.exception("Adapter could not build authorize URL")
        return _render_message(
            "Provider not configured",
            f"<p>Could not start OAuth for {link.kind}: {exc}</p>",
            status=500,
        )

    return RedirectResponse(url=authorize_url, status_code=302)


@public_router.get("/connect/{short_code}/callback", name="connect_callback")
async def connect_callback(
    short_code: str,
    code: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    """
    Provider redirects here after the user grants (or denies) consent.
    """
    if error:
        return _render_message(
            "Connection cancelled",
            f"<p>The provider returned an error: {error}.</p>"
            "<p>Nothing was connected. You can close this tab.</p>",
            status=400,
        )
    if not code:
        return _render_message(
            "Missing authorization code",
            "<p>The provider did not return an authorization code. Try again.</p>",
            status=400,
        )

    try:
        link = get_connect_link(short_code)
    except ConnectLinkError:
        return _render_message("Connect link not found",
                               "<p>The connect link is gone. Please start a new one.</p>",
                               status=404)

    if not link.is_usable:
        return _render_message("Link no longer valid",
                               "<p>This connect link has already been used or expired.</p>",
                               status=410)

    if user is None or user.get("org_id") != link.org_id or user.get("role") not in ("owner", "admin"):
        return _render_message("Authorization mismatch",
                               "<p>Your sign-in does not match the connect link. Please start again.</p>",
                               status=403)

    # Exchange the code for tokens via the adapter, then store + consume.
    try:
        adapter = get_adapter(link.kind)
        refreshed = adapter.exchange_code(code, _redirect_uri(short_code))
    except Exception as exc:
        logger.exception("OAuth code exchange failed")
        return _render_message("Connection failed",
                               f"<p>The provider could not exchange the code: {exc}</p>",
                               status=500)

    CredentialResolver.store_new(
        org_id=link.org_id,
        kind=link.kind,
        label=link.label,
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token,
        expires_at=refreshed.expires_at,
        granted_scopes=list(refreshed.granted_scopes),
        connected_by_user_id=user.get("user_id"),
    )

    try:
        consume_connect_link(short_code, consumed_by_user_id=user.get("user_id"))
    except ConnectLinkError:
        # Race condition — another concurrent callback consumed it. The
        # credential is still stored; user sees success.
        logger.warning("Connect link %s was consumed concurrently", short_code)

    # TODO: notify link.reply_channel via the matching channel adapter.

    return _render_message(
        f"{link.kind.title()} connected",
        f"<p>You can close this tab and return to your previous conversation.</p>"
        f"<p>Connection: {link.kind}/{link.label}</p>",
    )


