"""
Authentication routes - signup, login, token refresh, password management
"""

from fastapi import APIRouter, HTTPException, status, Depends
from psycopg2 import extras
import logging
import re
import secrets
import hashlib

from src.api.models import (
    UserSignupRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
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
from src.services.email_service import email_service

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
                INSERT INTO platform_users (org_id, email, password_hash, full_name, role, is_active, email_verified)
                VALUES (%s, %s, %s, %s, 'owner', true, true)
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
                SELECT user_id, org_id, email, password_hash, full_name, role, is_active, email_verified
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

            # Check if invited user needs to change temp password
            must_change_password = not user.get('email_verified', True)

            logger.info(f"User logged in: {request.email}")

            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                expires_in=3600,
                must_change_password=must_change_password
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


@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """
    Request a password reset email.
    Always returns 200 to prevent email enumeration.
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Look up user
            cur.execute(
                "SELECT user_id, email FROM platform_users WHERE email = %s AND is_active = true",
                (request.email,)
            )
            user = cur.fetchone()

            if user:
                # Generate reset token
                raw_token = secrets.token_urlsafe(32)
                token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

                # Invalidate any existing unused tokens for this user
                cur.execute(
                    """
                    UPDATE password_reset_tokens
                    SET used_at = NOW()
                    WHERE user_id = %s AND used_at IS NULL
                    """,
                    (user['user_id'],)
                )

                # Store hashed token with 1-hour expiry
                cur.execute(
                    """
                    INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
                    VALUES (%s, %s, NOW() + INTERVAL '1 hour')
                    """,
                    (user['user_id'], token_hash)
                )

                conn.commit()

                # Send email with raw token
                email_sent = email_service.send_password_reset_email(
                    to_email=user['email'],
                    reset_token=raw_token
                )

                if not email_sent:
                    logger.warning(f"Password reset email could not be sent to {request.email}")

            # Always return success to prevent email enumeration
            return {"message": "If an account with that email exists, a password reset link has been sent."}

    except Exception as e:
        conn.rollback()
        logger.error(f"Forgot password error: {e}", exc_info=True)
        # Still return 200 to prevent enumeration
        return {"message": "If an account with that email exists, a password reset link has been sent."}
    finally:
        DatabaseConnection.return_connection(conn)


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """
    Reset password using a token from the reset email.
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Hash the incoming token to compare with stored hash
            token_hash = hashlib.sha256(request.token.encode()).hexdigest()

            # Find valid, unused token
            cur.execute(
                """
                SELECT t.token_id, t.user_id
                FROM password_reset_tokens t
                WHERE t.token_hash = %s
                  AND t.used_at IS NULL
                  AND t.expires_at > NOW()
                """,
                (token_hash,)
            )
            token_record = cur.fetchone()

            if not token_record:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired reset token. Please request a new password reset."
                )

            # Update user's password
            new_hash = hash_password(request.new_password)
            cur.execute(
                """
                UPDATE platform_users
                SET password_hash = %s, email_verified = true, updated_at = NOW()
                WHERE user_id = %s
                """,
                (new_hash, token_record['user_id'])
            )

            # Mark token as used
            cur.execute(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE token_id = %s",
                (token_record['token_id'],)
            )

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (user_id, action, resource_type, resource_id, details)
                VALUES (%s, 'password_reset', 'user', %s, %s)
                """,
                (token_record['user_id'], str(token_record['user_id']),
                 extras.Json({'method': 'email_token'}))
            )

            conn.commit()

            logger.info(f"Password reset completed for user_id: {token_record['user_id']}")

            return {"message": "Password reset successfully. You can now log in with your new password."}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Reset password error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.put("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Change password for authenticated user.
    Also sets email_verified=true (handles invited user temp password flow).
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Get current password hash
            cur.execute(
                "SELECT password_hash FROM platform_users WHERE user_id = %s",
                (current_user['user_id'],)
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            # Verify current password
            if not verify_password(request.current_password, user['password_hash']):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Current password is incorrect"
                )

            # Update password and mark email as verified
            new_hash = hash_password(request.new_password)
            cur.execute(
                """
                UPDATE platform_users
                SET password_hash = %s, email_verified = true, updated_at = NOW()
                WHERE user_id = %s
                """,
                (new_hash, current_user['user_id'])
            )

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id)
                VALUES (%s, %s, 'password_changed', 'user', %s)
                """,
                (current_user['org_id'], current_user['user_id'], str(current_user['user_id']))
            )

            conn.commit()

            logger.info(f"Password changed for user: {current_user['email']}")

            return {"message": "Password changed successfully."}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Change password error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )
    finally:
        DatabaseConnection.return_connection(conn)
