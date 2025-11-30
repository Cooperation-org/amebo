"""
Workspace Authorization Middleware

CRITICAL SECURITY: Verifies users have access to requested workspaces.
Prevents one organization from accessing another's workspace data.
"""

from fastapi import HTTPException, status
from src.db.connection import DatabaseConnection
import logging

logger = logging.getLogger(__name__)


def verify_workspace_access(workspace_id: str, org_id: int) -> None:
    """
    Verify that an organization has access to a workspace.

    Args:
        workspace_id: The workspace being accessed
        org_id: The organization making the request

    Raises:
        HTTPException: 403 if organization doesn't have access to workspace
        HTTPException: 404 if workspace doesn't exist

    Security: This is a CRITICAL security function.
    It prevents workspace data leakage between organizations.
    """
    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace_id is required"
        )

    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="org_id is required"
        )

    conn = DatabaseConnection.get_connection()
    try:
        cur = conn.cursor()

        # Check if workspace exists
        cur.execute(
            "SELECT 1 FROM workspaces WHERE workspace_id = %s",
            (workspace_id,)
        )

        if not cur.fetchone():
            logger.warning(f"Workspace not found: {workspace_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {workspace_id} not found"
            )

        # Check if org has access to this workspace
        cur.execute(
            """
            SELECT 1 FROM workspaces
            WHERE org_id = %s AND workspace_id = %s AND is_active = true
            """,
            (org_id, workspace_id)
        )

        if not cur.fetchone():
            logger.warning(
                f"SECURITY: Org {org_id} attempted to access workspace {workspace_id} without permission"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this workspace"
            )

        logger.info(f"Access granted: Org {org_id} → Workspace {workspace_id}")

    finally:
        DatabaseConnection.return_connection(conn)


def get_workspace_ids_for_org(org_id: int) -> list[str]:
    """
    Get all workspace IDs that an organization has access to.
    """
    conn = DatabaseConnection.get_connection()
    try:
        cur = conn.cursor()

        # Use workspaces table directly with org_id column
        cur.execute(
            """
            SELECT workspace_id
            FROM workspaces
            WHERE org_id = %s AND is_active = true
            """,
            (org_id,)
        )

        workspace_ids = [row[0] for row in cur.fetchall()]
        logger.debug(f"Org {org_id} has access to {len(workspace_ids)} workspaces")

        return workspace_ids

    except Exception as e:
        logger.error(f"Error getting workspaces for org {org_id}: {e}")
        return []
    finally:
        DatabaseConnection.return_connection(conn)
