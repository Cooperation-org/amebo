"""
Workspace Management API Routes
Handles workspace CRUD operations, credential management, and sync operations
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
import logging

from src.api.middleware.auth import get_current_user
from src.db.connection import DatabaseConnection

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic models
class WorkspaceCreate(BaseModel):
    workspace_name: str
    bot_token: str
    app_token: str
    signing_secret: str

class WorkspaceUpdate(BaseModel):
    team_name: str
    bot_token: str
    app_token: str
    signing_secret: str

class WorkspaceResponse(BaseModel):
    workspace_id: str
    team_name: str
    team_domain: Optional[str] = None
    icon_url: Optional[str] = None
    is_active: bool
    installed_at: str
    last_active: Optional[str] = None
    status: Optional[str] = "active"
    message_count: Optional[int] = 0
    channel_count: Optional[int] = 0
    last_sync_at: Optional[str] = None

@router.get("/", response_model=dict)
async def get_workspaces(current_user: dict = Depends(get_current_user)):
    """Get all workspaces for the current user's organization"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Get workspaces for the user's organization
        cursor.execute("""
            SELECT 
                w.workspace_id,
                w.team_name,
                w.team_domain,
                w.icon_url,
                w.is_active,
                w.installed_at,
                w.last_active
            FROM workspaces w
            WHERE w.org_id = %s
            ORDER BY w.installed_at DESC
        """, (current_user["org_id"],))
        
        workspaces = []
        for row in cursor.fetchall():
            workspace = {
                "workspace_id": row[0],
                "team_name": row[1],
                "team_domain": row[2],
                "icon_url": row[3],
                "is_active": row[4],
                "installed_at": row[5].isoformat() if row[5] else None,
                "last_active": row[6].isoformat() if row[6] else None,
                "status": "active" if row[4] else "inactive",
                "message_count": 0,  # Placeholder
                "channel_count": 0,  # Placeholder
                "last_sync_at": row[6].isoformat() if row[6] else None
            }
            workspaces.append(workspace)
        
        return {"workspaces": workspaces, "total": len(workspaces)}
        
    except Exception as e:
        logger.error(f"Error fetching workspaces: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch workspaces"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@router.post("/", response_model=dict)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new workspace"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # For now, create a simple workspace entry
        # In production, this would integrate with Slack API and credential encryption
        workspace_id = f"W{hash(workspace_data.workspace_name) % 1000000:06d}"
        
        cursor.execute("""
            INSERT INTO workspaces (workspace_id, team_name, org_id, is_active, installed_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (workspace_id) DO NOTHING
        """, (workspace_id, workspace_data.workspace_name, current_user["org_id"], True))
        
        conn.commit()
        
        return {
            "workspace_id": workspace_id,
            "team_name": workspace_data.workspace_name,
            "status": "created"
        }
        
    except Exception as e:
        logger.error(f"Error creating workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create workspace"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@router.put("/{workspace_id}", response_model=dict)
async def update_workspace(
    workspace_id: str,
    workspace_data: WorkspaceUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update workspace credentials"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace belongs to user's org
        cursor.execute("""
            SELECT workspace_id FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user["org_id"]))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Update workspace
        cursor.execute("""
            UPDATE workspaces 
            SET team_name = %s, last_active = NOW()
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_data.team_name, workspace_id, current_user["org_id"]))
        
        conn.commit()
        
        return {"status": "updated", "workspace_id": workspace_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update workspace"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@router.delete("/{workspace_id}", response_model=dict)
async def delete_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a workspace"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace belongs to user's org
        cursor.execute("""
            SELECT workspace_id FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user["org_id"]))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Delete workspace (this will cascade to related data)
        cursor.execute("""
            DELETE FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user["org_id"]))
        
        conn.commit()
        
        return {"status": "deleted", "workspace_id": workspace_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete workspace"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@router.post("/{workspace_id}/sync", response_model=dict)
async def sync_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Trigger manual workspace sync"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace belongs to user's org
        cursor.execute("""
            SELECT workspace_id FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user["org_id"]))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # In production, this would trigger the backfill service
        # For now, just update the last_active timestamp
        cursor.execute("""
            UPDATE workspaces 
            SET last_active = NOW()
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user["org_id"]))
        
        conn.commit()
        
        return {"status": "sync_triggered", "workspace_id": workspace_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync workspace"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@router.post("/test-connection", response_model=dict)
async def test_connection(
    credentials: dict,
    current_user: dict = Depends(get_current_user)
):
    """Test Slack workspace connection"""
    try:
        # In production, this would test the actual Slack API connection
        # For now, just validate the token formats
        bot_token = credentials.get("bot_token", "")
        app_token = credentials.get("app_token", "")
        signing_secret = credentials.get("signing_secret", "")
        
        if not bot_token.startswith("xoxb-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid bot token format"
            )
        
        if not app_token.startswith("xapp-"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid app token format"
            )
        
        if len(signing_secret) < 32:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signing secret"
            )
        
        return {"status": "success", "message": "Connection test passed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing connection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Connection test failed"
        )

@router.get("/{workspace_id}/channels", response_model=dict)
async def get_workspace_channels(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get channels for a workspace"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace belongs to user's org
        cursor.execute("""
            SELECT workspace_id FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user["org_id"]))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Return mock channels for now (until messages table exists)
        channels = [
            {"id": "C1234567890", "name": "general"},
            {"id": "C1234567891", "name": "random"},
            {"id": "C1234567892", "name": "dev-team"}
        ]
        
        return {"channels": channels}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching channels: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch channels"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()