"""
Development authentication routes - FOR LOCAL DEVELOPMENT ONLY

WARNING: This module should NEVER be enabled in production.
It is disabled by default and requires DEV_AUTH_ENABLED=true environment variable.
"""

import os
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Development auth is disabled by default - must explicitly enable
DEV_AUTH_ENABLED = os.getenv("DEV_AUTH_ENABLED", "false").lower() == "true"

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

@router.post("/login", response_model=TokenResponse)
async def dev_login(request: LoginRequest):
    """
    Development login - FOR LOCAL TESTING ONLY

    Requires DEV_AUTH_ENABLED=true and DEV_AUTH_EMAIL/DEV_AUTH_PASSWORD_HASH env vars
    """
    if not DEV_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development authentication is disabled"
        )

    # Credentials must be set via environment variables
    dev_email = os.getenv("DEV_AUTH_EMAIL")
    dev_password = os.getenv("DEV_AUTH_PASSWORD")

    if not dev_email or not dev_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Development credentials not configured"
        )

    if request.email == dev_email and request.password == dev_password:
        return TokenResponse(
            access_token="mock-jwt-token-" + str(hash(request.email)),
            token_type="bearer",
            user={
                "user_id": 1,
                "email": request.email,
                "org_id": 1,
                "org_name": "Development Team",
                "role": "admin"
            }
        )
    raise HTTPException(status_code=401, detail="Invalid credentials")

@router.get("/me")
async def dev_get_current_user():
    """Development get current user - FOR LOCAL TESTING ONLY"""
    if not DEV_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Development authentication is disabled"
        )

    dev_email = os.getenv("DEV_AUTH_EMAIL", "dev@localhost")
    return {
        "user_id": 1,
        "email": dev_email,
        "org_id": 1,
        "org_name": "Development Team",
        "role": "admin"
    }