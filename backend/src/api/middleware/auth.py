"""
Authentication middleware for FastAPI
Simple mock authentication for development
"""

from fastapi import HTTPException, status
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def get_current_user() -> dict:
    """
    Mock authentication - returns a default user for development
    In production, this would validate JWT tokens
    """
    # Mock user for development
    return {
        "user_id": 1,
        "org_id": 1,
        "email": "demo@example.com"
    }

async def get_current_user_optional() -> Optional[dict]:
    """
    Optional authentication - returns mock user for development
    """
    return await get_current_user()