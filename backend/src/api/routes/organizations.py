"""
Organizations routes - manage organization settings, users, invites
"""

from fastapi import APIRouter, HTTPException, status, Depends
from psycopg2 import extras
import logging

from src.api.models import (
    OrganizationResponse,
    OrganizationUpdateRequest,
    InviteUserRequest,
    UserResponse,
    DashboardStats
)
from src.api.auth_utils import get_current_user, require_admin
from src.db.connection import DatabaseConnection

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/me", response_model=OrganizationResponse)
async def get_my_organization(current_user: dict = Depends(get_current_user)):
    """
    Get current user's organization details
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT org_id, org_name, org_slug, email_domain, subscription_plan,
                       subscription_status, max_workspaces, max_users, max_documents,
                       is_active, created_at
                FROM organizations
                WHERE org_id = %s
                """,
                (current_user['org_id'],)
            )
            org = cur.fetchone()

            if not org:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found"
                )

            return OrganizationResponse(**org)

    finally:
        DatabaseConnection.return_connection(conn)


@router.patch("/me", response_model=OrganizationResponse)
async def update_organization(
    request: OrganizationUpdateRequest,
    current_user: dict = Depends(require_admin)
):
    """
    Update organization settings (admin only)
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Build dynamic update query
            updates = []
            params = []

            if request.org_name:
                updates.append("org_name = %s")
                params.append(request.org_name)

            if request.email_domain:
                updates.append("email_domain = %s")
                params.append(request.email_domain)

            if not updates:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No fields to update"
                )

            params.append(current_user['org_id'])

            cur.execute(
                f"""
                UPDATE organizations
                SET {', '.join(updates)}, updated_at = NOW()
                WHERE org_id = %s
                RETURNING org_id, org_name, org_slug, email_domain, subscription_plan,
                          subscription_status, max_workspaces, max_users, max_documents,
                          is_active, created_at
                """,
                params
            )
            org = cur.fetchone()

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, 'org_updated', 'organization', %s, %s)
                """,
                (current_user['org_id'], current_user['user_id'],
                 str(current_user['org_id']), extras.Json(dict(request)))
            )

            conn.commit()

            return OrganizationResponse(**org)

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Update organization error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update organization"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/users", response_model=list[UserResponse])
async def list_organization_users(current_user: dict = Depends(get_current_user)):
    """
    List all users in the organization
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, org_id, email, full_name, role, is_active,
                       email_verified, created_at
                FROM platform_users
                WHERE org_id = %s
                ORDER BY created_at DESC
                """,
                (current_user['org_id'],)
            )
            users = cur.fetchall()

            return [UserResponse(**user) for user in users]

    finally:
        DatabaseConnection.return_connection(conn)


@router.post("/users/invite", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    request: InviteUserRequest,
    current_user: dict = Depends(require_admin)
):
    """
    Invite a new user to the organization (admin only)
    Creates user account with temporary password
    TODO: Send email invitation
    """
    from src.api.auth_utils import hash_password
    import secrets

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Check if email already exists
            cur.execute(
                "SELECT user_id FROM platform_users WHERE email = %s",
                (request.email,)
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User with this email already exists"
                )

            # Check org user limit
            cur.execute(
                """
                SELECT max_users,
                       (SELECT COUNT(*) FROM platform_users WHERE org_id = o.org_id) as current_users
                FROM organizations o
                WHERE org_id = %s
                """,
                (current_user['org_id'],)
            )
            limits = cur.fetchone()

            if limits['current_users'] >= limits['max_users']:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Organization user limit reached ({limits['max_users']}). Upgrade plan to add more users."
                )

            # Generate temporary password
            temp_password = secrets.token_urlsafe(16)
            password_hash = hash_password(temp_password)

            # Create user
            cur.execute(
                """
                INSERT INTO platform_users (org_id, email, password_hash, full_name, role, is_active)
                VALUES (%s, %s, %s, %s, %s, true)
                RETURNING user_id, org_id, email, full_name, role, is_active,
                          email_verified, created_at
                """,
                (current_user['org_id'], request.email, password_hash, request.full_name, request.role)
            )
            new_user = cur.fetchone()

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, 'user_invited', 'user', %s, %s)
                """,
                (current_user['org_id'], current_user['user_id'],
                 str(new_user['user_id']), extras.Json({'invited_by': current_user['email']}))
            )

            conn.commit()

            logger.info(f"User invited: {request.email} by {current_user['email']}")
            # TODO: Send email with temp_password

            return UserResponse(**new_user)

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Invite user error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invite user"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(current_user: dict = Depends(get_current_user)):
    """
    Get organization dashboard statistics
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Get workspace count
            cur.execute(
                """
                SELECT COUNT(*) as total_workspaces
                FROM org_workspaces
                WHERE org_id = %s
                """,
                (current_user['org_id'],)
            )
            workspace_count = cur.fetchone()['total_workspaces']

            # Get document count
            cur.execute(
                """
                SELECT COUNT(*) as total_documents
                FROM documents
                WHERE org_id = %s AND is_active = true
                """,
                (current_user['org_id'],)
            )
            document_count = cur.fetchone()['total_documents']

            # Get message count from all workspaces
            cur.execute(
                """
                SELECT COUNT(*) as total_messages
                FROM message_metadata m
                JOIN org_workspaces ow ON m.workspace_id = ow.workspace_id
                WHERE ow.org_id = %s AND m.deleted_at IS NULL
                """,
                (current_user['org_id'],)
            )
            message_count = cur.fetchone()['total_messages']

            # Get queries this month (placeholder - needs usage_metrics implementation)
            queries_this_month = 0

            # Get most active channel (from org's workspaces)
            cur.execute(
                """
                SELECT m.channel_name, COUNT(*) as msg_count
                FROM message_metadata m
                JOIN org_workspaces ow ON m.workspace_id = ow.workspace_id
                WHERE ow.org_id = %s
                  AND m.deleted_at IS NULL
                  AND m.created_at > NOW() - INTERVAL '30 days'
                GROUP BY m.channel_name
                ORDER BY msg_count DESC
                LIMIT 1
                """,
                (current_user['org_id'],)
            )
            most_active = cur.fetchone()
            most_active_channel = most_active['channel_name'] if most_active else None

            return DashboardStats(
                total_workspaces=workspace_count,
                total_documents=document_count,
                total_messages=message_count,
                total_queries_this_month=queries_this_month,
                most_active_channel=most_active_channel,
                most_queried_topic=None  # TODO: Implement topic tracking
            )

    finally:
        DatabaseConnection.return_connection(conn)
