"""
Authentication middleware for FastAPI
Simple mock authentication for development
"""

from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
from typing import Optional

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Development authentication - always returns valid user
    """
    # For development, always return the real user regardless of token
    return {
        "user_id": 1,
        "org_id": 1,
        "email": "orjienekenechukwu@gmail.com"
    }

async def get_current_user_optional() -> Optional[dict]:
    """
    Optional authentication - returns mock user for development
    """
    return await get_current_user()