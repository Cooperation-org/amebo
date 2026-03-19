"""
Workspace Management API Routes
Handles workspace CRUD operations, credential management, and sync operations
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
import logging

from src.api.middleware.auth import get_current_user
from src.api.utils.errors import get_safe_error
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
    """Get all workspaces with real message/channel counts"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()

        org_id = current_user.get("org_id")

        cursor.execute("""
            SELECT
                w.workspace_id,
                w.team_name,
                w.team_domain,
                w.icon_url,
                w.is_active,
                w.created_at,
                w.updated_at,
                COALESCE(ch.cnt, 0) AS channel_count,
                ch.last_sync_at
            FROM workspaces w
            LEFT JOIN (
                SELECT workspace_id,
                       COUNT(*) AS cnt,
                       MAX(last_sync) AS last_sync_at
                FROM channels
                WHERE is_archived = FALSE
                GROUP BY workspace_id
            ) ch ON ch.workspace_id = w.workspace_id
            WHERE w.org_id = %s
            ORDER BY w.team_name
        """, (org_id,))

        workspaces = []
        for row in cursor.fetchall():
            workspace_id = row[0]

            # Get message count from ChromaDB
            message_count = 0
            try:
                from src.db.chromadb_client import ChromaDBClient
                chromadb = ChromaDBClient()
                stats = chromadb.get_collection_stats(workspace_id)
                message_count = stats.get('message_count', 0)
            except Exception as chroma_err:
                logger.warning(f"Could not get ChromaDB stats for {workspace_id}: {chroma_err}")

            workspaces.append({
                "workspace_id": workspace_id,
                "team_name": row[1],
                "team_domain": row[2],
                "icon_url": row[3],
                "is_active": row[4],
                "installed_at": row[5].isoformat() if row[5] else None,
                "last_active": row[6].isoformat() if row[6] else None,
                "status": "active" if row[4] else "inactive",
                "message_count": message_count,
                "channel_count": row[7],
                "last_sync_at": row[8].isoformat() if row[8] else None,
            })

        return {"workspaces": workspaces, "total": len(workspaces)}

    except Exception as e:
        logger.error(f"Error fetching workspaces: {e}", exc_info=True)
        return {"workspaces": [], "total": 0}
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)

@router.post("/", response_model=dict)
async def create_workspace(
    workspace_data: WorkspaceCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new workspace with automatic backfill"""
    try:
        # First test the connection
        from slack_sdk.web.async_client import AsyncWebClient
        
        client = AsyncWebClient(token=workspace_data.bot_token)
        auth_response = await client.auth_test()
        team_info = await client.team_info()
        
        workspace_id = team_info["team"]["id"]
        team_name = team_info["team"]["name"]
        
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Create workspace entry
        cursor.execute("""
            INSERT INTO workspaces (workspace_id, team_name, is_active, org_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (workspace_id) DO UPDATE SET 
                team_name = EXCLUDED.team_name,
                is_active = EXCLUDED.is_active,
                org_id = EXCLUDED.org_id
        """, (workspace_id, team_name, True, current_user.get("org_id", 8)))
        
        # Store credentials using the credential service (encrypted)
        from src.services.credential_service import CredentialService
        cred_service = CredentialService()
        cred_service.store_credentials(
            workspace_id=workspace_id,
            bot_token=workspace_data.bot_token,
            app_token=workspace_data.app_token,
            signing_secret=workspace_data.signing_secret
        )
        
        conn.commit()
        
        # Trigger automatic backfill
        try:
            from src.services.backfill_service import BackfillService
            backfill_service = BackfillService(workspace_id=workspace_id, bot_token=workspace_data.bot_token)
            
            # Start backfill in background (last 7 days)
            import asyncio
            asyncio.create_task(backfill_service.backfill_messages(days=90))
            
            logger.info(f"Started automatic backfill for workspace {workspace_id}")
        except Exception as backfill_error:
            logger.warning(f"Backfill failed but workspace created: {backfill_error}")
        
        return {
            "workspace_id": workspace_id,
            "team_name": team_name,
            "status": "created",
            "backfill_started": True
        }
        
    except Exception as e:
        logger.error(f"Error creating workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_safe_error('create_workspace')
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)

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
        """, (workspace_id, current_user.get("org_id", 1)))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Update workspace
        cursor.execute("""
            UPDATE workspaces 
            SET team_name = %s, updated_at = NOW()
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_data.team_name, workspace_id, current_user.get("org_id", 1)))
        
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
            DatabaseConnection.return_connection(conn)

@router.delete("/{workspace_id}", response_model=dict)
async def delete_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a workspace and all associated documents"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace belongs to user's org
        cursor.execute("""
            SELECT workspace_id FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user.get("org_id", 8)))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Get ChromaDB collections to clean up
        cursor.execute("""
            SELECT chromadb_collection FROM documents 
            WHERE workspace_id = %s AND chromadb_collection IS NOT NULL
        """, (workspace_id,))
        
        collections_to_delete = [row[0] for row in cursor.fetchall()]
        
        # Delete associated documents first
        cursor.execute("""
            DELETE FROM documents WHERE workspace_id = %s
        """, (workspace_id,))
        
        # Delete workspace
        cursor.execute("""
            DELETE FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user.get("org_id", 8)))
        
        conn.commit()
        
        # Clean up ChromaDB collections
        deleted_collections = []
        try:
            import chromadb
            chroma_client = chromadb.PersistentClient(path='./chroma_db')
            existing_collections = [col.name for col in chroma_client.list_collections()]
            
            for collection_name in collections_to_delete:
                if collection_name in existing_collections:
                    chroma_client.delete_collection(collection_name)
                    deleted_collections.append(collection_name)
                    logger.info(f"Deleted ChromaDB collection: {collection_name}")
        except Exception as chroma_error:
            logger.warning(f"ChromaDB cleanup failed: {chroma_error}")
        
        return {
            "status": "deleted", 
            "workspace_id": workspace_id,
            "documents_deleted": len(collections_to_delete),
            "collections_deleted": deleted_collections
        }
        
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
            DatabaseConnection.return_connection(conn)

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
        """, (workspace_id, current_user.get("org_id", 1)))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Update timestamp
        cursor.execute("""
            UPDATE workspaces 
            SET updated_at = NOW()
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user.get("org_id", 1)))
        
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
            DatabaseConnection.return_connection(conn)

@router.patch("/{workspace_id}/deactivate", response_model=dict)
async def deactivate_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Deactivate a workspace (soft delete)"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace belongs to user's org
        cursor.execute("""
            SELECT workspace_id FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user.get("org_id", 1)))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Deactivate workspace
        cursor.execute("""
            UPDATE workspaces 
            SET is_active = false, updated_at = NOW()
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user.get("org_id", 1)))
        
        conn.commit()
        
        return {"status": "deactivated", "workspace_id": workspace_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deactivate workspace"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)

@router.patch("/{workspace_id}/activate", response_model=dict)
async def activate_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Reactivate a workspace"""
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Verify workspace belongs to user's org
        cursor.execute("""
            SELECT workspace_id FROM workspaces 
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user.get("org_id", 1)))
        
        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )
        
        # Activate workspace
        cursor.execute("""
            UPDATE workspaces 
            SET is_active = true, updated_at = NOW()
            WHERE workspace_id = %s AND org_id = %s
        """, (workspace_id, current_user.get("org_id", 1)))
        
        conn.commit()
        
        return {"status": "activated", "workspace_id": workspace_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating workspace: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to activate workspace"
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)

@router.get("/{workspace_id}/test", response_model=dict)
async def test_existing_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Test connection for an existing workspace using stored credentials"""
    try:
        from slack_sdk.web.async_client import AsyncWebClient

        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()

        # Get stored credentials
        cursor.execute("""
            SELECT i.bot_token FROM installations i
            JOIN workspaces w ON i.workspace_id = w.workspace_id
            WHERE w.workspace_id = %s AND w.org_id = %s AND i.is_active = true
        """, (workspace_id, current_user.get("org_id")))

        result = cursor.fetchone()
        if not result:
            return {"success": False, "error": "No credentials found for this workspace"}

        bot_token = result[0]

        # Test the connection
        client = AsyncWebClient(token=bot_token)
        auth_response = await client.auth_test()

        return {
            "success": True,
            "team_name": auth_response.get("team"),
            "bot_user_id": auth_response.get("user_id"),
            "url": auth_response.get("url"),
        }

    except Exception as e:
        logger.error(f"Connection test failed for {workspace_id}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)


@router.post("/test-connection", response_model=dict)
async def test_connection(
    credentials: dict,
    current_user: dict = Depends(get_current_user)
):
    """Test real Slack workspace connection using existing backfill service"""
    try:
        from src.services.backfill_service import BackfillService
        from slack_sdk.web.async_client import AsyncWebClient
        
        bot_token = credentials.get("bot_token", "")
        
        if not bot_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bot token is required"
            )
        
        # Test connection using Slack client
        client = AsyncWebClient(token=bot_token)
        
        # Test auth
        auth_response = await client.auth_test()
        team_info = await client.team_info()
        
        # Get channels using backfill service
        backfill_service = BackfillService(workspace_id="test", bot_token=bot_token)
        channels = await backfill_service._get_all_channels()
        
        return {
            "success": True,
            "team_name": team_info["team"]["name"],
            "team_domain": team_info["team"].get("domain"),
            "team_id": team_info["team"]["id"],
            "bot_user_id": auth_response["user_id"],
            "channel_count": len(channels),
            "channels": [{
                "id": ch["id"],
                "name": ch["name"],
                "is_private": ch.get("is_private", False)
            } for ch in channels[:5]]  # First 5 channels
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing connection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_safe_error('connection_test')
        )

class BackfillRequest(BaseModel):
    days_back: int = 7

@router.post("/{workspace_id}/backfill", response_model=dict)
async def backfill_workspace(
    workspace_id: str,
    backfill_data: BackfillRequest,
    current_user: dict = Depends(get_current_user)
):
    """Backfill messages from Slack workspace"""
    try:
        from src.services.backfill_service import BackfillService
        
        logger.info(f"Backfill request for workspace {workspace_id} with {backfill_data.days_back} days")
        
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()
        
        # Get bot token from database
        cursor.execute("""
            SELECT i.bot_token FROM installations i
            JOIN workspaces w ON i.workspace_id = w.workspace_id
            WHERE w.workspace_id = %s AND w.org_id = %s
        """, (workspace_id, current_user.get("org_id", 8)))
        
        result = cursor.fetchone()
        if not result:
            logger.error(f"No credentials found for workspace {workspace_id} and org {current_user.get('org_id', 8)}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found or no credentials stored"
            )
        
        bot_token = result[0]
        logger.info(f"Found bot token for workspace {workspace_id}")
        
        # Initialize backfill service
        backfill_service = BackfillService(workspace_id=workspace_id, bot_token=bot_token)
        
        # Run backfill
        import asyncio
        asyncio.create_task(backfill_service.backfill_messages(days=backfill_data.days_back))
        
        return {
            "success": True,
            "workspace_id": workspace_id,
            "days_back": backfill_data.days_back,
            "status": "backfill_started"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during backfill: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=get_safe_error('backfill')
        )
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            DatabaseConnection.return_connection(conn)

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
        """, (workspace_id, current_user.get("org_id")))

        if not cursor.fetchone():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found"
            )

        # Get channels from channels table (populated by backfill)
        cursor.execute("""
            SELECT channel_id, channel_name
            FROM channels
            WHERE workspace_id = %s AND is_archived = FALSE
            ORDER BY channel_name
        """, (workspace_id,))

        channels = []
        for row in cursor.fetchall():
            channels.append({
                "id": row[0] or row[1],
                "name": row[1]
            })

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
            DatabaseConnection.return_connection(conn)