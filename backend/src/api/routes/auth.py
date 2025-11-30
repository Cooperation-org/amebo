"""
Authentication routes - signup, login, token refresh
"""

from fastapi import APIRouter, HTTPException, status, Depends
from psycopg2 import extras
import logging
import re

from src.api.models import (
    UserSignupRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse
)
from src.api.auth_utils import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user
)
from src.db.connection import DatabaseConnection

router = APIRouter()
logger = logging.getLogger(__name__)


def create_org_slug(org_name: str) -> str:
    """Generate URL-friendly slug from org name"""
    slug = org_name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = slug.strip('-')
    return slug[:100]


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(request: UserSignupRequest):
    """
    Register a new user and organization
    Creates both organization and first user (owner)
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Generate org slug
            org_slug = request.org_slug or create_org_slug(request.org_name)

            # Check if email already exists
            cur.execute(
                "SELECT user_id FROM platform_users WHERE email = %s",
                (request.email,)
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )

            # Check if org slug is taken
            cur.execute(
                "SELECT org_id FROM organizations WHERE org_slug = %s",
                (org_slug,)
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Organization name already taken. Please choose a different name."
                )

            # Create organization
            cur.execute(
                """
                INSERT INTO organizations (org_name, org_slug, subscription_plan, subscription_status)
                VALUES (%s, %s, 'free', 'active')
                RETURNING org_id
                """,
                (request.org_name, org_slug)
            )
            org_id = cur.fetchone()['org_id']

            # Hash password
            password_hash = hash_password(request.password)

            # Create user (owner role)
            cur.execute(
                """
                INSERT INTO platform_users (org_id, email, password_hash, full_name, role, is_active)
                VALUES (%s, %s, %s, %s, 'owner', true)
                RETURNING user_id, email, full_name, role
                """,
                (org_id, request.email, password_hash, request.full_name)
            )
            user = cur.fetchone()

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, 'user_signup', 'user', %s, %s)
                """,
                (org_id, user['user_id'], str(user['user_id']),
                 extras.Json({'org_created': True}))
            )

            conn.commit()

            # Create tokens
            token_data = {
                "user_id": user['user_id'],
                "org_id": org_id,
                "email": user['email'],
                "role": user['role']
            }
            access_token = create_access_token(token_data)
            refresh_token = create_refresh_token({"user_id": user['user_id']})

            logger.info(f"New user signed up: {request.email}, org: {request.org_name}")

            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                expires_in=3600
            )

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Signup error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create account"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.post("/login", response_model=TokenResponse)
async def login(request: UserLoginRequest):
    """
    Login with email and password
    Returns access and refresh tokens
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Get user by email
            cur.execute(
                """
                SELECT user_id, org_id, email, password_hash, full_name, role, is_active
                FROM platform_users
                WHERE email = %s
                """,
                (request.email,)
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password"
                )

            # Verify password
            if not verify_password(request.password, user['password_hash']):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password"
                )

            # Check if user is active
            if not user['is_active']:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is disabled"
                )

            # Update last login
            cur.execute(
                "UPDATE platform_users SET last_login_at = NOW() WHERE user_id = %s",
                (user['user_id'],)
            )

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id)
                VALUES (%s, %s, 'user_login', 'user', %s)
                """,
                (user['org_id'], user['user_id'], str(user['user_id']))
            )

            conn.commit()

            # Create tokens
            token_data = {
                "user_id": user['user_id'],
                "org_id": user['org_id'],
                "email": user['email'],
                "role": user['role']
            }
            access_token = create_access_token(token_data)
            refresh_token = create_refresh_token({"user_id": user['user_id']})

            logger.info(f"User logged in: {request.email}")

            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                expires_in=3600
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest):
    """
    Refresh access token using refresh token
    """
    try:
        # Decode refresh token
        payload = decode_token(request.refresh_token)

        # Verify token type
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )

        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

        # Get user info
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT user_id, org_id, email, role, is_active
                    FROM platform_users
                    WHERE user_id = %s
                    """,
                    (user_id,)
                )
                user = cur.fetchone()

                if not user or not user['is_active']:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid token"
                    )

                # Create new access token
                token_data = {
                    "user_id": user['user_id'],
                    "org_id": user['org_id'],
                    "email": user['email'],
                    "role": user['role']
                }
                access_token = create_access_token(token_data)

                return TokenResponse(
                    access_token=access_token,
                    refresh_token=request.refresh_token,  # Keep same refresh token
                    token_type="bearer",
                    expires_in=3600
                )

        finally:
            DatabaseConnection.return_connection(conn)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not refresh token"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """
    Get current authenticated user information
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, org_id, email, full_name, role, is_active,
                       email_verified, created_at
                FROM platform_users
                WHERE user_id = %s
                """,
                (current_user['user_id'],)
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            return UserResponse(**user)

    finally:
        DatabaseConnection.return_connection(conn)
