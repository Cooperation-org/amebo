"""
User repository for database operations.
"""

import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class UserRepository:
    """
    Handles database operations for users.
    """

    def __init__(self, db_connection, workspace_id: str = None):
        """
        Initialize repository with database connection.

        Args:
            db_connection: Database connection from connection pool
            workspace_id: Workspace ID for multi-tenant isolation (optional for compatibility)
        """
        self.conn = db_connection
        self.workspace_id = workspace_id

    def upsert_user(self, user: Dict, workspace_id: str = None) -> None:
        """
        Insert or update user profile.

        Args:
            user: User dict from Slack API
            workspace_id: Optional workspace ID (uses instance workspace_id if not provided)
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            INSERT INTO users (
                workspace_id, user_id, user_name, real_name, display_name,
                email, title, department, team_id, is_bot, is_admin,
                is_owner, is_restricted, timezone, avatar_url,
                status_text, status_emoji, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (workspace_id, user_id) DO UPDATE SET
                user_name = EXCLUDED.user_name,
                real_name = EXCLUDED.real_name,
                display_name = EXCLUDED.display_name,
                email = EXCLUDED.email,
                title = EXCLUDED.title,
                department = EXCLUDED.department,
                is_admin = EXCLUDED.is_admin,
                is_owner = EXCLUDED.is_owner,
                timezone = EXCLUDED.timezone,
                avatar_url = EXCLUDED.avatar_url,
                status_text = EXCLUDED.status_text,
                status_emoji = EXCLUDED.status_emoji,
                updated_at = NOW()
        """

        # Extract values from user dict
        user_id = user.get('id')
        user_name = user.get('name', '')

        profile = user.get('profile', {})
        real_name = user.get('real_name') or profile.get('real_name', '')
        display_name = profile.get('display_name', '')
        email = profile.get('email', '')
        title = profile.get('title', '')
        avatar_url = profile.get('image_512') or profile.get('image_192', '')
        status_text = profile.get('status_text', '')
        status_emoji = profile.get('status_emoji', '')

        # Department and team info
        department = profile.get('department', '')
        team_id = user.get('team_id', '')

        # User flags
        is_bot = user.get('is_bot', False)
        is_admin = user.get('is_admin', False)
        is_owner = user.get('is_owner', False)
        is_restricted = user.get('is_restricted', False)

        # Timezone
        timezone = user.get('tz', '')

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (
                    ws_id, user_id, user_name, real_name, display_name,
                    email, title, department, team_id, is_bot, is_admin,
                    is_owner, is_restricted, timezone, avatar_url,
                    status_text, status_emoji
                ))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to upsert user {user_id}: {e}")
            raise

    def get_user(self, user_id: str, workspace_id: str = None) -> Optional[Dict]:
        """
        Get user by ID.

        Args:
            user_id: User ID
            workspace_id: Optional workspace ID

        Returns:
            User dict or None
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            SELECT user_id, user_name, real_name, display_name, email,
                   title, department, team_id, is_bot, is_admin, is_owner,
                   timezone, avatar_url, status_text, status_emoji
            FROM users
            WHERE workspace_id = %s AND user_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (ws_id, user_id))
                row = cur.fetchone()

                if row:
                    return {
                        'user_id': row[0],
                        'user_name': row[1],
                        'real_name': row[2],
                        'display_name': row[3],
                        'email': row[4],
                        'title': row[5],
                        'department': row[6],
                        'team_id': row[7],
                        'is_bot': row[8],
                        'is_admin': row[9],
                        'is_owner': row[10],
                        'timezone': row[11],
                        'avatar_url': row[12],
                        'status_text': row[13],
                        'status_emoji': row[14]
                    }
                return None
        except Exception as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            raise

    def update_last_seen(self, user_id: str, workspace_id: str = None):
        """
        Update the last seen timestamp for a user.

        Args:
            user_id: User ID
            workspace_id: Optional workspace ID
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            UPDATE users
            SET last_seen = NOW()
            WHERE workspace_id = %s AND user_id = %s
        """

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (ws_id, user_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to update last seen for user {user_id}: {e}")
            raise

    def list_users(self, workspace_id: str = None, include_bots: bool = False):
        """
        List all users for a workspace.

        Args:
            workspace_id: Optional workspace ID
            include_bots: Whether to include bot users

        Returns:
            List of user dicts
        """
        ws_id = workspace_id or self.workspace_id or 'W_DEFAULT'

        query = """
            SELECT user_id, user_name, real_name, display_name, email, is_bot
            FROM users
            WHERE workspace_id = %s
        """

        params = [ws_id]

        if not include_bots:
            query += " AND is_bot = false"

        query += " ORDER BY user_name"

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

                return [
                    {
                        'user_id': row[0],
                        'user_name': row[1],
                        'real_name': row[2],
                        'display_name': row[3],
                        'email': row[4],
                        'is_bot': row[5]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            raise
