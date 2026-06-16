"""
Authentication routes - signup, login, token refresh, password management
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request
from fastapi.responses import RedirectResponse
from psycopg2 import extras
import logging
import os
import re
import secrets
import hashlib
from datetime import timedelta

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
from src.auth_oauth import (
    GoogleLoginError, GoogleProfile, resolve_google_identity,
)
from pydantic import BaseModel
from typing import Optional

router = APIRouter()
logger = logging.getLogger(__name__)


class GoogleLoginRequest(BaseModel):
    id_token: Optional[str] = None
    code: Optional[str] = None
    redirect_uri: Optional[str] = None


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
                logger.warning("auth.signup.rejected email=%s reason=email_exists", request.email)
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
                logger.warning("auth.signup.rejected email=%s reason=org_taken slug=%s", request.email, org_slug)
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
                logger.warning("auth.login.failed email=%s reason=unknown_email", request.email)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password"
                )

            # Verify password
            if not verify_password(request.password, user['password_hash']):
                logger.warning("auth.login.failed email=%s reason=bad_password", request.email)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid email or password"
                )

            # Check if user is active
            if not user['is_active']:
                logger.warning("auth.login.failed email=%s reason=inactive", request.email)
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


# ---------------------------------------------------------------------------
# Google Sign-In
# ---------------------------------------------------------------------------


def _slug_from_email(email: str) -> str:
    """
    Build a per-user default org slug from an email. The org is a personal
    workspace for first-time Google signups — the user can rename it later.
    """
    local = email.split('@', 1)[0]
    slug = create_org_slug(local + "-personal")
    return slug or "personal"


@router.post("/google", response_model=TokenResponse)
async def google_login(request: GoogleLoginRequest):
    """
    Sign in with Google. Accepts either an `id_token` (from the Google
    Sign-In / One Tap library on the client) or a `code` (from a
    server-side OAuth redirect).

    First-time users get a personal organization auto-created from their
    name; they can rename it from settings later.
    """
    try:
        profile: GoogleProfile = resolve_google_identity(
            id_token=request.id_token,
            code=request.code,
            redirect_uri=request.redirect_uri,
        )
    except GoogleLoginError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    if not profile.email_verified:
        # We don't want to silently link a user by an unverified email.
        raise HTTPException(
            status_code=401,
            detail="Google account email is not verified.",
        )

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # 1. Try to find an existing user — first by (provider, provider_id),
            #    then by email so password users can link a Google identity.
            cur.execute(
                """
                SELECT user_id, org_id, email, role, auth_provider, auth_provider_id
                FROM platform_users
                WHERE auth_provider = 'google' AND auth_provider_id = %s
                """,
                (profile.sub,),
            )
            user = cur.fetchone()

            if user is None:
                cur.execute(
                    "SELECT user_id, org_id, email, role, auth_provider, auth_provider_id "
                    "FROM platform_users WHERE email = %s",
                    (profile.email,),
                )
                user = cur.fetchone()

            if user is None:
                # 2. New user — create a personal org + the user record.
                base_slug = _slug_from_email(profile.email)
                org_slug = base_slug
                suffix = 0
                while True:
                    cur.execute(
                        "SELECT 1 FROM organizations WHERE org_slug = %s",
                        (org_slug,),
                    )
                    if cur.fetchone() is None:
                        break
                    suffix += 1
                    org_slug = f"{base_slug}-{suffix}"

                org_name = (profile.name or profile.email.split('@', 1)[0]) + "'s workspace"
                cur.execute(
                    """
                    INSERT INTO organizations (org_name, org_slug, subscription_plan, subscription_status)
                    VALUES (%s, %s, 'free', 'active')
                    RETURNING org_id
                    """,
                    (org_name, org_slug),
                )
                org_id = cur.fetchone()['org_id']

                cur.execute(
                    """
                    INSERT INTO platform_users (
                        org_id, email, full_name, role, is_active, email_verified,
                        auth_provider, auth_provider_id, avatar_url
                    )
                    VALUES (%s, %s, %s, 'owner', true, true, 'google', %s, %s)
                    RETURNING user_id, org_id, email, role
                    """,
                    (org_id, profile.email, profile.name, profile.sub, profile.picture),
                )
                user = cur.fetchone()
                logger.info(
                    "Google sign-in: created user=%s org=%s for %s",
                    user['user_id'], org_id, profile.email,
                )
            else:
                # 3. Existing user — link Google identity if not already, refresh
                #    avatar/last_login_at.
                if user.get('auth_provider') != 'google' or user.get('auth_provider_id') != profile.sub:
                    cur.execute(
                        """
                        UPDATE platform_users
                        SET auth_provider = 'google',
                            auth_provider_id = %s,
                            email_verified = true,
                            avatar_url = COALESCE(%s, avatar_url),
                            last_login_at = NOW(),
                            updated_at = NOW()
                        WHERE user_id = %s
                        """,
                        (profile.sub, profile.picture, user['user_id']),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE platform_users
                        SET last_login_at = NOW(),
                            avatar_url = COALESCE(%s, avatar_url)
                        WHERE user_id = %s
                        """,
                        (profile.picture, user['user_id']),
                    )

            conn.commit()

            token_data = {
                "user_id": user['user_id'],
                "org_id": user['org_id'],
                "email": user['email'],
                "role": user['role'],
            }
            access_token = create_access_token(token_data)
            refresh_token = create_refresh_token({"user_id": user['user_id']})

            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                token_type="bearer",
                expires_in=3600,
            )

    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        logger.error("Google login error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Google sign-in failed.",
        )
    finally:
        DatabaseConnection.return_connection(conn)


# ---------------------------------------------------------------------------
# LinkedTrust IdP (OIDC) login — gives Google | Bluesky | LinkedTrust via the
# team identity provider. amebo is a confidential OIDC client; see
# src/auth_oauth/oidc_login.py. PKCE/state/nonce are carried in a short-lived
# signed cookie (no extra table). Unknown emails are created INACTIVE (pending
# approval); only is_active accounts receive a session.
# ---------------------------------------------------------------------------

from src.auth_oauth.oidc_login import (
    OidcConfig, OidcError, build_authorize_url, exchange_code,
    verify_id_token, new_pkce, new_state_nonce,
)

OIDC_TX_COOKIE = "amebo_oidc_tx"
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://amebo.linkedtrust.us").rstrip("/")


def _front(path: str) -> str:
    return f"{FRONTEND_URL}{path}"


@router.get("/oidc/login")
async def oidc_login(invite: str = None):
    """
    Begin LinkedTrust OIDC login: redirect the browser to the IdP.

    An optional ``invite`` token (from an SSO invite link) rides along in the
    signed tx cookie; the callback consumes it to admit the user into the
    inviting org. The invite link is just this endpoint with ``?invite=<token>``.
    """
    cfg = OidcConfig.from_env()
    state, nonce = new_state_nonce()
    verifier, challenge = new_pkce()
    url = build_authorize_url(cfg, state=state, nonce=nonce, code_challenge=challenge)
    tx_claims = {"oidc_state": state, "oidc_nonce": nonce, "oidc_verifier": verifier}
    if invite:
        tx_claims["oidc_invite"] = invite
    tx = create_access_token(tx_claims, expires_delta=timedelta(minutes=10))
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        OIDC_TX_COOKIE, tx, max_age=600, httponly=True, secure=True,
        samesite="lax", path="/api/auth/oidc",
    )
    return resp


@router.get("/oidc/callback")
async def oidc_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """IdP redirects here: verify, upsert (active-only), mint amebo session."""
    if error:
        return RedirectResponse(_front(f"/login?error={error}"), status_code=302)
    tx = request.cookies.get(OIDC_TX_COOKIE)
    if not tx or not code or not state:
        return RedirectResponse(_front("/login?error=invalid_request"), status_code=302)
    try:
        payload = decode_token(tx)
    except Exception:
        return RedirectResponse(_front("/login?error=expired"), status_code=302)
    if payload.get("oidc_state") != state:
        return RedirectResponse(_front("/login?error=state_mismatch"), status_code=302)

    cfg = OidcConfig.from_env()
    try:
        tokens = exchange_code(cfg, code=code, code_verifier=payload["oidc_verifier"])
        ident = verify_id_token(cfg, tokens["id_token"], nonce=payload["oidc_nonce"])
    except (OidcError, KeyError) as exc:
        logger.warning("OIDC callback failed: %s", exc)
        return RedirectResponse(_front("/login?error=auth_failed"), status_code=302)
    # No-email identities (e.g. Bluesky) are fine — we key on the stable subject.
    email = ident.email or f"lt-{ident.sub}@users.amebo.local"
    invite_token = payload.get("oidc_invite")

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # A valid (live, unexpired) invite token admits the user into its org.
            invite = None
            if invite_token:
                cur.execute(
                    "SELECT id, org_id, role FROM org_invites "
                    "WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > NOW()",
                    (hashlib.sha256(invite_token.encode()).hexdigest(),),
                )
                invite = cur.fetchone()

            # Resolve by stable provider subject first (works without a real
            # email); fall back to email so an existing account links.
            cur.execute(
                "SELECT user_id, org_id, email, role, is_active FROM platform_users "
                "WHERE auth_provider = 'linkedtrust' AND auth_provider_id = %s",
                (ident.sub,),
            )
            user = cur.fetchone()
            if user is None and ident.email:
                cur.execute(
                    "SELECT user_id, org_id, email, role, is_active FROM platform_users WHERE email = %s",
                    (ident.email,),
                )
                user = cur.fetchone()

            if invite is not None:
                # Invited: admit into the invite's org/role, activate, consume.
                if user is None:
                    cur.execute(
                        "INSERT INTO platform_users "
                        "(org_id, email, full_name, role, is_active, email_verified, auth_provider, auth_provider_id) "
                        "VALUES (%s, %s, %s, %s, true, true, 'linkedtrust', %s) "
                        "RETURNING user_id, org_id, email, role",
                        (invite["org_id"], email, ident.name, invite["role"], ident.sub),
                    )
                else:
                    cur.execute(
                        "UPDATE platform_users SET org_id = %s, role = %s, is_active = true, "
                        "auth_provider = 'linkedtrust', auth_provider_id = %s, "
                        "last_login_at = NOW(), updated_at = NOW() WHERE user_id = %s "
                        "RETURNING user_id, org_id, email, role",
                        (invite["org_id"], invite["role"], ident.sub, user["user_id"]),
                    )
                user = cur.fetchone()
                cur.execute(
                    "UPDATE org_invites SET consumed_at = NOW(), consumed_by_user_id = %s WHERE id = %s",
                    (user["user_id"], invite["id"]),
                )
                conn.commit()
                logger.info("OIDC: invite consumed — %s admitted to org %s as %s", email, user["org_id"], user["role"])
            else:
                # No invite: the standard gate (approval required for new identities).
                if user is not None:
                    cur.execute(
                        "UPDATE platform_users SET auth_provider = 'linkedtrust', auth_provider_id = %s WHERE user_id = %s",
                        (ident.sub, user["user_id"]),
                    )

                if user is None:
                    base = _slug_from_email(email)
                    slug = base
                    n = 0
                    while True:
                        cur.execute("SELECT 1 FROM organizations WHERE org_slug = %s", (slug,))
                        if cur.fetchone() is None:
                            break
                        n += 1
                        slug = f"{base}-{n}"
                    org_name = (ident.name or email.split("@", 1)[0]) + "'s workspace"
                    cur.execute(
                        "INSERT INTO organizations (org_name, org_slug, subscription_plan, subscription_status) "
                        "VALUES (%s, %s, 'free', 'active') RETURNING org_id",
                        (org_name, slug),
                    )
                    org_id = cur.fetchone()["org_id"]
                    cur.execute(
                        "INSERT INTO platform_users "
                        "(org_id, email, full_name, role, is_active, email_verified, auth_provider, auth_provider_id) "
                        "VALUES (%s, %s, %s, 'owner', false, true, 'linkedtrust', %s)",
                        (org_id, email, ident.name, ident.sub),
                    )
                    conn.commit()
                    logger.info("OIDC: created PENDING (inactive) user %s (sub=%s)", email, ident.sub)
                    return RedirectResponse(_front("/login?error=pending_approval"), status_code=302)

                if not user["is_active"]:
                    logger.info("OIDC: inactive user %s denied", email)
                    return RedirectResponse(_front("/login?error=pending_approval"), status_code=302)

                cur.execute(
                    "UPDATE platform_users SET last_login_at = NOW(), updated_at = NOW() WHERE user_id = %s",
                    (user["user_id"],),
                )
                conn.commit()

            access_token = create_access_token({
                "user_id": user["user_id"], "org_id": user["org_id"],
                "email": user["email"], "role": user["role"],
            })
            refresh_token = create_refresh_token({"user_id": user["user_id"]})
    except Exception as exc:
        conn.rollback()
        logger.error("OIDC callback DB error: %s", exc, exc_info=True)
        return RedirectResponse(_front("/login?error=server_error"), status_code=302)
    finally:
        DatabaseConnection.return_connection(conn)

    # Hand tokens to the SPA via URL fragment (kept out of server logs).
    resp = RedirectResponse(
        _front(f"/auth/callback#access_token={access_token}&refresh_token={refresh_token}"),
        status_code=302,
    )
    resp.delete_cookie(OIDC_TX_COOKIE, path="/api/auth/oidc")
    return resp
