"""
Team management routes - invite users, manage roles
"""

from fastapi import APIRouter, HTTPException, status, Depends
from psycopg2 import extras
import logging
import bcrypt
import secrets
import string
from datetime import datetime, timedelta

from src.api.models import TeamMember, InviteUserRequest, InviteUserResponse
from src.db.connection import DatabaseConnection
from src.services.email_service import email_service

# Simple auth for development
async def get_current_user():
    return {
        "user_id": 1,
        "org_id": 8,  # Updated to match the test user's org
        "email": "orjienekenechukwu@gmail.com"
    }

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
            
            # Log the invitation
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
                    'role': request.role,
                    'temp_password': temp_password  # In production, send via email
                })
            ))
            
            conn.commit()
            
            # Send invitation email
            email_sent = email_service.send_invitation_email(
                to_email=request.email,
                temp_password=temp_password,
                org_name="Your Organization"  # TODO: Get from database
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


@router.put("/members/{user_id}/role")
async def update_user_role(
    user_id: int,
    role: str,
    current_user: dict = Depends(get_current_user)
):
    """Update a user's role"""
    if role not in ['admin', 'member', 'viewer']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Must be 'admin', 'member', or 'viewer'"
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