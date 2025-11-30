"""
Development authentication routes - simple mock auth for testing
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: dict

@router.post("/login", response_model=TokenResponse)
async def dev_login(request: LoginRequest):
    """Development login - bypasses database"""
    if request.email == "orjienekenechukwu@gmail.com" and request.password == "Lekan2904.":
        return TokenResponse(
            access_token="mock-jwt-token-" + str(hash(request.email)),
            token_type="bearer",
            user={
                "user_id": 1,
                "email": request.email,
                "org_id": 1,
                "org_name": "WhatsCookin Team",
                "role": "admin"
            }
        )
    raise HTTPException(status_code=401, detail="Invalid credentials")

@router.get("/me")
async def dev_get_current_user():
    """Development get current user"""
    return {
        "user_id": 1,
        "email": "orjienekenechukwu@gmail.com",
        "org_id": 1,
        "org_name": "WhatsCookin Team",
        "role": "admin"
    }