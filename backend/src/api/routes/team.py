"""
Team management routes - invite users, manage roles
"""

from fastapi import APIRouter, HTTPException, status, Depends
from psycopg2 import extras
import logging
import bcrypt
import hashlib
import os
import secrets
import string
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from src.api.models import TeamMember, InviteUserRequest, InviteUserResponse
from src.db.connection import DatabaseConnection
from src.services.email_service import email_service

# Use proper auth middleware
from src.api.middleware.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/members")
async def get_team_members(current_user: dict = Depends(get_current_user)):
    """Get all team members for the organization"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    user_id,
                    email,
                    full_name,
                    role,
                    is_active,
                    email_verified,
                    last_login_at,
                    created_at
                FROM platform_users 
                WHERE org_id = %s
                ORDER BY is_active DESC, created_at DESC
            """, (current_user.get('org_id', 1),))
            
            members = cur.fetchall()
            
            return {
                "members": [
                    {
                        "user_id": member["user_id"],
                        "name": member["full_name"] or member["email"].split("@")[0],
                        "email": member["email"],
                        "role": member["role"],
                        "status": "active" if member["is_active"] and member["email_verified"] else "pending",
                        "last_active": member["last_login_at"].isoformat() if member["last_login_at"] else None,
                        "invited_at": member["created_at"].isoformat()
                    }
                    for member in members
                ]
            }
    finally:
        DatabaseConnection.return_connection(conn)


@router.post("/invite", response_model=InviteUserResponse)
async def invite_user(
    request: InviteUserRequest,
    current_user: dict = Depends(get_current_user)
):
    """Invite a new user to the organization"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Check if user already exists globally (email is unique across all orgs)
            cur.execute("""
                SELECT user_id, org_id, is_active FROM platform_users 
                WHERE email = %s
            """, (request.email,))
            
            existing_user = cur.fetchone()
            if existing_user:
                if existing_user["org_id"] == current_user.get('org_id', 1):
                    if existing_user["is_active"]:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="User with this email already exists in your organization"
                        )
                    else:
                        # Reactivate the user instead of creating new
                        cur.execute("""
                            UPDATE platform_users 
                            SET is_active = true, role = %s, updated_at = NOW()
                            WHERE email = %s AND org_id = %s
                            RETURNING user_id
                        """, (request.role, request.email, current_user.get('org_id', 1)))
                        
                        user_id = cur.fetchone()["user_id"]
                        conn.commit()
                        
                        return InviteUserResponse(
                            success=True,
                            message="User reactivated successfully!",
                            user_id=user_id
                        )
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="This email is already registered with another organization"
                    )
            
            # Generate temporary password
            temp_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
            logger.info(f"temp password: {temp_password}")
            password_hash = bcrypt.hashpw(temp_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            # Create user
            cur.execute("""
                INSERT INTO platform_users (org_id, email, password_hash, full_name, role, is_active, email_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING user_id
            """, (
                current_user.get('org_id', 1),
                request.email,
                password_hash,
                request.email.split('@')[0],  # Default name from email
                request.role,
                True,
                False  # Will be verified when they set their password
            ))
            
            user_id = cur.fetchone()["user_id"]
            
            # Log the invitation (never log passwords or secrets)
            cur.execute("""
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                current_user.get('org_id', 1),
                current_user.get('user_id'),
                'user_invited',
                'user',
                str(user_id),
                extras.Json({
                    'invited_email': request.email,
                    'role': request.role
                })
            ))
            
            conn.commit()

            # Get org name for the email
            with conn.cursor() as org_cur:
                org_cur.execute("SELECT org_name FROM organizations WHERE org_id = %s", (current_user.get('org_id', 1),))
                org_row = org_cur.fetchone()
                org_name = org_row[0] if org_row else "your team"

            # Send invitation email
            email_sent = email_service.send_invitation_email(
                to_email=request.email,
                temp_password=temp_password,
                org_name=org_name
            )
            
            if email_sent:
                message = "User invited successfully! An email has been sent with login instructions."
            else:
                message = f"User invited successfully. Temporary password: {temp_password} (Email not configured)"
            
            return InviteUserResponse(
                success=True,
                message=message,
                user_id=user_id
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to invite user: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invite user"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.put("/members/{user_id}/activate")
async def activate_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Reactivate a deactivated user"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            # Check if user exists in the same org and is inactive
            cur.execute("""
                SELECT user_id FROM platform_users 
                WHERE user_id = %s AND org_id = %s AND is_active = false
            """, (user_id, current_user.get('org_id', 1)))
            
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found or already active"
                )
            
            # Reactivate user
            cur.execute("""
                UPDATE platform_users 
                SET is_active = true, updated_at = NOW()
                WHERE user_id = %s AND org_id = %s
            """, (user_id, current_user.get('org_id', 1)))
            
            # Log the activation
            cur.execute("""
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                current_user.get('org_id', 1),
                current_user.get('user_id'),
                'user_activated',
                'user',
                str(user_id),
                extras.Json({})
            ))
            
            conn.commit()
            
            return {"success": True, "message": "User activated successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to activate user: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate user"
        )
    finally:
        DatabaseConnection.return_connection(conn)


class RoleUpdateRequest(BaseModel):
    role: str


@router.put("/members/{user_id}/role")
async def update_user_role(
    user_id: int,
    request: RoleUpdateRequest,
    current_user: dict = Depends(get_current_user)
):
    """Update a user's role"""
    role = request.role
    valid_roles = ['owner', 'admin', 'member', 'viewer']
    if role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )

    # Only owners can assign the owner role
    if role == 'owner' and current_user.get('role') != 'owner':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners can assign the owner role"
        )
    
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            # Check if user exists in the same org
            cur.execute("""
                SELECT user_id FROM platform_users 
                WHERE user_id = %s AND org_id = %s
            """, (user_id, current_user.get('org_id', 1)))
            
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            # Update role
            cur.execute("""
                UPDATE platform_users 
                SET role = %s, updated_at = NOW()
                WHERE user_id = %s AND org_id = %s
            """, (role, user_id, current_user.get('org_id', 1)))
            
            # Log the change
            cur.execute("""
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                current_user.get('org_id', 1),
                current_user.get('user_id'),
                'user_role_updated',
                'user',
                str(user_id),
                extras.Json({'new_role': role})
            ))
            
            conn.commit()
            
            return {"success": True, "message": "User role updated successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user role: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user role"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.put("/members/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Deactivate a user (soft delete)"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            # Check if user exists in the same org
            cur.execute("""
                SELECT user_id FROM platform_users 
                WHERE user_id = %s AND org_id = %s AND is_active = true
            """, (user_id, current_user.get('org_id', 1)))
            
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found or already inactive"
                )
            
            # Deactivate user
            cur.execute("""
                UPDATE platform_users 
                SET is_active = false, updated_at = NOW()
                WHERE user_id = %s AND org_id = %s
            """, (user_id, current_user.get('org_id', 1)))
            
            # Log the deactivation
            cur.execute("""
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                current_user.get('org_id', 1),
                current_user.get('user_id'),
                'user_deactivated',
                'user',
                str(user_id),
                extras.Json({})
            ))
            
            conn.commit()
            
            return {"success": True, "message": "User deactivated successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to deactivate user: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate user"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.delete("/members/{user_id}")
async def delete_user(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Permanently delete a user"""
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            # Check if user exists in the same org
            cur.execute("""
                SELECT user_id FROM platform_users 
                WHERE user_id = %s AND org_id = %s
            """, (user_id, current_user.get('org_id', 1)))
            
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            # Log the deletion before removing
            cur.execute("""
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                current_user.get('org_id', 1),
                current_user.get('user_id'),
                'user_deleted',
                'user',
                str(user_id),
                extras.Json({})
            ))
            
            # Permanently delete user
            cur.execute("""
                DELETE FROM platform_users 
                WHERE user_id = %s AND org_id = %s
            """, (user_id, current_user.get('org_id', 1)))
            
            conn.commit()
            
            return {"success": True, "message": "User deleted permanently"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete user: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user"
        )
    finally:
        DatabaseConnection.return_connection(conn)


# ---------------------------------------------------------------------------
# SSO invite links
# ---------------------------------------------------------------------------


class InviteLinkRequest(BaseModel):
    role: str = "member"
    expires_in_days: int = 7


class InviteLinkResponse(BaseModel):
    invite_url: str
    role: str
    expires_at: str


@router.post("/invite-link", response_model=InviteLinkResponse)
async def create_invite_link(
    request: InviteLinkRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Mint a one-time SSO invite link for this org. Owner/admin only.

    The link is just the LinkedTrust OIDC login carrying an invite token; when
    the invitee clicks it and signs in, the callback admits them into this org
    (active, with the given role) and consumes the invite. No temp passwords.
    """
    if current_user.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only owners/admins can create invite links.")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    days = max(1, min(int(request.expires_in_days or 7), 30))
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO org_invites (token_hash, org_id, role, created_by_user_id, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (token_hash, current_user["org_id"], request.role,
                 current_user.get("user_id"), expires_at),
            )
            conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("create_invite_link failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create invite link.")
    finally:
        DatabaseConnection.return_connection(conn)

    # The invite link IS the OIDC login URL with the token. Derive the login
    # endpoint from OIDC_REDIRECT_URI (.../oidc/callback -> .../oidc/login).
    redirect_uri = os.getenv("OIDC_REDIRECT_URI", "")
    login_url = (
        redirect_uri.rsplit("/callback", 1)[0] + "/login"
        if redirect_uri.endswith("/callback")
        else "/api/auth/oidc/login"
    )
    logger.info("invite link minted: org=%s role=%s by user=%s",
                current_user["org_id"], request.role, current_user.get("user_id"))
    return InviteLinkResponse(
        invite_url=f"{login_url}?invite={token}",
        role=request.role,
        expires_at=expires_at.isoformat(),
    )
