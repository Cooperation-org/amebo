"""
Slack OAuth routes - installation flow, workspace management
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from psycopg2 import extras
import logging
import os
import secrets
from urllib.parse import urlencode

from slack_sdk.oauth import AuthorizeUrlGenerator
from slack_sdk.web import WebClient
from slack_sdk.errors import SlackApiError

from src.api.models import (
    SlackOAuthStartResponse,
    SlackWorkspaceListResponse,
    SlackWorkspaceResponse
)
from src.api.auth_utils import get_current_user
from src.db.connection import DatabaseConnection

router = APIRouter()
logger = logging.getLogger(__name__)

# Slack OAuth configuration
SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# Required Slack scopes
SLACK_SCOPES = [
    "channels:history",
    "channels:read",
    "users:read",
    "reactions:read",
    "groups:history",
    "groups:read",
    "im:history",
    "mpim:history",
    "chat:write",
    "files:read",
    "links:read",
]


def generate_authorize_url(state: str) -> str:
    """Generate Slack OAuth authorization URL"""
    authorize_url_generator = AuthorizeUrlGenerator(
        client_id=SLACK_CLIENT_ID,
        scopes=SLACK_SCOPES,
        user_scopes=[]  # No user-level scopes needed
    )

    redirect_uri = f"{API_BASE_URL}/api/slack/callback"

    return authorize_url_generator.generate(
        state=state,
        redirect_uri=redirect_uri
    )


@router.get("/install", response_model=SlackOAuthStartResponse)
async def start_slack_oauth(current_user: dict = Depends(get_current_user)):
    """
    Start Slack OAuth flow
    Returns authorization URL for user to install app
    """
    if not SLACK_CLIENT_ID or not SLACK_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Slack OAuth not configured. Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET."
        )

    # Generate state parameter (includes user_id and org_id for callback)
    state_token = secrets.token_urlsafe(32)

    # Store state in database with user/org info
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oauth_states (state_token, user_id, org_id, expires_at)
                VALUES (%s, %s, %s, NOW() + INTERVAL '10 minutes')
                """,
                (state_token, current_user['user_id'], current_user['org_id'])
            )
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    # Generate authorization URL
    authorization_url = generate_authorize_url(state_token)

    logger.info(f"Starting Slack OAuth for user {current_user['email']}")

    return SlackOAuthStartResponse(
        authorization_url=authorization_url,
        state=state_token
    )


@router.get("/callback")
async def slack_oauth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """
    Slack OAuth callback endpoint
    Handles installation completion and redirects to frontend
    """
    # Handle OAuth errors
    if error:
        logger.error(f"Slack OAuth error: {error}")
        return RedirectResponse(
            url=f"{FRONTEND_URL}/settings/integrations?error=access_denied"
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter"
        )

    # Verify state and get user/org info
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Get and delete state token
            cur.execute(
                """
                DELETE FROM oauth_states
                WHERE state_token = %s
                  AND expires_at > NOW()
                RETURNING user_id, org_id
                """,
                (state,)
            )
            state_data = cur.fetchone()

            if not state_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired state token"
                )

            user_id = state_data['user_id']
            org_id = state_data['org_id']

            # Exchange code for access token
            client = WebClient()
            redirect_uri = f"{API_BASE_URL}/api/slack/callback"

            try:
                oauth_response = client.oauth_v2_access(
                    client_id=SLACK_CLIENT_ID,
                    client_secret=SLACK_CLIENT_SECRET,
                    code=code,
                    redirect_uri=redirect_uri
                )
            except SlackApiError as e:
                logger.error(f"Slack OAuth token exchange failed: {e}")
                return RedirectResponse(
                    url=f"{FRONTEND_URL}/settings/integrations?error=token_exchange_failed"
                )

            # Extract workspace and token info
            workspace_id = oauth_response['team']['id']
            team_name = oauth_response['team']['name']
            bot_token = oauth_response['access_token']

            # Get additional workspace info
            workspace_client = WebClient(token=bot_token)
            try:
                team_info = workspace_client.team_info()
                team_domain = team_info['team'].get('domain')
                icon_url = team_info['team'].get('icon', {}).get('image_132')
            except SlackApiError:
                team_domain = None
                icon_url = None

            # Check if workspace already exists
            cur.execute(
                "SELECT workspace_id FROM workspaces WHERE workspace_id = %s",
                (workspace_id,)
            )
            existing_workspace = cur.fetchone()

            if existing_workspace:
                # Update existing workspace
                cur.execute(
                    """
                    UPDATE workspaces
                    SET team_name = %s, team_domain = %s, icon_url = %s,
                        is_active = true, updated_at = NOW()
                    WHERE workspace_id = %s
                    """,
                    (team_name, team_domain, icon_url, workspace_id)
                )

                # Update installation
                cur.execute(
                    """
                    UPDATE installations
                    SET bot_token = %s, installed_by = %s, installed_at = NOW(),
                        last_active = NOW(), is_active = true
                    WHERE workspace_id = %s
                    """,
                    (bot_token, str(user_id), workspace_id)
                )
            else:
                # Create new workspace
                cur.execute(
                    """
                    INSERT INTO workspaces (workspace_id, team_name, team_domain, icon_url, plan, is_active)
                    VALUES (%s, %s, %s, %s, 'free', true)
                    """,
                    (workspace_id, team_name, team_domain, icon_url)
                )

                # Create installation record
                cur.execute(
                    """
                    INSERT INTO installations (workspace_id, bot_token, installed_by, installed_at, last_active, is_active)
                    VALUES (%s, %s, %s, NOW(), NOW(), true)
                    """,
                    (workspace_id, bot_token, str(user_id))
                )

            # Link workspace to organization
            cur.execute(
                """
                INSERT INTO org_workspaces (org_id, workspace_id, display_name, added_by, added_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (org_id, workspace_id) DO UPDATE
                SET display_name = EXCLUDED.display_name, added_at = NOW()
                """,
                (org_id, workspace_id, team_name, user_id)
            )

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, 'workspace_connected', 'workspace', %s, %s)
                """,
                (org_id, user_id, workspace_id,
                 extras.Json({'team_name': team_name, 'method': 'oauth'}))
            )

            conn.commit()

            logger.info(f"Slack workspace {team_name} ({workspace_id}) connected to org {org_id}")

            # Redirect to frontend success page
            return RedirectResponse(
                url=f"{FRONTEND_URL}/settings/integrations?success=true&workspace={team_name}"
            )

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Slack OAuth callback error: {e}", exc_info=True)
        return RedirectResponse(
            url=f"{FRONTEND_URL}/settings/integrations?error=installation_failed"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/workspaces", response_model=SlackWorkspaceListResponse)
async def list_workspaces(current_user: dict = Depends(get_current_user)):
    """
    List all Slack workspaces connected to this organization
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    w.workspace_id,
                    w.team_name,
                    w.team_domain,
                    w.icon_url,
                    w.is_active,
                    i.installed_at,
                    i.last_active
                FROM workspaces w
                JOIN org_workspaces ow ON w.workspace_id = ow.workspace_id
                JOIN installations i ON w.workspace_id = i.workspace_id
                WHERE ow.org_id = %s
                ORDER BY i.installed_at DESC
                """,
                (current_user['org_id'],)
            )
            workspaces = cur.fetchall()

            return SlackWorkspaceListResponse(
                workspaces=[SlackWorkspaceResponse(**ws) for ws in workspaces],
                total=len(workspaces)
            )
    finally:
        DatabaseConnection.return_connection(conn)


@router.delete("/workspaces/{workspace_id}")
async def disconnect_workspace(
    workspace_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Disconnect a Slack workspace from the organization
    """
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            # Verify workspace belongs to this org
            cur.execute(
                """
                SELECT ow.id, w.team_name
                FROM org_workspaces ow
                JOIN workspaces w ON ow.workspace_id = w.workspace_id
                WHERE ow.org_id = %s AND ow.workspace_id = %s
                """,
                (current_user['org_id'], workspace_id)
            )
            org_workspace = cur.fetchone()

            if not org_workspace:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Workspace not found or not connected to your organization"
                )

            # Delete org-workspace link
            cur.execute(
                "DELETE FROM org_workspaces WHERE org_id = %s AND workspace_id = %s",
                (current_user['org_id'], workspace_id)
            )

            # Deactivate installation if no other orgs are using it
            cur.execute(
                "SELECT COUNT(*) as count FROM org_workspaces WHERE workspace_id = %s",
                (workspace_id,)
            )
            other_orgs = cur.fetchone()['count']

            if other_orgs == 0:
                cur.execute(
                    "UPDATE installations SET is_active = false WHERE workspace_id = %s",
                    (workspace_id,)
                )
                cur.execute(
                    "UPDATE workspaces SET is_active = false WHERE workspace_id = %s",
                    (workspace_id,)
                )

            # Log audit event
            cur.execute(
                """
                INSERT INTO audit_logs (org_id, user_id, action, resource_type, resource_id, details)
                VALUES (%s, %s, 'workspace_disconnected', 'workspace', %s, %s)
                """,
                (current_user['org_id'], current_user['user_id'], workspace_id,
                 extras.Json({'team_name': org_workspace['team_name']}))
            )

            conn.commit()

            logger.info(f"Workspace {workspace_id} disconnected from org {current_user['org_id']}")

            return {"message": "Workspace disconnected successfully"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Disconnect workspace error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to disconnect workspace"
        )
    finally:
        DatabaseConnection.return_connection(conn)


@router.get("/install-button")
async def get_install_button():
    """
    Returns HTML for 'Add to Slack' button
    Useful for embedding in frontend
    """
    if not SLACK_CLIENT_ID:
        return HTMLResponse(
            content="<p>Slack OAuth not configured</p>",
            status_code=500
        )

    # This would be used by the frontend, but here's an example
    button_html = f"""
    <a href="https://slack.com/oauth/v2/authorize?{urlencode({
        'client_id': SLACK_CLIENT_ID,
        'scope': ','.join(SLACK_SCOPES),
        'redirect_uri': f'{API_BASE_URL}/api/slack/callback'
    })}">
        <img alt="Add to Slack"
             height="40"
             width="139"
             src="https://platform.slack-edge.com/img/add_to_slack.png"
             srcSet="https://platform.slack-edge.com/img/add_to_slack.png 1x, https://platform.slack-edge.com/img/add_to_slack@2x.png 2x" />
    </a>
    """

    return HTMLResponse(content=button_html)
