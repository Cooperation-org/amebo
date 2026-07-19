"""
Authentication middleware for FastAPI
Validates JWT tokens and extracts user information.
Also provides service-to-service API key authentication.
"""

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
import logging
from typing import Optional

from src.api.auth_utils import SESSION_COOKIE_NAME, user_from_session_token
from src.db.connection import DatabaseConnection
from psycopg2 import extras

logger = logging.getLogger(__name__)
security_optional = HTTPBearer(auto_error=False)


def _validate_session_token(token: str) -> dict:
    """Validate a session JWT, normalizing unexpected errors to 401."""
    try:
        return user_from_session_token(token)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
) -> dict:
    """
    Authenticate user from a session JWT.

    Credential resolution order:
      1. ``Authorization: Bearer <jwt>`` header (always wins)
      2. the HttpOnly session cookie (fallback, for browser embeds
         fetching with credentials:'include' — see auth_utils)

    Returns:
        User dict with user_id, org_id, email, role

    Raises:
        HTTPException 401: If no credential is present or it is invalid
    """
    if credentials:
        return _validate_session_token(credentials.credentials)

    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return _validate_session_token(cookie_token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional)
) -> Optional[dict]:
    """
    Optional authentication - returns None if no valid credential provided

    Useful for endpoints that work differently for authenticated vs anonymous users
    """
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# Service-to-service API key authentication
# ---------------------------------------------------------------------------

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)
api_key_header_optional = APIKeyHeader(name="X-API-Key", auto_error=False)


def _validate_api_key(api_key: str) -> dict:
    """
    Validate an API key string against the api_keys table.

    Returns the service-client dict (org_id, key_name, permissions) on
    success. Raises HTTPException 401 on any failure. Updates
    last_used_at on every successful lookup.
    """
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT key_id, org_id, key_name, permissions, is_active, expires_at
                FROM api_keys
                WHERE key_hash = %s
            """, (key_hash,))
            row = cur.fetchone()

            if not row:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid API key",
                )

            if not row["is_active"]:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key is inactive",
                )

            if row["expires_at"] and row["expires_at"] < datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="API key has expired",
                )

            cur.execute(
                "UPDATE api_keys SET last_used_at = NOW() WHERE key_id = %s",
                (row["key_id"],)
            )
            conn.commit()

            return {
                "org_id": row["org_id"],
                "key_name": row["key_name"],
                "permissions": row["permissions"] or ["read"],
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Service auth error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate API key",
        )
    finally:
        DatabaseConnection.return_connection(conn)


async def get_service_client(api_key: str = Depends(api_key_header)) -> dict:
    """Authenticate a service-to-service call via X-API-Key header."""
    return _validate_api_key(api_key)


async def get_service_or_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    api_key: Optional[str] = Depends(api_key_header_optional),
) -> dict:
    """
    Accept a user JWT (Authorization: Bearer ...), a service X-API-Key,
    or (fallback) the HttpOnly session cookie. All produce a dict carrying
    `org_id` so downstream code (which reads `client["org_id"]`) works
    unchanged.

    Credential resolution order: Bearer header, X-API-Key, session cookie.

    Distinguished by the `auth` key:
      Bearer JWT / session cookie → {"org_id", "user_id", "email", "role", "auth": "user"}
      X-API-Key                   → {"org_id", "key_name", "permissions", "auth": "service"}

    Use this on endpoints that should be reachable from an end-user
    session (per-user JWT or browser session cookie) or from a
    service-to-service caller.
    """
    if credentials:
        user = _validate_session_token(credentials.credentials)
        user["auth"] = "user"
        return user
    if api_key:
        svc = _validate_api_key(api_key)
        svc["auth"] = "service"
        return svc
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        user = _validate_session_token(cookie_token)
        user["auth"] = "user"
        return user
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (Bearer JWT or X-API-Key)",
        headers={"WWW-Authenticate": "Bearer"},
    )