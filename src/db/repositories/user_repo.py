"""
User repository for database operations.
"""

import logging
from typing import Dict, Optional
from psycopg2 import extras
from datetime import datetime

logger = logging.getLogger(__name__)


class UserRepository:
    """
    Handles database operations for users.
    """

    def __init__(self, db_connection):
        """
        Initialize repository with database connection.

        Args:
            db_connection: Database connection from connection pool
        """
        self.conn = db_connection

    def upsert_user(self, user: Dict) -> str:
        """
        Insert or update a user.

        Args:
            user: User dict from Slack API

        Returns:
            user_id
        """
        query = """
            INSERT INTO users (
                user_id, user_name, real_name, display_name, email,
                title, department, team_id, is_bot, is_admin, is_owner,
                is_restricted, timezone, avatar_url, status_text,
                status_emoji, joined_at
            ) VALUES (
                %(user_id)s, %(user_name)s, %(real_name)s, %(display_name)s, %(email)s,
                %(title)s, %(department)s, %(team_id)s, %(is_bot)s, %(is_admin)s, %(is_owner)s,
                %(is_restricted)s, %(timezone)s, %(avatar_url)s, %(status_text)s,
                %(status_emoji)s, %(joined_at)s
            )
            ON CONFLICT (user_id) DO UPDATE SET
                user_name = EXCLUDED.user_name,
                real_name = EXCLUDED.real_name,
                display_name = EXCLUDED.display_name,
                email = EXCLUDED.email,
                title = EXCLUDED.title,
                department = EXCLUDED.department,
                is_admin = EXCLUDED.is_admin,
                is_owner = EXCLUDED.is_owner,
                status_text = EXCLUDED.status_text,
                status_emoji = EXCLUDED.status_emoji,
                updated_at = NOW()
            RETURNING user_id
        """

        profile = user.get('profile', {})

        params = {
            'user_id': user['id'],
            'user_name': user.get('name', ''),
            'real_name': user.get('real_name', profile.get('real_name', '')),
            'display_name': profile.get('display_name', ''),
            'email': profile.get('email', ''),
            'title': profile.get('title', ''),
            'department': profile.get('fields', {}).get('department', ''),
            'team_id': user.get('team_id', ''),
            'is_bot': user.get('is_bot', False),
            'is_admin': user.get('is_admin', False),
            'is_owner': user.get('is_owner', False),
            'is_restricted': user.get('is_restricted', False),
            'timezone': user.get('tz', ''),
            'avatar_url': profile.get('image_512', profile.get('image_192', '')),
            'status_text': profile.get('status_text', ''),
            'status_emoji': profile.get('status_emoji', ''),
            'joined_at': datetime.fromtimestamp(user['updated']) if 'updated' in user else None
        }

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, params)
                user_id = cur.fetchone()[0]
                self.conn.commit()
                return user_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to upsert user {user.get('id')}: {e}")
            raise

    def get_user(self, user_id: str) -> Optional[Dict]:
        """
        Get a user by ID.

        Args:
            user_id: User ID

        Returns:
            User dict or None
        """
        query = "SELECT * FROM users WHERE user_id = %s"

        try:
            with self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                cur.execute(query, (user_id,))
                return cur.fetchone()
        except Exception as e:
            logger.error(f"Failed to fetch user {user_id}: {e}")
            raise

    def user_exists(self, user_id: str) -> bool:
        """
        Check if user exists in database.

        Args:
            user_id: User ID

        Returns:
            True if exists, False otherwise
        """
        query = "SELECT 1 FROM users WHERE user_id = %s"

        try:
            with self.conn.cursor() as cur:
                cur.execute(query, (user_id,))
                return cur.fetchone() is not None
        except Exception as e:
            logger.error(f"Failed to check user existence {user_id}: {e}")
            raise
