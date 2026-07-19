"""
Authentication utilities - JWT, password hashing, token management
"""

from datetime import datetime, timedelta
from typing import Optional
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is required. "
        "Generate a secure key with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
REFRESH_TOKEN_EXPIRE_DAYS = 30  # 30 days

# Session cookie: the session JWT mirrored into an HttpOnly cookie at OIDC
# callback / token refresh so browser embeds on allowlisted origins
# (credentials:'include') can authenticate cross-origin. The Authorization
# header always takes precedence; the cookie is only a fallback credential.
# SameSite=Lax limits CSRF exposure (cross-site POSTs never carry it).
SESSION_COOKIE_NAME = os.getenv("AMEBO_SESSION_COOKIE", "amebo_session")

# HTTP Bearer token scheme. auto_error=False so a missing Authorization
# header falls through to the session-cookie fallback instead of a bare 403.
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    # Convert password to bytes and hash
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token

    Args:
        data: Payload data (typically user_id, org_id, role)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Create a JWT refresh token

    Args:
        data: Payload data (typically user_id)

    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT token

    Args:
        token: JWT token string

    Returns:
        Decoded payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def set_session_cookie(response: Response, access_token: str) -> None:
    """
    Mirror the session JWT into the HttpOnly session cookie.

    Called wherever an access token is issued to a browser (OIDC callback,
    token refresh). The SPA's localStorage flow is unchanged — the cookie
    is an additional credential for cross-origin embeds fetching with
    credentials:'include' from CORS-allowlisted origins.
    """
    response.set_cookie(
        SESSION_COOKIE_NAME,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def user_from_session_token(token: str) -> dict:
    """
    Validate a session (access) JWT and return the user dict.

    Shared by the Authorization-header and session-cookie paths.

    Raises:
        HTTPException 401: invalid/expired token, wrong type, bad payload
    """
    payload = decode_token(token)

    # Verify token type
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type"
        )

    # Extract user info
    user_id = payload.get("user_id")
    org_id = payload.get("org_id")

    if user_id is None or org_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    return {
        "user_id": user_id,
        "org_id": org_id,
        "email": payload.get("email"),
        "role": payload.get("role", "member")
    }


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    Dependency to get current authenticated user from a session JWT.

    Credential resolution order:
      1. ``Authorization: Bearer <jwt>`` header (always wins)
      2. the HttpOnly session cookie (fallback, for browser embeds)

    Returns:
        User payload dict with user_id, org_id, email, role

    Raises:
        HTTPException 401: no credential, or the credential is invalid
    """
    if credentials:
        return user_from_session_token(credentials.credentials)

    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return user_from_session_token(cookie_token)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(required_roles: list):
    """
    Dependency factory to check if user has required role

    Args:
        required_roles: List of allowed roles (e.g., ['admin', 'owner'])

    Returns:
        Dependency function
    """
    async def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {', '.join(required_roles)}"
            )
        return current_user

    return role_checker


# Convenience dependencies
require_admin = require_role(["admin", "owner"])
require_owner = require_role(["owner"])
